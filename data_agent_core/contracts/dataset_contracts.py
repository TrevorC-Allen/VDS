"""Dataset contract drafts for file, table, and column profiles.

TODO:
- Define DatasetProfile, TableProfile, and ColumnProfile as stable contracts.
- Keep these contracts independent from backend schemas and framework adapters.
- Include dataset_id, file metadata, table metadata, column types, missing rates,
  sample values, warnings, and errors.

Draft structures:
- DatasetProfile: dataset_id, file_name, status, tables, created_at, warnings, errors
- TableProfile: table_name, row_count, column_count, columns
- ColumnProfile: name, inferred_type, missing_rate, unique_count, sample_values,
  semantic_hints
"""
