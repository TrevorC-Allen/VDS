"""File parser for CSV, Excel, Parquet, and DABstep context files."""

from __future__ import annotations

import csv
import io
import json
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from data_agent_core.contracts.dataset_contracts import DatasetProfile
from data_agent_core.core.data_quality import build_data_quality_report, report_to_dict
from data_agent_core.core.schema_profiler import profile_table, profile_tables


@dataclass
class ParsedDataset:
    """Parsed file tables plus stable profile metadata."""

    tables: dict[str, pd.DataFrame]
    profile: DatasetProfile
    table_metadata: dict[str, dict[str, Any]] | None = None


@dataclass
class CsvReadResult:
    """CSV frame plus parse diagnostics."""

    dataframe: pd.DataFrame
    diagnostics: dict[str, Any]


@dataclass
class ExcelTableCandidate:
    """One table-like or source-like block found inside an Excel sheet."""

    table_name: str
    dataframe: pd.DataFrame
    metadata: dict[str, Any]
    include_in_analysis: bool = True


def read_csv(path: str | Path) -> pd.DataFrame:
    """Read a CSV file with conservative defaults."""

    return read_csv_with_diagnostics(path).dataframe


def read_csv_with_diagnostics(path: str | Path) -> CsvReadResult:
    """Read a CSV file with encoding, delimiter, and bad-line diagnostics."""

    source = Path(path)
    raw = source.read_bytes()
    last_error: Exception | None = None
    for encoding in ("utf-8-sig", "utf-8", "gb18030", "gbk"):
        try:
            text = raw.decode(encoding)
            delimiter = _detect_csv_delimiter(text)
            diagnostics = _csv_diagnostics(text, delimiter=delimiter, encoding=encoding)
            read_kwargs: dict[str, Any] = {
                "sep": delimiter,
                "on_bad_lines": "skip" if diagnostics.get("bad_line_count") else "error",
            }
            if diagnostics.get("bad_line_count"):
                read_kwargs["engine"] = "python"
            else:
                read_kwargs["low_memory"] = False
            dataframe = pd.read_csv(io.StringIO(text), **read_kwargs)
            diagnostics["row_count"] = int(len(dataframe))
            diagnostics["column_count"] = int(len(dataframe.columns))
            return CsvReadResult(dataframe=dataframe, diagnostics=diagnostics)
        except UnicodeDecodeError as exc:
            last_error = exc
    if last_error is not None:
        raise last_error
    dataframe = pd.read_csv(source, encoding="utf-8-sig", low_memory=False)
    return CsvReadResult(
        dataframe=dataframe,
        diagnostics={"encoding": "utf-8-sig", "delimiter": ",", "bad_line_count": 0},
    )


def read_excel(path: str | Path) -> dict[str, pd.DataFrame]:
    """Read every sheet from an Excel workbook."""

    return {candidate.table_name: candidate.dataframe for candidate in read_excel_candidates(path) if candidate.include_in_analysis}


def read_excel_candidates(path: str | Path) -> list[ExcelTableCandidate]:
    """Read Excel sheets into table candidates with role and range diagnostics."""

    raw_sheets = pd.read_excel(path, sheet_name=None, header=None, dtype=object)
    candidates: list[ExcelTableCandidate] = []
    for sheet_name, raw_df in raw_sheets.items():
        blocks = _split_excel_sheet_blocks(raw_df)
        if not blocks:
            empty = pd.DataFrame()
            candidates.append(
                ExcelTableCandidate(
                    table_name=str(sheet_name),
                    dataframe=empty,
                    include_in_analysis=False,
                    metadata={
                        "source_kind": "excel_sheet",
                        "sheet": str(sheet_name),
                        "table_name": str(sheet_name),
                        "table_role": "empty_sheet",
                        "role_confidence": 1.0,
                        "range_ref": "",
                        "header_rows": [],
                        "parse_diagnostics": {"reason": "empty_sheet"},
                    },
                )
            )
            continue
        for block_index, block in enumerate(blocks, start=1):
            candidate = _excel_block_candidate(sheet_name=str(sheet_name), block=block, block_index=block_index, block_count=len(blocks))
            candidates.append(candidate)
    return candidates


