# DATASET LIFECYCLE

## 当前阶段

当前只定义数据集生命周期和存储位置草案，不实现真实存储逻辑。

## dataset_id

dataset_id 未来由后端上传接口生成，建议格式为 `ds_YYYYMMDD_sequence` 或等价的可追踪唯一 ID。

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

- Phase 1 明确 dataset_id 生成器。
- Phase 1 明确临时文件清理策略。
- Phase 1 明确多 sheet 文件的表名规则。
