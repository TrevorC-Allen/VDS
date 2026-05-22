# DATASET LIFECYCLE

## 当前阶段

当前已实现最小本地临时存储：上传文件会生成 dataset_id，写入 source_file 和 profile.json，并在当前进程内保存 DataFrame tables；进程重启恢复、自动清理和生产持久化仍未实现。

## dataset_id

dataset_id 当前由后端上传接口生成，格式为 `ds_` 加唯一标识；后续可调整为 `ds_YYYYMMDD_sequence` 或等价的可追踪唯一 ID。

## 建议存储路径

1. 原始文件存储位置：storage/datasets/{dataset_id}/source_file
2. profile 存储位置：storage/datasets/{dataset_id}/profile.json
3. 表格拆分存储位置：storage/datasets/{dataset_id}/tables/
4. run trace 存储位置：storage/runs/{run_id}/trace.json

## 默认策略草案

1. 默认临时数据集保留时间：24 小时。
2. 默认最大文件大小：50 MB。
3. 当前支持 csv / xlsx。
4. 多 sheet 文件应拆成多个 TableProfile。
5. 不确定表头时必须返回 warning，不允许静默猜测。

## TODO

- 明确生产级临时文件清理策略。
- 明确多 sheet 文件的表名规则和冲突处理。
- 明确进程重启后的 profile / tables 重新加载策略。