def read_parquet(path: str | Path) -> pd.DataFrame:
    """Read Parquet with a DuckDB fallback for runtimes without pyarrow."""

    try:
        return pd.read_parquet(path)
    except (ImportError, ValueError) as exc:
        message = str(exc).lower()
        if "pyarrow" not in message and "fastparquet" not in message and "parquet" not in message:
            raise
        try:
            import duckdb
        except ImportError as duckdb_exc:  # pragma: no cover - environment dependent.
            raise exc from duckdb_exc
        with duckdb.connect(database=":memory:") as con:
            return con.execute("SELECT * FROM read_parquet(?)", [str(Path(path))]).fetchdf()


def _detect_csv_delimiter(text: str) -> str:
    sample = text[:8192]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",\t;|")
        return dialect.delimiter
    except csv.Error:
        counts = {delimiter: sample.count(delimiter) for delimiter in (",", "\t", ";", "|")}
        return max(counts.items(), key=lambda item: item[1])[0] if any(counts.values()) else ","


def _csv_diagnostics(text: str, *, delimiter: str, encoding: str) -> dict[str, Any]:
    reader = csv.reader(io.StringIO(text), delimiter=delimiter)
    expected_width = 0
    bad_lines: list[int] = []
    row_count = 0
    for row_number, row in enumerate(reader, start=1):
        if not row or not any(str(cell).strip() for cell in row):
            continue
        row_count += 1
        if expected_width == 0:
            expected_width = len(row)
            continue
        if len(row) != expected_width:
            bad_lines.append(row_number)
    return {
        "encoding": encoding,
        "delimiter": delimiter,
        "expected_column_count": expected_width,
        "physical_row_count": row_count,
        "bad_line_count": len(bad_lines),
        "bad_line_numbers": bad_lines[:20],
    }


def _split_excel_sheet_blocks(raw_df: pd.DataFrame) -> list[dict[str, Any]]:
    if raw_df.empty:
        return []
    row_has_data = raw_df.apply(lambda row: any(not _empty_cell(value) for value in row), axis=1).tolist()
    row_ranges: list[tuple[int, int]] = []
    start: int | None = None
    for index, has_data in enumerate(row_has_data):
        if has_data and start is None:
            start = index
        elif not has_data and start is not None:
            row_ranges.append((start, index - 1))
            start = None
    if start is not None:
        row_ranges.append((start, len(row_has_data) - 1))

    blocks: list[dict[str, Any]] = []
    for start_row, end_row in row_ranges:
        row_block = raw_df.iloc[start_row : end_row + 1, :]
        col_has_data = row_block.apply(lambda column: any(not _empty_cell(value) for value in column), axis=0).tolist()
        col_start: int | None = None
        for col_index, has_data in enumerate(col_has_data):
            if has_data and col_start is None:
                col_start = col_index
            elif not has_data and col_start is not None:
                blocks.append(_excel_block(raw_df, start_row, end_row, col_start, col_index - 1))
                col_start = None
        if col_start is not None:
            blocks.append(_excel_block(raw_df, start_row, end_row, col_start, len(col_has_data) - 1))
    return [block for block in blocks if not block["dataframe"].empty]


def _excel_block(raw_df: pd.DataFrame, start_row: int, end_row: int, start_col: int, end_col: int) -> dict[str, Any]:
    return {
        "dataframe": raw_df.iloc[start_row : end_row + 1, start_col : end_col + 1].reset_index(drop=True),
        "start_row": start_row,
        "end_row": end_row,
        "start_col": start_col,
        "end_col": end_col,
    }


def _excel_block_candidate(
    *,
    sheet_name: str,
    block: dict[str, Any],
    block_index: int,
    block_count: int,
) -> ExcelTableCandidate:
    raw = block["dataframe"]
    header_index = _detect_excel_header_row(raw)
    header_indices = _excel_header_indices(raw, header_index)
    role, confidence = _excel_table_role(raw, header_indices)
    table_name = sheet_name if block_count == 1 else f"{sheet_name}__table_{block_index}"
    include_in_analysis = role == "data_table"
    dataframe = _excel_dataframe_from_block(raw, header_indices) if include_in_analysis else _excel_source_frame(raw)
    range_ref = _range_ref(
        int(block["start_row"]),
        int(block["start_col"]),
        int(block["end_row"]) + 1,
        int(block["end_col"]) + 1,
    )
    diagnostics = {
        "detected_header_row": None if header_index < 0 else int(block["start_row"]) + header_index + 1,
        "block_index": block_index,
        "block_count": block_count,
        "raw_row_count": int(raw.shape[0]),
        "raw_column_count": int(raw.shape[1]),
        "included_in_analysis": include_in_analysis,
    }
    metadata = {
        "source_kind": "excel_sheet",
        "sheet": sheet_name,
        "table_name": table_name,
        "table_role": role,
        "role_confidence": confidence,
        "range_ref": range_ref,
        "header_rows": [int(block["start_row"]) + index + 1 for index in header_indices],
        "parse_diagnostics": diagnostics,
    }
    return ExcelTableCandidate(
        table_name=table_name,
        dataframe=dataframe,
        metadata=metadata,
        include_in_analysis=include_in_analysis,
    )


