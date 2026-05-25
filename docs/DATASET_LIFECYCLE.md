# DATASET LIFECYCLE

## 当前阶段

当前已实现最小本地临时存储：上传文件会生成 dataset_id，写入 source_file 和 profile.json，并在当前进程内保存 DataFrame tables；进程重启恢复、自动清理和生产持久化仍未实现。

2026-05-25 更新：规则文件不再进入 dataset source_file / tables。显式 `file_role=rule` 的文件会存储为 rule file record，包含 `file_id`、`file_role=rule`、`rule_scope`、原始文本和解析摘要；普通旧上传不传 `file_role` 时仍按 `dataset` 处理以保持兼容。

## dataset_id

dataset_id 当前由后端上传接口生成，格式为 `ds_` 加唯一标识；后续可调整为 `ds_YYYYMMDD_sequence` 或等价的可追踪唯一 ID。

## 建议存储路径

1. 原始文件存储位置：storage/datasets/{dataset_id}/source_file
2. profile 存储位置：storage/datasets/{dataset_id}/profile.json
3. 表格拆分存储位置：storage/datasets/{dataset_id}/tables/
4. run trace 存储位置：storage/runs/{run_id}/trace.json
5. 规则文件存储位置：storage/rules/{file_id}/
6. Benchmark report 存储位置：storage/benchmarks/{run_id}/report.json

## 默认策略草案

1. 默认临时数据集保留时间：24 小时。
2. 默认最大文件大小：50 MB。
3. 当前支持 csv / xlsx。
4. 多 sheet 文件应拆成多个 TableProfile。
5. 不确定表头时必须返回 warning，不允许静默猜测。
6. `file_role=rule` 必须带 `rule_scope`，并且不能被字段画像、DataFrame 分析或普通数据概览读取。
7. 旧文件没有 file_role 时默认按 dataset 处理。

## TODO

- 明确生产级临时文件清理策略。
- 明确多 sheet 文件的表名规则和冲突处理。
- 明确进程重启后的 profile / tables 重新加载策略。
