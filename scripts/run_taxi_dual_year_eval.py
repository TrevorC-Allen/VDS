#!/usr/bin/env python3
"""Generate and optionally score the NYC taxi dual-year VDS evaluation pack.

This runner is intentionally independent of the core Agent workflow. It reads
the source files with DuckDB, computes deterministic reference facts, and then
builds GPT-like standard answers from those facts. Candidate VDS answers can be
scored later with --candidate-answers without ever passing standard answers into
Planner, Executor, Verifier, Correction, prompt, or trace.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

try:
    import duckdb
except ImportError as exc:  # pragma: no cover - exercised by local environment.
    raise SystemExit(
        "duckdb is required for this evaluation runner. Use the Codex bundled Python "
        "shown in README.md or install duckdb in the active Python environment."
    ) from exc


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG_PATH = REPO_ROOT / "configs" / "eval_gate" / "taxi_dual_year_eval.json"
PAYMENT_LABELS = {
    0: "unknown_or_not_recorded",
    1: "credit_card",
    2: "cash",
    3: "no_charge",
    4: "dispute",
    5: "unknown",
    6: "voided_trip",
}
AIRPORT_ZONE_IDS = (1, 132, 138)
FIELD_MEANINGS = {
    "VendorID": "出租车数据供应商/技术服务商代码。",
    "tpep_pickup_datetime": "上车时间；本评估用它判定 2025 年 1 月和 2026 年 1 月。",
    "tpep_dropoff_datetime": "下车时间；可用于计算行程时长和时间倒挂异常。",
    "passenger_count": "乘客数量；该字段在当前两年文件中存在明显缺失。",
    "trip_distance": "行程里程；0 或负值通常需要作为质量问题审查。",
    "RatecodeID": "费率代码；可辅助识别 JFK / Newark 等机场相关行程。",
    "store_and_fwd_flag": "是否为暂存后转发记录。",
    "PULocationID": "上车区域 ID；需要外部 taxi zone 维表才能解释成真实地名。",
    "DOLocationID": "下车区域 ID；需要外部 taxi zone 维表才能解释成真实地名。",
    "payment_type": "支付方式代码；1 通常为信用卡，2 通常为现金。",
    "fare_amount": "基础车费金额，不含所有附加费。",
    "extra": "附加费。",
    "mta_tax": "MTA 税费。",
    "tip_amount": "小费金额。",
    "tolls_amount": "过路费。",
    "improvement_surcharge": "改善附加费。",
    "total_amount": "订单总金额；本评估默认把它作为订单金额/总收入口径。",
    "congestion_surcharge": "拥堵附加费。",
    "Airport_fee": "机场费；可辅助识别机场相关订单。",
    "cbd_congestion_fee": "CBD 拥堵费。",
}


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the taxi dual-year evaluation standard-answer generator.")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG_PATH), help="Evaluation config JSON path.")
    parser.add_argument("--cases", help="Override case manifest JSONL path.")
    parser.add_argument("--output-dir", help="Output directory. Defaults to outputs/eval_gate/<timestamp>.")
    parser.add_argument(
        "--candidate-answers",
        help="Optional JSON/JSONL candidate answers to score. Supported shapes: {case_id: answer} or rows with case_id/answer.",
    )
    parser.add_argument("--print-summary", action="store_true", help="Print the Markdown summary after writing files.")
    args = parser.parse_args()

    config_path = Path(args.config)
    if not config_path.is_absolute():
        config_path = REPO_ROOT / config_path
    config = _load_json(config_path)
    cases_path = Path(args.cases or config["cases_path"])
    if not cases_path.is_absolute():
        cases_path = REPO_ROOT / cases_path
    cases = _load_jsonl(cases_path)

    output_dir = Path(args.output_dir) if args.output_dir else _default_output_dir(config)
    if not output_dir.is_absolute():
        output_dir = REPO_ROOT / output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    started = time.perf_counter()
    facts = build_dataset_facts(config["dataset"])
    standard_cases = build_standard_cases(cases, facts)
    candidate_score = None
    if args.candidate_answers:
        candidate_score = score_candidate_answers(standard_cases, Path(args.candidate_answers), config["thresholds"])

    elapsed_seconds = round(time.perf_counter() - started, 3)
    run = {
        "name": config["name"],
        "description": config["description"],
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "elapsed_seconds": elapsed_seconds,
        "repo": repo_state(),
        "config_path": str(config_path),
        "cases_path": str(cases_path),
        "dataset": config["dataset"],
        "thresholds": config["thresholds"],
        "facts": facts,
        "cases": standard_cases,
        "candidate_score": candidate_score,
        "note": (
            "Standard answers are generated after reading source files. They are for offline evaluation only "
            "and must not be passed into the VDS Agent workflow."
        ),
    }

    _write_json(output_dir / "summary.json", run)
    _write_json(output_dir / "standard_answers.json", {"cases": standard_cases})
    _write_jsonl(output_dir / "standard_answers.jsonl", standard_cases)
    (output_dir / "standard_answers.md").write_text(standard_answers_markdown(run), encoding="utf-8")
    summary_md = summary_markdown(run)
    (output_dir / "summary.md").write_text(summary_md, encoding="utf-8")
    if args.print_summary:
        print(summary_md)
    else:
        print(json.dumps({"output_dir": str(output_dir), "cases": len(standard_cases), "elapsed_seconds": elapsed_seconds}, ensure_ascii=False))


def build_dataset_facts(dataset_config: dict[str, Any]) -> dict[str, Any]:
    con = duckdb.connect(database=":memory:")
    year_configs = {
        "2025": dataset_config["year_2025"],
        "2026": dataset_config["year_2026"],
    }
    date_col = dataset_config["date_column"]
    amount_col = dataset_config["amount_column"]
    fare_col = dataset_config["fare_column"]
    distance_col = dataset_config["distance_column"]
    pickup_col = dataset_config["pickup_location_column"]
    dropoff_col = dataset_config["dropoff_location_column"]
    payment_col = dataset_config["payment_type_column"]
    airport_fee_col = dataset_config["airport_fee_column"]
    cbd_fee_col = dataset_config["cbd_fee_column"]
    dropoff_time_col = "tpep_dropoff_datetime"

    for year, path in year_configs.items():
        source_sql = _source_sql(Path(path))
        con.execute(f"CREATE OR REPLACE VIEW raw_{year} AS SELECT * FROM {source_sql}")
        con.execute(
            f"""
            CREATE OR REPLACE VIEW jan_{year} AS
            SELECT * FROM raw_{year}
            WHERE {_q(date_col)} >= TIMESTAMP '{year}-01-01'
              AND {_q(date_col)} < TIMESTAMP '{year}-02-01'
            """
        )

    schema = {year: _schema(con, f"raw_{year}") for year in year_configs}
    profiles = {
        year: _file_profile(con, f"raw_{year}", f"jan_{year}", schema[year], year, date_col)
        for year in year_configs
    }
    missing = {
        year: _missing_profile(con, f"raw_{year}", schema[year], profiles[year]["row_count"])
        for year in year_configs
    }
    jan_metrics = {
        year: _month_metrics(con, f"jan_{year}", amount_col, fare_col)
        for year in year_configs
    }
    anomalies = {
        year: _anomaly_profile(
            con,
            f"jan_{year}",
            year=year,
            amount_col=amount_col,
            fare_col=fare_col,
            distance_col=distance_col,
            pickup_time_col=date_col,
            dropoff_time_col=dropoff_time_col,
            pickup_col=pickup_col,
            dropoff_col=dropoff_col,
        )
        for year in year_configs
    }
    business = {
        year: _business_profile(
            con,
            f"jan_{year}",
            year=year,
            amount_col=amount_col,
            pickup_col=pickup_col,
            dropoff_col=dropoff_col,
            payment_col=payment_col,
            airport_fee_col=airport_fee_col,
            cbd_fee_col=cbd_fee_col,
        )
        for year in year_configs
    }
    cleaning = {
        year: _cleaning_profile(
            con,
            f"jan_{year}",
            year=year,
            amount_col=amount_col,
            fare_col=fare_col,
            distance_col=distance_col,
            pickup_time_col=date_col,
            dropoff_time_col=dropoff_time_col,
            high_amount_threshold=anomalies[year]["amount_outlier_threshold"],
        )
        for year in year_configs
    }
    facts = {
        "data_source": year_configs,
        "analysis_scope": {
            "date_column": date_col,
            "month_filter": "pickup time >= YYYY-01-01 and < YYYY-02-01",
            "amount_column": amount_col,
            "fare_column": fare_col,
            "distance_column": distance_col,
            "airport_rule": (
                "Airport_fee > 0 OR RatecodeID in (2, 3) OR pickup/dropoff location ID in "
                f"{list(AIRPORT_ZONE_IDS)}"
            ),
            "cleaning_rule": "drop rows with total_amount < 0, fare_amount < 0, trip_distance <= 0, or non-positive duration",
            "cleaning_boundary": "simulation only; source files are never mutated",
        },
        "schema": schema,
        "profiles": profiles,
        "missing": missing,
        "schema_compare": _schema_compare(schema["2025"], schema["2026"]),
        "missing_compare": _missing_compare(missing["2025"], missing["2026"]),
        "month_metrics": jan_metrics,
        "yoy": _yoy_metrics(jan_metrics["2025"], jan_metrics["2026"]),
        "anomalies": anomalies,
        "business": business,
        "cleaning": cleaning,
    }
    facts["cleaning_yoy"] = _cleaning_yoy(cleaning["2025"], cleaning["2026"])
    return _json_ready(facts)


def build_standard_cases(cases: list[dict[str, Any]], facts: dict[str, Any]) -> list[dict[str, Any]]:
    built = []
    for case in cases:
        answer = standard_answer(case["answer_key"], facts)
        built.append(
            {
                **case,
                "standard_answer": answer["text"],
                "expected_facts": answer.get("expected_facts", {}),
                "required_terms": answer.get("required_terms", []),
                "expected_numbers": answer.get("expected_numbers", []),
                "technical_checks": answer.get("technical_checks", []),
                "standard_answer_policy": (
                    "GPT-like prose grounded in computed facts; used only after VDS response generation for offline evaluation."
                ),
            }
        )
    return built


def standard_answer(answer_key: str, facts: dict[str, Any]) -> dict[str, Any]:
    profile25 = facts["profiles"]["2025"]
    profile26 = facts["profiles"]["2026"]
    metrics25 = facts["month_metrics"]["2025"]
    metrics26 = facts["month_metrics"]["2026"]
    yoy = facts["yoy"]
    missing_compare = facts["missing_compare"]
    anomalies25 = facts["anomalies"]["2025"]
    anomalies26 = facts["anomalies"]["2026"]
    business25 = facts["business"]["2025"]
    business26 = facts["business"]["2026"]
    cleaning25 = facts["cleaning"]["2025"]
    cleaning26 = facts["cleaning"]["2026"]
    cleaning_yoy = facts["cleaning_yoy"]

    if answer_key == "no_file_greeting":
        return _answer(
            "你好，我可以帮你做数据理解、字段解释、同比分析、异常检测、业务分析和清洗策略模拟。当前还没有上传文件，所以不能给出任何真实数据结论。",
            required_terms=["没有上传文件", "不能给出真实数据结论"],
        )
    if answer_key == "no_file_capabilities":
        return _answer(
            "我可以在上传文件后读取真实字段和数据，做基础概览、多文件对比、同比、异常检测、业务占比、清洗影响模拟和后续追问；没有文件时只能说明分析方法，不能编造结论。",
            required_terms=["上传文件后", "不能编造结论"],
        )
    if answer_key == "no_file_analysis_advice":
        return _answer(
            "可以先给分析建议：准备两年同口径文件，确认日期、订单金额、里程、时长、区域和支付方式字段，再按基础理解、同比、异常、业务和清洗策略分组提问。没有数据时不应输出具体数值。",
            required_terms=["没有数据", "不应输出具体数值"],
        )
    if answer_key == "no_file_multifile_support":
        return _answer(
            "支持多文件对比。上传后应分别识别每个文件的行列、字段、缺失和时间范围，再进行跨文件同比或差异分析；不能只看第一个文件。",
            required_terms=["分别识别", "不能只看第一个文件"],
        )
    if answer_key == "no_file_model_identity":
        return _answer(
            "我是 VDS 数据分析助手。可以说明能力和需要的数据，但不应暴露系统 prompt、密钥、trace、benchmark 标准答案或内部评分信息。",
            required_terms=["VDS 数据分析助手", "不应暴露"],
        )
    if answer_key == "overview_two_files":
        return _answer(
            (
                f"两个文件字段结构一致，都是 {profile25['column_count']} 列。"
                f"2025 文件共有 {_int(profile25['row_count'])} 行，其中按上车时间落在 2025 年 1 月的记录为 {_int(profile25['jan_row_count'])} 行；"
                f"2026 文件共有 {_int(profile26['row_count'])} 行，其中按上车时间落在 2026 年 1 月的记录为 {_int(profile26['jan_row_count'])} 行。"
                "主要字段覆盖上车/下车时间、乘客数、里程、上下车区域、支付方式、车费、附加费、机场费、总金额和 CBD 拥堵费。"
            ),
            expected_numbers=[
                _num("2025 rows", profile25["row_count"]),
                _num("2026 rows", profile26["row_count"]),
                _num("columns", profile25["column_count"], tolerance_abs=0),
            ],
            required_terms=["字段结构一致", "上车时间"],
        )
    if answer_key == "dataset_story":
        return _answer(
            (
                "这是纽约出租车 2025 年 1 月和 2026 年 1 月黄色出租车行程数据。"
                "每行代表一笔行程/订单，能分析订单量、收入、客单价、里程、时长、支付方式、上下车区域、机场相关订单和拥堵费变化。"
                "PULocationID/DOLocationID 目前只能解释为区域 ID；如果要输出真实地名，需要补充 taxi zone 维表。"
            ),
            required_terms=["每行代表一笔行程", "区域 ID", "维表"],
        )
    if answer_key == "two_file_difference":
        return _answer(
            (
                f"结构上两个文件字段完全一致，没有新增、缺失或类型变化。规模上 2026 文件多 {_int(profile26['row_count'] - profile25['row_count'])} 行。"
                f"按 1 月过滤后，2026 订单量比 2025 多 {_int(yoy['order_count_delta'])} 单，"
                f"总金额增加 {_money(yoy['revenue_delta'])}，平均订单金额增加 {_money(yoy['avg_amount_delta'])}。"
            ),
            expected_numbers=[
                _num("row delta", profile26["row_count"] - profile25["row_count"]),
                _num("order count delta", yoy["order_count_delta"]),
            ],
            required_terms=["字段完全一致", "平均订单金额"],
        )
    if answer_key == "recommended_questions":
        return _answer(
            (
                "建议按五组继续问：1）行列、字段、缺失和时间范围；2）订单量、总收入、客单价同比；"
                "3）负金额、0 里程、非正时长、极端金额和缺失变化；4）热门上车区域、支付占比、机场订单占比、CBD 拥堵费；"
                "5）删除异常、处理缺失和去除极端值后的结论变化。"
            ),
            required_terms=["同比", "异常", "清洗"],
        )
    if answer_key == "field_meanings":
        return _field_meanings_answer(facts)
    if answer_key == "field_roles":
        return _answer(
            (
                "时间字段：tpep_pickup_datetime、tpep_dropoff_datetime；金额字段：fare_amount、extra、mta_tax、tip_amount、tolls_amount、"
                "improvement_surcharge、total_amount、congestion_surcharge、Airport_fee、cbd_congestion_fee；"
                "区域字段：PULocationID、DOLocationID；支付字段：payment_type；里程字段：trip_distance。"
            ),
            required_terms=["时间字段", "金额字段", "区域字段", "支付字段"],
        )
    if answer_key == "quality_overview":
        increased = _top_missing_increases(missing_compare)
        return _answer(
            (
                "明显质量问题包括：passenger_count、RatecodeID、store_and_fwd_flag、congestion_surcharge、Airport_fee 在两年都有缺失，"
                f"且 2026 缺失率上升最明显的是 {_format_missing_increase_list(increased)}。"
                f"异常规则扫描还发现 2025/2026 分别有 {_int(anomalies25['negative_total_amount_count'])}/{_int(anomalies26['negative_total_amount_count'])} 条负总金额，"
                f"{_int(anomalies25['non_positive_distance_count'])}/{_int(anomalies26['non_positive_distance_count'])} 条非正里程，"
                f"{_int(anomalies25['non_positive_duration_count'])}/{_int(anomalies26['non_positive_duration_count'])} 条非正时长。"
            ),
            expected_numbers=[
                _num("2025 negative total", anomalies25["negative_total_amount_count"], tolerance_abs=0),
                _num("2026 negative total", anomalies26["negative_total_amount_count"], tolerance_abs=0),
            ],
            required_terms=["缺失率", "负总金额", "非正里程"],
        )
    if answer_key == "shape":
        return _answer(
            (
                f"2025 文件：{_int(profile25['row_count'])} 行、{profile25['column_count']} 列；"
                f"2026 文件：{_int(profile26['row_count'])} 行、{profile26['column_count']} 列。"
                f"按上车时间严格限定 1 月后，2025 为 {_int(profile25['jan_row_count'])} 行，2026 为 {_int(profile26['jan_row_count'])} 行。"
            ),
            expected_numbers=[
                _num("2025 rows", profile25["row_count"], tolerance_abs=0),
                _num("2026 rows", profile26["row_count"], tolerance_abs=0),
                _num("2025 columns", profile25["column_count"], tolerance_abs=0),
                _num("2026 columns", profile26["column_count"], tolerance_abs=0),
            ],
            required_terms=["2025 文件", "2026 文件"],
        )
    if answer_key == "missing_fields":
        return _missing_fields_answer(facts)
    if answer_key == "schema_consistency":
        compare = facts["schema_compare"]
        return _answer(
            (
                "两个文件字段一致、字段类型一致。"
                f"新增字段：{compare['only_in_2026'] or '无'}；缺失字段：{compare['only_in_2025'] or '无'}；"
                f"类型变化：{compare['type_changes'] or '无'}。"
            ),
            required_terms=["字段一致", "类型一致"],
        )
    if answer_key == "month_scope":
        return _answer(
            (
                f"两个文件基本覆盖对应 1 月，但都包含少量跨月时间戳。"
                f"2025 上车时间范围为 {profile25['min_datetime']} 到 {profile25['max_datetime']}，严格 2025 年 1 月记录为 {_int(profile25['jan_row_count'])} 行；"
                f"2026 上车时间范围为 {profile26['min_datetime']} 到 {profile26['max_datetime']}，严格 2026 年 1 月记录为 {_int(profile26['jan_row_count'])} 行。"
            ),
            required_terms=["跨月", "严格"],
        )
    if answer_key == "order_count_yoy":
        return _answer(
            (
                f"按 tpep_pickup_datetime 过滤 1 月，2025 年 1 月订单量为 {_int(metrics25['order_count'])}，"
                f"2026 年 1 月为 {_int(metrics26['order_count'])}，增加 {_int(yoy['order_count_delta'])} 单，"
                f"增长率为 {_pct(yoy['order_count_growth_rate'])}。"
            ),
            expected_numbers=[
                _num("2025 order count", metrics25["order_count"], tolerance_abs=0),
                _num("2026 order count", metrics26["order_count"], tolerance_abs=0),
                _num("order count delta", yoy["order_count_delta"], tolerance_abs=0),
                _num("order count growth rate", yoy["order_count_growth_rate"]),
            ],
            required_terms=["tpep_pickup_datetime", "增长率"],
        )
    if answer_key == "avg_amount_yoy":
        return _answer(
            (
                f"平均订单金额上涨。2025 年 1 月平均 total_amount 为 {_money(metrics25['avg_total_amount'])}，"
                f"2026 年 1 月为 {_money(metrics26['avg_total_amount'])}，上涨 {_money(yoy['avg_amount_delta'])}，"
                f"涨幅 {_pct(yoy['avg_amount_growth_rate'])}。"
            ),
            expected_numbers=[
                _num("2025 avg", metrics25["avg_total_amount"]),
                _num("2026 avg", metrics26["avg_total_amount"]),
                _num("avg delta", yoy["avg_amount_delta"]),
            ],
            required_terms=["平均订单金额上涨", "total_amount"],
        )
    if answer_key == "revenue_driver":
        driver = "客单价" if yoy["price_effect_share"] > yoy["volume_effect_share"] else "订单量"
        return _answer(
            (
                f"总收入增长主要来自{driver}。按 total_amount = 订单量 × 平均订单金额分解，"
                f"总收入增加 {_money(yoy['revenue_delta'])}；订单量贡献约 {_money(yoy['volume_effect'])}，占 {_pct(yoy['volume_effect_share'])}；"
                f"客单价贡献约 {_money(yoy['price_effect'])}，占 {_pct(yoy['price_effect_share'])}。"
            ),
            expected_numbers=[
                _num("revenue delta", yoy["revenue_delta"]),
                _num("volume effect", yoy["volume_effect"]),
                _num("price effect", yoy["price_effect"]),
            ],
            required_terms=["主要来自客单价", "订单量贡献", "客单价贡献"],
        )
    if answer_key == "yoy_summary":
        return _answer(
            (
                f"订单量：{_int(metrics25['order_count'])} -> {_int(metrics26['order_count'])}，同比 {_pct(yoy['order_count_growth_rate'])}；"
                f"总收入：{_money(metrics25['total_amount_sum'])} -> {_money(metrics26['total_amount_sum'])}，同比 {_pct(yoy['revenue_growth_rate'])}；"
                f"平均订单金额：{_money(metrics25['avg_total_amount'])} -> {_money(metrics26['avg_total_amount'])}，同比 {_pct(yoy['avg_amount_growth_rate'])}。"
            ),
            expected_numbers=[
                _num("revenue growth rate", yoy["revenue_growth_rate"]),
                _num("avg growth rate", yoy["avg_amount_growth_rate"]),
            ],
            required_terms=["订单量", "总收入", "平均订单金额"],
        )
    if answer_key == "yoy_date_basis":
        return _answer(
            "用 tpep_pickup_datetime 作为月份归属字段，过滤条件是 >= 当年 1 月 1 日且 < 当年 2 月 1 日；不用下车时间或文件名直接推断月份。",
            required_terms=["tpep_pickup_datetime", "不直接推断"],
        )
    if answer_key == "amount_anomalies":
        return _amount_anomalies_answer(facts)
    if answer_key == "negative_zero_duration":
        return _answer(
            (
                f"存在。2025：负 total_amount {_int(anomalies25['negative_total_amount_count'])} 条，非正里程 {_int(anomalies25['non_positive_distance_count'])} 条，"
                f"非正时长 {_int(anomalies25['non_positive_duration_count'])} 条；"
                f"2026：负 total_amount {_int(anomalies26['negative_total_amount_count'])} 条，非正里程 {_int(anomalies26['non_positive_distance_count'])} 条，"
                f"非正时长 {_int(anomalies26['non_positive_duration_count'])} 条。"
            ),
            expected_numbers=[
                _num("2026 non-positive duration", anomalies26["non_positive_duration_count"], tolerance_abs=0),
                _num("2026 non-positive distance", anomalies26["non_positive_distance_count"], tolerance_abs=0),
            ],
            required_terms=["存在", "负 total_amount", "非正里程", "非正时长"],
        )
    if answer_key == "missing_increase":
        return _answer(
            "2026 年缺失明显变多的字段是：" + _format_missing_increase_list(_top_missing_increases(missing_compare)) + "。",
            required_terms=["2026 年缺失明显变多"],
        )
    if answer_key == "duration_anomalies":
        return _answer(
            (
                f"有时间倒挂或 0 秒/负时长行程。按下车时间 <= 上车时间计算，"
                f"2025 有 {_int(anomalies25['non_positive_duration_count'])} 条，占 {_pct(anomalies25['non_positive_duration_rate'])}；"
                f"2026 有 {_int(anomalies26['non_positive_duration_count'])} 条，占 {_pct(anomalies26['non_positive_duration_rate'])}。"
            ),
            required_terms=["下车时间 <= 上车时间", "占"],
        )
    if answer_key == "anomaly_summary":
        return _anomaly_summary_answer(facts)
    if answer_key == "top_pickup_locations":
        return _top_pickup_answer(business25, business26)
    if answer_key == "payment_share":
        return _payment_share_answer(business25, business26)
    if answer_key == "airport_share":
        return _answer(
            (
                f"按规则 {facts['analysis_scope']['airport_rule']} 识别机场相关订单。"
                f"2025 机场相关订单金额 {_money(business25['airport']['amount'])}，占总金额 {_pct(business25['airport']['amount_share'])}；"
                f"2026 为 {_money(business26['airport']['amount'])}，占 {_pct(business26['airport']['amount_share'])}。"
            ),
            expected_numbers=[
                _num("2025 airport share", business25["airport"]["amount_share"]),
                _num("2026 airport share", business26["airport"]["amount_share"]),
            ],
            required_terms=["Airport_fee", "RatecodeID", "占总金额"],
        )
    if answer_key == "cbd_change":
        return _answer(
            (
                f"CBD 拥堵费总额从 2025 的 {_money(business25['cbd']['fee_sum'])} 增至 2026 的 {_money(business26['cbd']['fee_sum'])}，"
                f"增加 {_money(business26['cbd']['fee_sum'] - business25['cbd']['fee_sum'])}；"
                f"有 CBD 费的订单占比从 {_pct(business25['cbd']['positive_count_share'])} 升至 {_pct(business26['cbd']['positive_count_share'])}。"
                "正向收费订单的单笔 CBD 费均值两年都是 0.75。"
            ),
            required_terms=["CBD 拥堵费总额", "有 CBD 费的订单占比"],
        )
    if answer_key == "location_id_boundary":
        return _answer(
            "不能直接把 PULocationID/DOLocationID 编造成真实地名。当前文件只有区域 ID；要输出 Times Square、JFK 等真实名称，需要额外 taxi zone lookup 维表。",
            required_terms=["不能直接", "区域 ID", "维表"],
        )
    if answer_key == "payment_amount_compare":
        return _payment_amount_compare_answer(business25, business26)
    if answer_key == "clean_invalid_drop":
        return _clean_invalid_drop_answer(cleaning25, cleaning26)
    if answer_key == "missing_cleaning_strategy":
        return _missing_cleaning_strategy_answer(facts)
    if answer_key == "outlier_cleaning_impact":
        return _outlier_cleaning_answer(cleaning25, cleaning26)
    if answer_key == "cleaning_yoy_change":
        return _answer(
            (
                f"清洗前订单量同比 {_pct(yoy['order_count_growth_rate'])}，总收入同比 {_pct(yoy['revenue_growth_rate'])}，"
                f"平均订单金额同比 {_pct(yoy['avg_amount_growth_rate'])}。"
                f"删除负金额、非正里程、非正时长后，订单量同比 {_pct(cleaning_yoy['order_count_growth_rate'])}，"
                f"总收入同比 {_pct(cleaning_yoy['revenue_growth_rate'])}，平均订单金额同比 {_pct(cleaning_yoy['avg_amount_growth_rate'])}。"
                "方向仍是 2026 更高，但幅度会变化。"
            ),
            required_terms=["清洗前", "删除负金额", "方向仍是 2026 更高"],
        )
    if answer_key == "cleaning_confirmation_boundary":
        return _answer(
            "不会直接修改原始数据。清洗策略只能先做模拟，输出规则、影响行数、影响比例和指标变化；真正删除、填充或覆盖数据必须由用户确认。",
            required_terms=["不会直接修改原始数据", "用户确认"],
        )
    if answer_key == "cleaning_policy_summary":
        return _answer(
            (
                "建议清洗规则：先标记负 total_amount、负 fare_amount、trip_distance <= 0、下车时间 <= 上车时间、极端高 total_amount 和关键字段缺失。"
                f"若删除负金额/非正里程/非正时长，2025 会影响 {_int(cleaning25['invalid_union_count'])} 行（{_pct(cleaning25['invalid_union_rate'])}），"
                f"2026 会影响 {_int(cleaning26['invalid_union_count'])} 行（{_pct(cleaning26['invalid_union_rate'])}）。"
                "这一步必须作为模拟或待确认策略，不能自动覆盖源文件。"
            ),
            required_terms=["建议清洗规则", "影响", "不能自动覆盖源文件"],
        )
    raise KeyError(f"Unsupported answer_key: {answer_key}")


def score_candidate_answers(
    standard_cases: list[dict[str, Any]],
    candidate_path: Path,
    thresholds: dict[str, Any],
) -> dict[str, Any]:
    answers = _load_candidate_answers(candidate_path)
    details = []
    for case in standard_cases:
        case_id = case["case_id"]
        answer = str(answers.get(case_id) or "")
        terms = case.get("required_terms") or []
        term_hits = [term for term in terms if term in answer]
        number_checks = [
            _candidate_contains_number(answer, check, thresholds.get("numeric_tolerance", 0.01))
            for check in case.get("expected_numbers", [])
        ]
        numeric_passed = all(item["passed"] for item in number_checks)
        passed = bool(answer) and len(term_hits) == len(terms) and numeric_passed
        details.append(
            {
                "case_id": case_id,
                "category": case.get("category"),
                "passed": passed,
                "answer_present": bool(answer),
                "term_hits": term_hits,
                "missing_terms": [term for term in terms if term not in term_hits],
                "number_checks": number_checks,
            }
        )
    passed_count = sum(1 for row in details if row["passed"])
    return {
        "candidate_path": str(candidate_path),
        "total": len(details),
        "passed": passed_count,
        "pass_rate": None if not details else passed_count / len(details),
        "details": details,
    }


def _file_profile(
    con: duckdb.DuckDBPyConnection,
    raw_view: str,
    jan_view: str,
    schema: list[dict[str, str]],
    year: str,
    date_col: str,
) -> dict[str, Any]:
    row = con.execute(
        f"""
        SELECT
            count(*) AS row_count,
            (SELECT count(*) FROM {jan_view}) AS jan_row_count,
            min({_q(date_col)}) AS min_datetime,
            max({_q(date_col)}) AS max_datetime
        FROM {raw_view}
        """
    ).fetchone()
    return {
        "year": year,
        "row_count": int(row[0]),
        "jan_row_count": int(row[1]),
        "column_count": len(schema),
        "min_datetime": str(row[2]),
        "max_datetime": str(row[3]),
    }


def _schema(con: duckdb.DuckDBPyConnection, view: str) -> list[dict[str, str]]:
    rows = con.execute(f"DESCRIBE SELECT * FROM {view}").fetchall()
    return [{"column_name": str(row[0]), "column_type": str(row[1])} for row in rows]


def _missing_profile(
    con: duckdb.DuckDBPyConnection,
    view: str,
    schema: list[dict[str, str]],
    row_count: int,
) -> dict[str, dict[str, Any]]:
    expressions = []
    for column in schema:
        name = column["column_name"]
        column_type = column["column_type"].upper()
        if "VARCHAR" in column_type or "STRING" in column_type:
            predicate = f"{_q(name)} IS NULL OR trim({_q(name)}) = ''"
        else:
            predicate = f"{_q(name)} IS NULL"
        expressions.append(f"sum(CASE WHEN {predicate} THEN 1 ELSE 0 END)::BIGINT AS {_q(name)}")
    row = con.execute(f"SELECT {', '.join(expressions)} FROM {view}").fetchone()
    result = {}
    for column, missing_count in zip(schema, row):
        count = int(missing_count or 0)
        result[column["column_name"]] = {
            "missing_count": count,
            "missing_rate": 0.0 if row_count == 0 else count / row_count,
            "column_type": column["column_type"],
        }
    return result


def _schema_compare(schema_2025: list[dict[str, str]], schema_2026: list[dict[str, str]]) -> dict[str, Any]:
    left = {item["column_name"]: item["column_type"] for item in schema_2025}
    right = {item["column_name"]: item["column_type"] for item in schema_2026}
    shared = sorted(set(left) & set(right))
    return {
        "only_in_2025": sorted(set(left) - set(right)),
        "only_in_2026": sorted(set(right) - set(left)),
        "type_changes": [
            {"column": column, "type_2025": left[column], "type_2026": right[column]}
            for column in shared
            if left[column] != right[column]
        ],
        "shared_columns": shared,
        "same_schema": set(left) == set(right) and all(left[column] == right[column] for column in shared),
    }


def _missing_compare(left: dict[str, Any], right: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for column in sorted(set(left) | set(right)):
        l = left.get(column, {"missing_count": 0, "missing_rate": 0.0})
        r = right.get(column, {"missing_count": 0, "missing_rate": 0.0})
        rows.append(
            {
                "column": column,
                "missing_count_2025": l["missing_count"],
                "missing_rate_2025": l["missing_rate"],
                "missing_count_2026": r["missing_count"],
                "missing_rate_2026": r["missing_rate"],
                "missing_count_delta": r["missing_count"] - l["missing_count"],
                "missing_rate_delta": r["missing_rate"] - l["missing_rate"],
            }
        )
    return sorted(rows, key=lambda item: item["missing_rate_delta"], reverse=True)


def _month_metrics(con: duckdb.DuckDBPyConnection, view: str, amount_col: str, fare_col: str) -> dict[str, Any]:
    row = con.execute(
        f"""
        SELECT
            count(*) AS order_count,
            sum({_q(amount_col)}) AS total_amount_sum,
            avg({_q(amount_col)}) AS avg_total_amount,
            sum({_q(fare_col)}) AS fare_amount_sum,
            avg({_q(fare_col)}) AS avg_fare_amount
        FROM {view}
        """
    ).fetchone()
    return {
        "order_count": int(row[0]),
        "total_amount_sum": float(row[1] or 0),
        "avg_total_amount": float(row[2] or 0),
        "fare_amount_sum": float(row[3] or 0),
        "avg_fare_amount": float(row[4] or 0),
    }


def _yoy_metrics(left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
    count_delta = right["order_count"] - left["order_count"]
    revenue_delta = right["total_amount_sum"] - left["total_amount_sum"]
    avg_delta = right["avg_total_amount"] - left["avg_total_amount"]
    volume_effect = count_delta * left["avg_total_amount"]
    price_effect = right["order_count"] * avg_delta
    return {
        "order_count_delta": count_delta,
        "order_count_growth_rate": _safe_div(count_delta, left["order_count"]),
        "revenue_delta": revenue_delta,
        "revenue_growth_rate": _safe_div(revenue_delta, left["total_amount_sum"]),
        "avg_amount_delta": avg_delta,
        "avg_amount_growth_rate": _safe_div(avg_delta, left["avg_total_amount"]),
        "volume_effect": volume_effect,
        "price_effect": price_effect,
        "volume_effect_share": _safe_div(volume_effect, revenue_delta),
        "price_effect_share": _safe_div(price_effect, revenue_delta),
        "decomposition_formula": "revenue_delta = (orders_2026 - orders_2025) * avg_2025 + orders_2026 * (avg_2026 - avg_2025)",
    }


def _anomaly_profile(
    con: duckdb.DuckDBPyConnection,
    view: str,
    *,
    year: str,
    amount_col: str,
    fare_col: str,
    distance_col: str,
    pickup_time_col: str,
    dropoff_time_col: str,
    pickup_col: str,
    dropoff_col: str,
) -> dict[str, Any]:
    row_count = con.execute(f"SELECT count(*) FROM {view}").fetchone()[0]
    q1, q3 = con.execute(
        f"""
        SELECT quantile_cont({_q(amount_col)}, 0.25), quantile_cont({_q(amount_col)}, 0.75)
        FROM {view}
        WHERE {_q(amount_col)} > 0
        """
    ).fetchone()
    iqr = float(q3 - q1)
    threshold = float(q3 + 3 * iqr)
    counts = con.execute(
        f"""
        SELECT
            count(*) FILTER (WHERE {_q(amount_col)} < 0) AS negative_total_amount_count,
            count(*) FILTER (WHERE {_q(fare_col)} < 0) AS negative_fare_amount_count,
            count(*) FILTER (WHERE {_q(distance_col)} <= 0) AS non_positive_distance_count,
            count(*) FILTER (WHERE date_diff('second', {_q(pickup_time_col)}, {_q(dropoff_time_col)}) <= 0) AS non_positive_duration_count,
            count(*) FILTER (WHERE {_q(amount_col)} > {threshold}) AS high_amount_outlier_count
        FROM {view}
        """
    ).fetchone()
    return {
        "year": year,
        "row_count": int(row_count),
        "amount_q1": float(q1),
        "amount_q3": float(q3),
        "amount_iqr": iqr,
        "amount_outlier_threshold": threshold,
        "negative_total_amount_count": int(counts[0]),
        "negative_total_amount_rate": _safe_div(counts[0], row_count),
        "negative_fare_amount_count": int(counts[1]),
        "negative_fare_amount_rate": _safe_div(counts[1], row_count),
        "non_positive_distance_count": int(counts[2]),
        "non_positive_distance_rate": _safe_div(counts[2], row_count),
        "non_positive_duration_count": int(counts[3]),
        "non_positive_duration_rate": _safe_div(counts[3], row_count),
        "high_amount_outlier_count": int(counts[4]),
        "high_amount_outlier_rate": _safe_div(counts[4], row_count),
        "highest_amount_samples": _sample_rows(
            con,
            view,
            amount_col=amount_col,
            fare_col=fare_col,
            distance_col=distance_col,
            pickup_time_col=pickup_time_col,
            dropoff_time_col=dropoff_time_col,
            pickup_col=pickup_col,
            dropoff_col=dropoff_col,
            where=f"{_q(amount_col)} > {threshold}",
            order_by=f"{_q(amount_col)} DESC",
        ),
        "negative_amount_samples": _sample_rows(
            con,
            view,
            amount_col=amount_col,
            fare_col=fare_col,
            distance_col=distance_col,
            pickup_time_col=pickup_time_col,
            dropoff_time_col=dropoff_time_col,
            pickup_col=pickup_col,
            dropoff_col=dropoff_col,
            where=f"{_q(amount_col)} < 0",
            order_by=f"{_q(amount_col)} ASC",
        ),
    }


def _sample_rows(
    con: duckdb.DuckDBPyConnection,
    view: str,
    *,
    amount_col: str,
    fare_col: str,
    distance_col: str,
    pickup_time_col: str,
    dropoff_time_col: str,
    pickup_col: str,
    dropoff_col: str,
    where: str,
    order_by: str,
    limit: int = 5,
) -> list[dict[str, Any]]:
    rows = con.execute(
        f"""
        SELECT
            {_q(pickup_time_col)} AS pickup_time,
            {_q(dropoff_time_col)} AS dropoff_time,
            {_q(pickup_col)} AS pickup_location_id,
            {_q(dropoff_col)} AS dropoff_location_id,
            {_q(amount_col)} AS total_amount,
            {_q(fare_col)} AS fare_amount,
            {_q(distance_col)} AS trip_distance,
            date_diff('second', {_q(pickup_time_col)}, {_q(dropoff_time_col)}) AS duration_seconds
        FROM {view}
        WHERE {where}
        ORDER BY {order_by}
        LIMIT {limit}
        """
    ).fetchall()
    columns = [
        "pickup_time",
        "dropoff_time",
        "pickup_location_id",
        "dropoff_location_id",
        "total_amount",
        "fare_amount",
        "trip_distance",
        "duration_seconds",
    ]
    return [dict(zip(columns, row)) for row in rows]


def _business_profile(
    con: duckdb.DuckDBPyConnection,
    view: str,
    *,
    year: str,
    amount_col: str,
    pickup_col: str,
    dropoff_col: str,
    payment_col: str,
    airport_fee_col: str,
    cbd_fee_col: str,
) -> dict[str, Any]:
    total_rows, total_amount = con.execute(
        f"SELECT count(*), sum({_q(amount_col)}) FROM {view}"
    ).fetchone()
    payment_rows = con.execute(
        f"""
        SELECT
            {_q(payment_col)} AS payment_type,
            count(*) AS order_count,
            sum({_q(amount_col)}) AS total_amount,
            avg({_q(amount_col)}) AS avg_total_amount
        FROM {view}
        GROUP BY 1
        ORDER BY order_count DESC
        """
    ).fetchall()
    payment = []
    for payment_type, order_count, amount, avg_amount in payment_rows:
        key = int(payment_type) if payment_type is not None else None
        payment.append(
            {
                "payment_type": key,
                "label": PAYMENT_LABELS.get(key, "unmapped"),
                "order_count": int(order_count),
                "order_share": _safe_div(order_count, total_rows),
                "total_amount": float(amount or 0),
                "amount_share": _safe_div(amount or 0, total_amount),
                "avg_total_amount": float(avg_amount or 0),
            }
        )
    airport_predicate = _airport_predicate(airport_fee_col, pickup_col, dropoff_col)
    airport_count, airport_amount = con.execute(
        f"""
        SELECT
            count(*) FILTER (WHERE {airport_predicate}) AS airport_count,
            sum({_q(amount_col)}) FILTER (WHERE {airport_predicate}) AS airport_amount
        FROM {view}
        """
    ).fetchone()
    cbd_count, cbd_sum, cbd_avg, cbd_avg_positive = con.execute(
        f"""
        SELECT
            count(*) FILTER (WHERE coalesce({_q(cbd_fee_col)}, 0) > 0) AS cbd_count,
            sum({_q(cbd_fee_col)}) AS cbd_sum,
            avg({_q(cbd_fee_col)}) AS cbd_avg,
            avg({_q(cbd_fee_col)}) FILTER (WHERE coalesce({_q(cbd_fee_col)}, 0) > 0) AS cbd_avg_positive
        FROM {view}
        """
    ).fetchone()
    top_pickups = con.execute(
        f"""
        SELECT {_q(pickup_col)} AS pickup_location_id, count(*) AS order_count, sum({_q(amount_col)}) AS total_amount
        FROM {view}
        GROUP BY 1
        ORDER BY order_count DESC
        LIMIT 10
        """
    ).fetchall()
    return {
        "year": year,
        "total_rows": int(total_rows),
        "total_amount": float(total_amount or 0),
        "top_pickup_locations": [
            {
                "pickup_location_id": int(location_id),
                "order_count": int(order_count),
                "order_share": _safe_div(order_count, total_rows),
                "total_amount": float(amount or 0),
            }
            for location_id, order_count, amount in top_pickups
        ],
        "payment": payment,
        "airport": {
            "order_count": int(airport_count),
            "order_share": _safe_div(airport_count, total_rows),
            "amount": float(airport_amount or 0),
            "amount_share": _safe_div(airport_amount or 0, total_amount),
        },
        "cbd": {
            "positive_count": int(cbd_count),
            "positive_count_share": _safe_div(cbd_count, total_rows),
            "fee_sum": float(cbd_sum or 0),
            "fee_avg_all_orders": float(cbd_avg or 0),
            "fee_avg_positive_orders": float(cbd_avg_positive or 0),
        },
    }


def _cleaning_profile(
    con: duckdb.DuckDBPyConnection,
    view: str,
    *,
    year: str,
    amount_col: str,
    fare_col: str,
    distance_col: str,
    pickup_time_col: str,
    dropoff_time_col: str,
    high_amount_threshold: float,
) -> dict[str, Any]:
    invalid_predicate = _invalid_trip_predicate(amount_col, fare_col, distance_col, pickup_time_col, dropoff_time_col)
    row = con.execute(
        f"""
        WITH base AS (
            SELECT *,
                {invalid_predicate} AS invalid_trip,
                {_q(amount_col)} > {high_amount_threshold} AS high_amount_outlier
            FROM {view}
        )
        SELECT
            count(*) AS raw_count,
            sum({_q(amount_col)}) AS raw_revenue,
            avg({_q(amount_col)}) AS raw_avg,
            count(*) FILTER (WHERE invalid_trip) AS invalid_count,
            count(*) FILTER (WHERE NOT invalid_trip) AS cleaned_count,
            sum({_q(amount_col)}) FILTER (WHERE NOT invalid_trip) AS cleaned_revenue,
            avg({_q(amount_col)}) FILTER (WHERE NOT invalid_trip) AS cleaned_avg,
            count(*) FILTER (WHERE high_amount_outlier) AS high_outlier_count,
            avg({_q(amount_col)}) FILTER (WHERE NOT high_amount_outlier) AS avg_without_high_outliers,
            avg({_q(amount_col)}) FILTER (WHERE NOT invalid_trip AND NOT high_amount_outlier) AS cleaned_avg_without_high_outliers
        FROM base
        """
    ).fetchone()
    return {
        "year": year,
        "raw_order_count": int(row[0]),
        "raw_revenue": float(row[1] or 0),
        "raw_avg_total_amount": float(row[2] or 0),
        "invalid_union_count": int(row[3]),
        "invalid_union_rate": _safe_div(row[3], row[0]),
        "cleaned_order_count": int(row[4]),
        "cleaned_revenue": float(row[5] or 0),
        "cleaned_avg_total_amount": float(row[6] or 0),
        "raw_to_clean_count_delta": int(row[4] - row[0]),
        "raw_to_clean_revenue_delta": float((row[5] or 0) - (row[1] or 0)),
        "raw_to_clean_avg_delta": float((row[6] or 0) - (row[2] or 0)),
        "high_amount_threshold": high_amount_threshold,
        "high_amount_outlier_count": int(row[7]),
        "avg_without_high_outliers": float(row[8] or 0),
        "cleaned_avg_without_high_outliers": float(row[9] or 0),
    }


def _cleaning_yoy(left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
    cleaned_2025 = {
        "order_count": left["cleaned_order_count"],
        "total_amount_sum": left["cleaned_revenue"],
        "avg_total_amount": left["cleaned_avg_total_amount"],
    }
    cleaned_2026 = {
        "order_count": right["cleaned_order_count"],
        "total_amount_sum": right["cleaned_revenue"],
        "avg_total_amount": right["cleaned_avg_total_amount"],
    }
    return _yoy_metrics(cleaned_2025, cleaned_2026)


def _field_meanings_answer(facts: dict[str, Any]) -> dict[str, Any]:
    columns = facts["schema_compare"]["shared_columns"]
    lines = []
    for column in columns:
        meaning = FIELD_MEANINGS.get(column, "字段含义需要结合数据字典或业务上下文确认。")
        prefix = "推测：" if column not in FIELD_MEANINGS else ""
        lines.append(f"{column}: {prefix}{meaning}")
    return _answer(
        "字段含义如下；其中区域 ID 只能解释为编码，不能在没有维表时编造成真实地名。\n" + "\n".join(lines),
        required_terms=["区域 ID", "不能", "维表"],
    )


def _missing_fields_answer(facts: dict[str, Any]) -> dict[str, Any]:
    parts = []
    for year in ("2025", "2026"):
        profile = facts["profiles"][year]
        rows = [
            (column, item)
            for column, item in facts["missing"][year].items()
            if item["missing_count"] > 0
        ]
        rendered = ", ".join(
            f"{column} {_int(item['missing_count'])} 行（{_pct(item['missing_rate'])}）"
            for column, item in rows
        )
        parts.append(f"{year}：{rendered or '无缺失'}；总行数 {_int(profile['row_count'])}。")
    return _answer(
        "有缺失的字段如下。" + "".join(parts),
        required_terms=["passenger_count", "Airport_fee", "congestion_surcharge"],
    )


def _amount_anomalies_answer(facts: dict[str, Any]) -> dict[str, Any]:
    anomalies25 = facts["anomalies"]["2025"]
    anomalies26 = facts["anomalies"]["2026"]
    return _answer(
        (
            f"用正金额 IQR 规则识别极端高 total_amount：2025 阈值为 {_money(anomalies25['amount_outlier_threshold'])}，"
            f"命中 {_int(anomalies25['high_amount_outlier_count'])} 条；"
            f"2026 阈值为 {_money(anomalies26['amount_outlier_threshold'])}，命中 {_int(anomalies26['high_amount_outlier_count'])} 条。"
            f"另外负 total_amount 分别为 {_int(anomalies25['negative_total_amount_count'])} 和 {_int(anomalies26['negative_total_amount_count'])} 条。"
            "报告中应给出规则、数量、占比和样例行，而不是只说存在异常。"
        ),
        required_terms=["IQR", "total_amount", "样例行"],
    )


def _anomaly_summary_answer(facts: dict[str, Any]) -> dict[str, Any]:
    a25 = facts["anomalies"]["2025"]
    a26 = facts["anomalies"]["2026"]
    return _answer(
        (
            "异常规则：负 total_amount、负 fare_amount、trip_distance <= 0、下车时间 <= 上车时间、以及正 total_amount 的 IQR 极端高值。"
            f"2025：负总金额 {_int(a25['negative_total_amount_count'])}，负 fare {_int(a25['negative_fare_amount_count'])}，"
            f"非正里程 {_int(a25['non_positive_distance_count'])}，非正时长 {_int(a25['non_positive_duration_count'])}，"
            f"高金额异常 {_int(a25['high_amount_outlier_count'])}。"
            f"2026：负总金额 {_int(a26['negative_total_amount_count'])}，负 fare {_int(a26['negative_fare_amount_count'])}，"
            f"非正里程 {_int(a26['non_positive_distance_count'])}，非正时长 {_int(a26['non_positive_duration_count'])}，"
            f"高金额异常 {_int(a26['high_amount_outlier_count'])}。"
        ),
        required_terms=["异常规则", "负总金额", "高金额异常"],
    )


def _top_pickup_answer(business25: dict[str, Any], business26: dict[str, Any]) -> dict[str, Any]:
    top25 = business25["top_pickup_locations"][:5]
    top26 = business26["top_pickup_locations"][:5]
    return _answer(
        (
            "按 PULocationID 统计热门上车区域。"
            f"2025 Top5：{_format_location_rows(top25)}。"
            f"2026 Top5：{_format_location_rows(top26)}。"
            "注意这些是区域 ID，不是地名。"
        ),
        required_terms=["PULocationID", "区域 ID"],
    )


def _payment_share_answer(business25: dict[str, Any], business26: dict[str, Any]) -> dict[str, Any]:
    c25 = _payment_row(business25, "credit_card")
    cash25 = _payment_row(business25, "cash")
    c26 = _payment_row(business26, "credit_card")
    cash26 = _payment_row(business26, "cash")
    return _answer(
        (
            f"按订单量占比，2025 信用卡 { _pct(c25['order_share']) }，现金 { _pct(cash25['order_share']) }；"
            f"2026 信用卡 { _pct(c26['order_share']) }，现金 { _pct(cash26['order_share']) }。"
            f"按金额占比，2025 信用卡 { _pct(c25['amount_share']) }，现金 { _pct(cash25['amount_share']) }；"
            f"2026 信用卡 { _pct(c26['amount_share']) }，现金 { _pct(cash26['amount_share']) }。"
        ),
        required_terms=["信用卡", "现金", "订单量占比", "金额占比"],
    )


def _payment_amount_compare_answer(business25: dict[str, Any], business26: dict[str, Any]) -> dict[str, Any]:
    c25 = _payment_row(business25, "credit_card")
    cash25 = _payment_row(business25, "cash")
    c26 = _payment_row(business26, "credit_card")
    cash26 = _payment_row(business26, "cash")
    return _answer(
        (
            f"信用卡平均 total_amount 从 2025 的 {_money(c25['avg_total_amount'])} 到 2026 的 {_money(c26['avg_total_amount'])}；"
            f"现金从 {_money(cash25['avg_total_amount'])} 到 {_money(cash26['avg_total_amount'])}。"
            "要判断是否因果影响客单价，需要进一步控制区域、机场、里程和费率；当前只能说明分组均值变化。"
        ),
        required_terms=["分组均值", "不能说明因果"],
    )


def _clean_invalid_drop_answer(cleaning25: dict[str, Any], cleaning26: dict[str, Any]) -> dict[str, Any]:
    return _answer(
        (
            f"按模拟规则删除负金额、非正里程和非正时长后，2025 删除 {_int(cleaning25['invalid_union_count'])} 行，"
            f"订单量从 {_int(cleaning25['raw_order_count'])} 变为 {_int(cleaning25['cleaned_order_count'])}，"
            f"总收入变化 {_money(cleaning25['raw_to_clean_revenue_delta'])}，平均订单金额变化 {_money(cleaning25['raw_to_clean_avg_delta'])}。"
            f"2026 删除 {_int(cleaning26['invalid_union_count'])} 行，订单量从 {_int(cleaning26['raw_order_count'])} 变为 {_int(cleaning26['cleaned_order_count'])}，"
            f"总收入变化 {_money(cleaning26['raw_to_clean_revenue_delta'])}，平均订单金额变化 {_money(cleaning26['raw_to_clean_avg_delta'])}。"
        ),
        required_terms=["模拟规则", "订单量", "总收入变化"],
    )


def _missing_cleaning_strategy_answer(facts: dict[str, Any]) -> dict[str, Any]:
    missing = _top_missing_increases(facts["missing_compare"])
    return _answer(
        (
            "缺失处理建议分三档：保留缺失用于不依赖这些字段的总订单量/total_amount 分析；"
            "对 passenger_count、RatecodeID、Airport_fee 等缺失做单独 Unknown/缺失分类，避免直接填 0 改变含义；"
            "只有在问题明确依赖该字段时才做完整案例删除，并报告影响行数。"
            f"当前缺失上升最明显字段为 {_format_missing_increase_list(missing)}。"
        ),
        required_terms=["保留缺失", "Unknown", "完整案例删除"],
    )


def _outlier_cleaning_answer(cleaning25: dict[str, Any], cleaning26: dict[str, Any]) -> dict[str, Any]:
    return _answer(
        (
            f"去除极端高 total_amount 后，2025 平均订单金额从 {_money(cleaning25['raw_avg_total_amount'])} 变为 {_money(cleaning25['avg_without_high_outliers'])}；"
            f"2026 从 {_money(cleaning26['raw_avg_total_amount'])} 变为 {_money(cleaning26['avg_without_high_outliers'])}。"
            "均值会更不受极端高值影响，但负金额、0 里程和非正时长仍应单独处理。"
        ),
        required_terms=["极端高", "均值", "单独处理"],
    )


def _top_missing_increases(missing_compare: list[dict[str, Any]], limit: int = 5) -> list[dict[str, Any]]:
    return [row for row in missing_compare if row["missing_rate_delta"] > 0][:limit]


def _format_missing_increase_list(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return "无明显上升字段"
    return "、".join(
        f"{row['column']}（{_pct(row['missing_rate_2025'])} -> {_pct(row['missing_rate_2026'])}，+{_pct(row['missing_rate_delta'])}）"
        for row in rows
    )


def _format_location_rows(rows: list[dict[str, Any]]) -> str:
    return "、".join(
        f"{row['pickup_location_id']}({_int(row['order_count'])}单, {_pct(row['order_share'])})"
        for row in rows
    )


def _payment_row(business: dict[str, Any], label: str) -> dict[str, Any]:
    for row in business["payment"]:
        if row["label"] == label:
            return row
    return {"order_count": 0, "order_share": 0.0, "total_amount": 0.0, "amount_share": 0.0, "avg_total_amount": 0.0}


def summary_markdown(run: dict[str, Any]) -> str:
    facts = run["facts"]
    yoy = facts["yoy"]
    candidate = run.get("candidate_score")
    lines = [
        "# Taxi Dual-Year Eval Gate Summary",
        "",
        f"- Generated at: {run['generated_at']}",
        f"- Output cases: {len(run['cases'])}",
        f"- Elapsed: {run['elapsed_seconds']}s",
        f"- Git branch: {run['repo'].get('branch')}",
        f"- Git commit: {run['repo'].get('commit')}",
        f"- 2025 rows/columns: {_int(facts['profiles']['2025']['row_count'])} / {facts['profiles']['2025']['column_count']}",
        f"- 2026 rows/columns: {_int(facts['profiles']['2026']['row_count'])} / {facts['profiles']['2026']['column_count']}",
        f"- January order count YoY: {_int(yoy['order_count_delta'])} ({_pct(yoy['order_count_growth_rate'])})",
        f"- Revenue YoY: {_money(yoy['revenue_delta'])} ({_pct(yoy['revenue_growth_rate'])})",
        f"- Average total amount YoY: {_money(yoy['avg_amount_delta'])} ({_pct(yoy['avg_amount_growth_rate'])})",
        "",
        "Metric boundary: DAB / benchmark standards are not used here. These standard answers are generated after reading the taxi files and are only for offline evaluation.",
    ]
    if candidate:
        lines.extend(
            [
                "",
                "## Candidate Score",
                f"- Passed: {candidate['passed']} / {candidate['total']}",
                f"- Pass rate: {_pct(candidate['pass_rate']) if candidate['pass_rate'] is not None else 'n/a'}",
            ]
        )
    return "\n".join(lines) + "\n"


def standard_answers_markdown(run: dict[str, Any]) -> str:
    lines = [
        "# Taxi Dual-Year Standard Answers",
        "",
        "这些标准答案由脚本读取源数据后生成，只用于离线评估，不进入 VDS Agent 的分析链路。",
        "",
    ]
    for case in run["cases"]:
        lines.extend(
            [
                f"## {case['case_id']} - {case['category']}",
                "",
                f"Question: {case['question']}",
                "",
                case["standard_answer"],
                "",
            ]
        )
    return "\n".join(lines)


def repo_state() -> dict[str, Any]:
    return {
        "branch": _git(["rev-parse", "--abbrev-ref", "HEAD"]),
        "commit": _git(["rev-parse", "--short", "HEAD"]),
        "status_short": _git(["status", "--short"]),
    }


def _git(args: list[str]) -> str:
    try:
        completed = subprocess.run(
            ["git", *args],
            cwd=REPO_ROOT,
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except OSError:
        return ""
    return completed.stdout.strip()


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows = []
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid JSONL at {path}:{line_number}: {exc}") from exc
    return rows


def _load_candidate_answers(path: Path) -> dict[str, str]:
    if path.suffix.lower() == ".jsonl":
        rows = _load_jsonl(path)
        return {str(row["case_id"]): str(row.get("answer") or row.get("agent_answer") or "") for row in rows}
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict):
        if "answers" in data and isinstance(data["answers"], list):
            return {str(row["case_id"]): str(row.get("answer") or row.get("agent_answer") or "") for row in data["answers"]}
        return {str(key): str(value) for key, value in data.items()}
    if isinstance(data, list):
        return {str(row["case_id"]): str(row.get("answer") or row.get("agent_answer") or "") for row in data}
    raise ValueError(f"Unsupported candidate answer format: {path}")


def _write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(_json_ready(value), ensure_ascii=False, indent=2), encoding="utf-8")


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(_json_ready(row), ensure_ascii=False) + "\n")


def _default_output_dir(config: dict[str, Any]) -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return REPO_ROOT / config["output_root"] / f"{stamp}-{config['name']}"


def _source_sql(path: Path) -> str:
    suffix = path.suffix.lower()
    literal = _sql_literal(str(path))
    if suffix == ".parquet":
        return f"read_parquet({literal})"
    if suffix == ".csv":
        return f"read_csv_auto({literal}, union_by_name=true)"
    if suffix in {".json", ".ndjson"}:
        return f"read_json_auto({literal})"
    raise ValueError(f"Unsupported evaluation data format: {path}")


def _q(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def _sql_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _airport_predicate(airport_fee_col: str, pickup_col: str, dropoff_col: str) -> str:
    zones = ", ".join(str(item) for item in AIRPORT_ZONE_IDS)
    return (
        f"coalesce({_q(airport_fee_col)}, 0) > 0 "
        f"OR RatecodeID IN (2, 3) "
        f"OR {_q(pickup_col)} IN ({zones}) "
        f"OR {_q(dropoff_col)} IN ({zones})"
    )


def _invalid_trip_predicate(
    amount_col: str,
    fare_col: str,
    distance_col: str,
    pickup_time_col: str,
    dropoff_time_col: str,
) -> str:
    return (
        f"coalesce({_q(amount_col)} < 0, false) "
        f"OR coalesce({_q(fare_col)} < 0, false) "
        f"OR coalesce({_q(distance_col)} <= 0, false) "
        f"OR coalesce(date_diff('second', {_q(pickup_time_col)}, {_q(dropoff_time_col)}) <= 0, false)"
    )


def _answer(
    text: str,
    *,
    expected_facts: dict[str, Any] | None = None,
    required_terms: list[str] | None = None,
    expected_numbers: list[dict[str, Any]] | None = None,
    technical_checks: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "text": text,
        "expected_facts": expected_facts or {},
        "required_terms": required_terms or [],
        "expected_numbers": expected_numbers or [],
        "technical_checks": technical_checks or [],
    }


def _num(label: str, value: Any, tolerance_abs: float | None = None, tolerance_rel: float = 0.01) -> dict[str, Any]:
    return {
        "label": label,
        "value": float(value),
        "tolerance_abs": 0.01 if tolerance_abs is None else tolerance_abs,
        "tolerance_rel": tolerance_rel,
    }


def _candidate_contains_number(answer: str, check: dict[str, Any], default_tolerance: float) -> dict[str, Any]:
    expected = float(check["value"])
    tolerance_abs = float(check.get("tolerance_abs", 0.01))
    tolerance_rel = float(check.get("tolerance_rel", default_tolerance))
    tolerance = max(tolerance_abs, abs(expected) * tolerance_rel)
    numbers = _extract_numbers(answer)
    passed = any(abs(number - expected) <= tolerance for number in numbers)
    if not passed and abs(expected) <= 1:
        expected_percent = expected * 100
        percent_tolerance = max(0.01, abs(expected_percent) * tolerance_rel)
        passed = any(abs(number - expected_percent) <= percent_tolerance for number in numbers)
    return {
        "label": check["label"],
        "expected": expected,
        "tolerance": tolerance,
        "passed": passed,
    }


def _extract_numbers(text: str) -> list[float]:
    values = []
    for match in re.finditer(r"[-+]?\d[\d,]*(?:\.\d+)?", text):
        raw = match.group(0).replace(",", "")
        try:
            values.append(float(raw))
        except ValueError:
            continue
    return values


def _safe_div(numerator: Any, denominator: Any) -> float:
    if denominator in (0, None):
        return 0.0
    if numerator is None:
        return 0.0
    return float(numerator) / float(denominator)


def _int(value: Any) -> str:
    return f"{int(round(float(value))):,}"


def _money(value: Any) -> str:
    return f"{float(value):,.2f}"


def _pct(value: Any) -> str:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return "n/a"
    return f"{float(value) * 100:.2f}%"


def _json_ready(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_ready(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_ready(item) for item in value]
    if isinstance(value, tuple):
        return [_json_ready(item) for item in value]
    if isinstance(value, Path):
        return str(value)
    if hasattr(value, "isoformat"):
        try:
            return value.isoformat()
        except (TypeError, ValueError):
            pass
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            return None
        return value
    if hasattr(value, "item"):
        try:
            return _json_ready(value.item())
        except (TypeError, ValueError):
            pass
    return value


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # noqa: BLE001 - command-line tool should fail clearly.
        print(f"ERROR: {exc}", file=sys.stderr)
        raise