def _detect_excel_header_row(raw: pd.DataFrame) -> int:
    best: tuple[float, int] | None = None
    max_scan = min(len(raw), 12)
    for index in range(max_scan):
        values = [_cell_text(value) for value in raw.iloc[index].tolist()]
        filled = [value for value in values if value]
        if len(filled) < 2:
            continue
        unique_count = len(set(filled))
        numeric_count = sum(_numeric_text(value) for value in filled)
        next_filled = 0
        if index + 1 < len(raw):
            next_filled = sum(1 for value in raw.iloc[index + 1].tolist() if not _empty_cell(value))
        score = len(filled) * 2 + unique_count + min(next_filled, len(filled)) - numeric_count * 2
        if best is None or score > best[0]:
            best = (score, index)
    return -1 if best is None else best[1]


def _excel_header_indices(raw: pd.DataFrame, header_index: int) -> list[int]:
    if header_index < 0:
        return []
    indices = [header_index]
    previous_index = header_index - 1
    if previous_index >= 0:
        previous_values = [_cell_text(value) for value in raw.iloc[previous_index].tolist()]
        current_values = [_cell_text(value) for value in raw.iloc[header_index].tolist()]
        previous_count = sum(1 for value in previous_values if value)
        current_count = sum(1 for value in current_values if value)
        previous_text = " ".join(previous_values)
        looks_like_title = previous_count == 1 and current_count >= 3 and len(previous_text) > 8
        if previous_count >= 2 and current_count >= previous_count and not looks_like_title:
            indices.insert(0, previous_index)
    return indices


def _excel_table_role(raw: pd.DataFrame, header_indices: list[int]) -> tuple[str, float]:
    text = " ".join(_cell_text(value) for value in raw.to_numpy().ravel() if _cell_text(value)).lower()
    header_text = ""
    if header_indices:
        header_text = " ".join(_cell_text(value) for index in header_indices for value in raw.iloc[index].tolist()).lower()
    field_tokens = ("字段", "字段名", "列名", "含义", "说明", "dictionary", "definition", "field", "column")
    rule_tokens = ("规则", "口径", "计算口径", "公式", "manual", "rule", "guideline")
    row_count, column_count = raw.shape
    has_data_shape = bool(header_indices) and column_count >= 2 and row_count - max(header_indices) - 1 >= 1
    numeric_cells = sum(_numeric_text(_cell_text(value)) for value in raw.to_numpy().ravel())
    if any(token in header_text for token in field_tokens) and any(token in text for token in ("含义", "说明", "definition", "类型", "type")):
        return "field_dictionary", 0.92
    if any(token in text for token in rule_tokens) and numeric_cells <= max(1, row_count):
        return "rule_or_notes", 0.88
    if has_data_shape:
        return "data_table", 0.86 if numeric_cells else 0.72
    if any(token in text for token in field_tokens):
        return "field_dictionary", 0.78
    if any(token in text for token in rule_tokens):
        return "rule_or_notes", 0.78
    return "notes_or_metadata", 0.55


def _excel_dataframe_from_block(raw: pd.DataFrame, header_indices: list[int]) -> pd.DataFrame:
    if not header_indices:
        return _excel_source_frame(raw)
    header_frame = raw.iloc[header_indices].copy()
    if len(header_indices) > 1:
        header_frame = header_frame.ffill(axis=1)
    columns = _unique_columns([
        _join_header_parts([_cell_text(header_frame.iloc[row_index, col_index]) for row_index in range(len(header_frame))])
        for col_index in range(header_frame.shape[1])
    ])
    data = raw.iloc[max(header_indices) + 1 :].copy()
    data.columns = columns
    data = data.dropna(axis=0, how="all").dropna(axis=1, how="all")
    data.columns = [str(column) for column in data.columns]
    return _coerce_numeric_like_columns(data).reset_index(drop=True)


def _excel_source_frame(raw: pd.DataFrame) -> pd.DataFrame:
    frame = raw.dropna(axis=0, how="all").dropna(axis=1, how="all").copy()
    frame.columns = [f"column_{index + 1}" for index in range(frame.shape[1])]
    return frame.reset_index(drop=True)


