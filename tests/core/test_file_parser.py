"""Tests for uploaded file parsing fallbacks."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

try:
    import duckdb
except ImportError:  # pragma: no cover - environment dependent.
    duckdb = None

from data_agent_core.core.file_parser import parse_dataset_file


class FileParserTest(unittest.TestCase):
    @unittest.skipIf(duckdb is None, "duckdb is required to create parquet fixtures")
    def test_parquet_upload_uses_duckdb_when_pandas_engine_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            parquet_path = Path(temp_dir) / "taxi_sample.parquet"
            with duckdb.connect(database=":memory:") as con:
                con.execute(
                    f"""
                    COPY (
                        SELECT 1 AS VendorID, 10.5 AS total_amount
                        UNION ALL
                        SELECT 2 AS VendorID, 20.0 AS total_amount
                    ) TO '{parquet_path.as_posix()}' (FORMAT PARQUET)
                    """
                )

            with patch("pandas.read_parquet", side_effect=ImportError("Missing optional dependency 'pyarrow'.")):
                parsed = parse_dataset_file(parquet_path, dataset_id="ds_parquet")

        self.assertEqual(["taxi_sample"], list(parsed.tables))
        table = parsed.tables["taxi_sample"]
        self.assertEqual((2, 2), table.shape)
        self.assertEqual(30.5, float(table["total_amount"].sum()))
        self.assertEqual("ready", parsed.profile.status)


if __name__ == "__main__":
    unittest.main()
