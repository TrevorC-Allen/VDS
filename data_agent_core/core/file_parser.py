"""File parser for CSV, Excel, and DABstep context files."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd


def read_csv(path: str | Path) -> pd.DataFrame:
    """Read a CSV file with conservative defaults."""

    return pd.read_csv(path)


def read_excel(path: str | Path) -> dict[str, pd.DataFrame]:
    """Read every sheet from an Excel workbook."""

    return pd.read_excel(path, sheet_name=None)


def read_json_records(path: str | Path) -> list[dict[str, Any]]:
    """Read a JSON file that contains a list of records."""

    data = json.loads(Path(path).read_text())
    if not isinstance(data, list):
        raise ValueError(f"Expected JSON list records in {path}")
    return data


def load_dabstep_context(context_dir: str | Path) -> dict[str, Any]:
    """Load the DABstep context without exposing benchmark answers."""

    root = Path(context_dir)
    return {
        "payments": read_csv(root / "payments.csv"),
        "merchant_category_codes": read_csv(root / "merchant_category_codes.csv"),
        "acquirer_countries": read_csv(root / "acquirer_countries.csv"),
        "fees": read_json_records(root / "fees.json"),
        "merchant_data": read_json_records(root / "merchant_data.json"),
        "context_dir": root,
    }