def _join_header_parts(parts: list[str]) -> str:
    clean: list[str] = []
    for part in parts:
        if not part or part in clean:
            continue
        clean.append(part)
    return "_".join(clean).strip("_") or "Unnamed"


def _unique_columns(columns: list[str]) -> list[str]:
    seen: dict[str, int] = {}
    unique: list[str] = []
    for index, column in enumerate(columns, start=1):
        name = str(column or f"Unnamed_{index}").strip() or f"Unnamed_{index}"
        count = seen.get(name, 0)
        seen[name] = count + 1
        unique.append(name if count == 0 else f"{name}_{count + 1}")
    return unique


def _range_ref(start_row: int, start_col: int, end_row: int, end_col: int) -> str:
    if end_row <= start_row or end_col <= start_col:
        return ""
    return f"{_excel_column_name(start_col + 1)}{start_row + 1}:{_excel_column_name(end_col)}{end_row}"


def _excel_column_name(index: int) -> str:
    name = ""
    while index > 0:
        index, remainder = divmod(index - 1, 26)
        name = chr(65 + remainder) + name
    return name or "A"


def _empty_cell(value: Any) -> bool:
    if value is None:
        return True
    try:
        if pd.isna(value):
            return True
    except (TypeError, ValueError):
        pass
    return str(value).strip() == ""


def _cell_text(value: Any) -> str:
    if _empty_cell(value):
        return ""
    return re.sub(r"\s+", " ", str(value)).strip()


def _numeric_text(value: str) -> bool:
    if not value:
        return False
    try:
        float(str(value).replace(",", ""))
    except ValueError:
        return False
    return True


def _coerce_numeric_like_columns(dataframe: pd.DataFrame) -> pd.DataFrame:
    frame = dataframe.copy()
    for column in frame.columns:
        if _identifier_like_column(str(column)):
            continue
        series = frame[column]
        if pd.api.types.is_numeric_dtype(series):
            continue
        cleaned = series.map(_numeric_cell_text)
        non_empty = cleaned[cleaned != ""]
        if non_empty.empty:
            continue
        converted = pd.to_numeric(cleaned, errors="coerce")
        numeric_ratio = float(converted.notna().sum()) / float(len(non_empty))
        if numeric_ratio >= 0.85:
            frame[column] = converted
    return frame


def _numeric_cell_text(value: Any) -> str:
    if _empty_cell(value):
        return ""
    text = str(value).strip()
    if not text:
        return ""
    return text.replace(",", "")


def _identifier_like_column(column_name: str) -> bool:
    normalized = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "", column_name.lower())
    return any(token in normalized for token in ("id", "code", "编号", "代码", "手机号", "电话", "邮编"))


def parse_dataset_file(
    path: str | Path,
    dataset_id: str | None = None,
    *,
    source_name: str | None = None,
) -> ParsedDataset:
    """Parse one uploaded CSV / Excel file and return tables plus DatasetProfile."""

    source_path = Path(path)
    display_name = source_name or source_path.name
    display_path = Path(display_name)
    dataset_id = dataset_id or _new_dataset_id()
    warnings: list[str] = []
    parse_diagnostics: dict[str, Any] = {"sources": []}
    profile_only_tables = []
    suffix = source_path.suffix.lower()
    if suffix == ".csv":
        csv_result = read_csv_with_diagnostics(source_path)
        table_name = display_path.stem or source_path.stem or "table"
        tables = {table_name: csv_result.dataframe}
        parse_diagnostics["sources"].append({"source_file": display_name, "kind": "csv", **csv_result.diagnostics})
        if csv_result.diagnostics.get("bad_line_count"):
            warnings.append(
                f"{display_name} has {csv_result.diagnostics['bad_line_count']} CSV line(s) with unexpected field counts; they were skipped and recorded in parse diagnostics."
            )
    elif suffix in {".xlsx", ".xls"}:
        candidates = read_excel_candidates(source_path)
        tables = {candidate.table_name: candidate.dataframe for candidate in candidates if candidate.include_in_analysis}
        profile_only_tables = [
            profile_table(
                candidate.table_name,
                candidate.dataframe,
                source_file=display_name,
                sheet=candidate.metadata.get("sheet"),
                source_kind=candidate.metadata.get("source_kind"),
                range_ref=candidate.metadata.get("range_ref"),
                header_rows=candidate.metadata.get("header_rows"),
                table_role=candidate.metadata.get("table_role"),
                role_confidence=candidate.metadata.get("role_confidence"),
                parse_diagnostics=candidate.metadata.get("parse_diagnostics"),
            )
            for candidate in candidates
            if not candidate.include_in_analysis
        ]
        parse_diagnostics["sources"].extend(
            {
                "source_file": display_name,
                "kind": "excel_sheet",
                "sheet": candidate.metadata.get("sheet"),
                "table_name": candidate.table_name,
                "table_role": candidate.metadata.get("table_role"),
                "range_ref": candidate.metadata.get("range_ref"),
                "header_rows": candidate.metadata.get("header_rows"),
                "included_in_analysis": candidate.include_in_analysis,
                **dict(candidate.metadata.get("parse_diagnostics") or {}),
            }
            for candidate in candidates
        )
        if len(tables) > 1:
            warnings.append("Multiple Excel sheet/table candidates were parsed as separate tables.")
        skipped = [candidate.table_name for candidate in candidates if not candidate.include_in_analysis]
        if skipped:
            warnings.append("Some Excel sheets or blocks were treated as rules/notes/metadata, not analysis tables: " + ", ".join(skipped) + ".")
    elif suffix == ".json":
        records = read_json_records(source_path)
        tables = {display_path.stem or source_path.stem or "table": pd.DataFrame(records)}
    elif suffix == ".parquet":
        tables = {display_path.stem or source_path.stem or "table": read_parquet(source_path)}
    elif suffix in {".arrow", ".feather"}:
        tables = {display_path.stem or source_path.stem or "table": pd.read_feather(source_path)}
    elif suffix in {".pdf"}:
        raise ValueError("PDF table extraction is not enabled for dataset uploads yet; upload text rules as file_role=rule or convert tabular pages to CSV/XLSX.")
    elif suffix in {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp"}:
        raise ValueError("Image table extraction needs OCR and is not enabled for dataset uploads; convert the table to CSV/XLSX or provide a text source.")
    else:
        raise ValueError(f"Unsupported file type: {source_path.suffix}")

    table_metadata: dict[str, dict[str, Any]] = {}
    for table_name, df in tables.items():
        metadata = {
            "source_file": display_name,
            "sheet": table_name if suffix in {".xlsx", ".xls"} else None,
            "table_name": table_name,
            "source_kind": "excel_sheet" if suffix in {".xlsx", ".xls"} else "csv" if suffix == ".csv" else suffix.removeprefix(".") or "table",
            "table_role": "data_table",
            "role_confidence": 0.8,
            "parse_diagnostics": {},
        }
        if suffix == ".csv" and parse_diagnostics["sources"]:
            metadata["range_ref"] = _range_ref(0, 0, len(df), len(df.columns))
            metadata["header_rows"] = [1] if len(df.columns) else []
            metadata["parse_diagnostics"] = dict(parse_diagnostics["sources"][0])
        elif suffix in {".xlsx", ".xls"}:
            candidate_meta = next(
                (
                    candidate.metadata
                    for candidate in locals().get("candidates", [])
                    if candidate.table_name == table_name
                ),
                {},
            )
            metadata.update(candidate_meta)
        df.attrs.update({key: value for key, value in metadata.items() if value is not None})
        table_metadata[table_name] = metadata

    for table_name, df in tables.items():
        if df.empty:
            warnings.append(f"Table {table_name} is empty.")
        unnamed = [str(column) for column in df.columns if str(column).startswith("Unnamed")]
        if unnamed:
            warnings.append(f"Table {table_name} has uncertain header columns: {', '.join(unnamed)}.")

    table_profiles = list(profile_tables(tables, table_metadata=table_metadata).values()) + profile_only_tables
    quality_report = build_data_quality_report(tables, generated_from="upload_profile")
    profile = DatasetProfile(
        dataset_id=dataset_id,
        file_name=display_name,
        status="ready" if not warnings else "ready_with_warnings",
        tables=table_profiles,
        created_at=datetime.now(timezone.utc).isoformat(),
        warnings=warnings,
        errors=[],
        quality_report=report_to_dict(quality_report),
        parse_diagnostics=parse_diagnostics,
    )
    return ParsedDataset(tables=tables, profile=profile, table_metadata=table_metadata)


def parse_dataset_files(
    paths: list[str | Path],
    dataset_id: str | None = None,
    *,
    source_names: list[str | None] | None = None,
) -> ParsedDataset:
    """Parse multiple uploaded CSV / Excel files into one auditable dataset."""

    if not paths:
        raise ValueError("At least one file is required for a multi-file dataset.")
    if source_names is not None and len(source_names) != len(paths):
        raise ValueError("source_names must have the same length as paths.")

    dataset_id = dataset_id or _new_dataset_id()
    combined_tables: dict[str, pd.DataFrame] = {}
    combined_metadata: dict[str, dict[str, Any]] = {}
    warnings: list[str] = []
    parse_diagnostics: dict[str, Any] = {"sources": []}
    profile_only_tables = []
    display_source_names: list[str] = []
    for index, path in enumerate(paths):
        source_path = Path(path)
        display_name = None if source_names is None else source_names[index]
        parsed = parse_dataset_file(source_path, dataset_id=dataset_id, source_name=display_name)
        display_source_names.append(display_name or source_path.name)
        warnings.extend(parsed.profile.warnings)
        parse_diagnostics["sources"].extend((parsed.profile.parse_diagnostics or {}).get("sources") or [])
        parsed_profile_tables = {profile.table_name: profile for profile in parsed.profile.tables}
        for original_name, df in parsed.tables.items():
            metadata = dict((parsed.table_metadata or {}).get(original_name) or {})
            table_source_path = Path(display_name or source_path.name)
            table_name = _unique_table_name(combined_tables, _table_name_for_source(table_source_path, original_name, len(parsed.tables)))
            metadata["table_name"] = table_name
            df.attrs.update({key: value for key, value in metadata.items() if value is not None})
            combined_tables[table_name] = df
            combined_metadata[table_name] = metadata
        for table_profile in parsed.profile.tables:
            if table_profile.table_name not in parsed.tables:
                table_profile.table_name = _unique_table_name(combined_tables, _table_name_for_source(Path(display_name or source_path.name), table_profile.table_name, len(parsed.profile.tables)))
                profile_only_tables.append(table_profile)
    if len(combined_tables) > 1:
        warnings.append("Multiple source files or sheets were parsed as separate tables.")

    table_profiles = list(profile_tables(combined_tables, table_metadata=combined_metadata).values()) + profile_only_tables
    quality_report = build_data_quality_report(combined_tables, generated_from="upload_profile")
    profile = DatasetProfile(
        dataset_id=dataset_id,
        file_name=", ".join(display_source_names),
        status="ready" if not warnings else "ready_with_warnings",
        tables=table_profiles,
        created_at=datetime.now(timezone.utc).isoformat(),
        warnings=warnings,
        errors=[],
        quality_report=report_to_dict(quality_report),
        parse_diagnostics=parse_diagnostics,
    )
    return ParsedDataset(tables=combined_tables, profile=profile, table_metadata=combined_metadata)


def read_json_records(path: str | Path) -> list[dict[str, Any]]:
    """Read a JSON file that contains a list of records."""

    data = json.loads(Path(path).read_text())
    if not isinstance(data, list):
        raise ValueError(f"Expected JSON list records in {path}")
    return data


def load_dabstep_context(context_dir: str | Path) -> dict[str, Any]:
    """Load the DABstep context without exposing benchmark answers."""

    root = Path(context_dir)
    payments = read_csv(root / "payments.csv")
    merchant_category_codes = read_csv(root / "merchant_category_codes.csv")
    acquirer_countries = read_csv(root / "acquirer_countries.csv")
    tables = {
        "payments": payments,
        "merchant_category_codes": merchant_category_codes,
        "acquirer_countries": acquirer_countries,
    }
    for table_name, df in tables.items():
        source_file = f"{table_name}.csv"
        metadata = {"source_file": source_file, "sheet": None, "table_name": table_name}
        df.attrs.update(metadata)
    return {
        "payments": payments,
        "merchant_category_codes": merchant_category_codes,
        "acquirer_countries": acquirer_countries,
        "fees": read_json_records(root / "fees.json"),
        "merchant_data": read_json_records(root / "merchant_data.json"),
        "context_dir": root,
        "tables": tables,
        "primary_table": "payments",
    }


def _new_dataset_id() -> str:
    return "ds_" + datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_") + uuid.uuid4().hex[:8]


def _table_name_for_source(path: Path, table_name: str, table_count: int) -> str:
    if path.suffix.lower() == ".csv" or table_count == 1:
        return path.stem or table_name
    return f"{path.stem}__{table_name}"


def _unique_table_name(existing: dict[str, Any], preferred: str) -> str:
    candidate = preferred or "table"
    if candidate not in existing:
        return candidate
    index = 2
    while f"{candidate}_{index}" in existing:
        index += 1
    return f"{candidate}_{index}"
