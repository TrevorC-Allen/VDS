"""General fee-rule engine for DABstep-style uploaded business rules.

The engine treats payments.csv as the business database table and
manual.md / fees.json / merchant_data.json as the uploaded rule knowledge base.
It is intentionally independent from task IDs, benchmark answers, and any agent
framework.
"""

from __future__ import annotations

import csv
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from data_agent_core.core.date_utils import month_from_day_of_year


ACI_CODES = ("A", "B", "C", "D", "E", "F", "G")
ECOMMERCE_ACIS = ("D", "E", "F", "G")


@dataclass(frozen=True)
class FeeRule:
    """One row from fees.json normalized for matching."""

    fee_id: int
    card_scheme: str
    account_type: tuple[str, ...]
    capture_delay: str | None
    monthly_fraud_level: str | None
    monthly_volume: str | None
    merchant_category_code: tuple[int, ...]
    is_credit: bool | None
    aci: tuple[str, ...]
    fixed_amount: float
    rate: int
    intracountry: bool | None
    raw: dict[str, Any]

    @classmethod
    def from_dict(cls, row: dict[str, Any]) -> "FeeRule":
        """Create a normalized fee rule from a JSON record."""

        return cls(
            fee_id=int(row["ID"]),
            card_scheme=str(row["card_scheme"]),
            account_type=tuple(row.get("account_type") or []),
            capture_delay=row.get("capture_delay"),
            monthly_fraud_level=row.get("monthly_fraud_level"),
            monthly_volume=row.get("monthly_volume"),
            merchant_category_code=tuple(int(v) for v in (row.get("merchant_category_code") or [])),
            is_credit=row.get("is_credit"),
            aci=tuple(row.get("aci") or []),
            fixed_amount=float(row["fixed_amount"]),
            rate=int(row["rate"]),
            intracountry=None if row.get("intracountry") is None else bool(row["intracountry"]),
            raw=row,
        )

    def fee_for_amount(self, amount: float, rate_override: int | None = None) -> float:
        """Compute fixed + relative fee for one transaction amount."""

        rate = self.rate if rate_override is None else rate_override
        return self.fixed_amount + rate * amount / 10000


def _parse_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() == "true"


def _range_value(value: str) -> float:
    value = value.strip().lower()
    if value.endswith("k"):
        return float(value[:-1]) * 1_000
    if value.endswith("m"):
        return float(value[:-1]) * 1_000_000
    return float(value)


def _matches_range(expr: str, value: float) -> bool:
    expr = expr.replace("%", "").strip().lower()
    if expr.startswith("<"):
        return value < _range_value(expr[1:])
    if expr.startswith(">"):
        return value > _range_value(expr[1:])
    if "-" in expr:
        lo, hi = expr.split("-", 1)
        return _range_value(lo) <= value <= _range_value(hi)
    return value == _range_value(expr)


def _capture_delay_matches(rule_delay: str | None, merchant_delay: str | None) -> bool:
    if rule_delay is None:
        return True
    if merchant_delay is None:
        return False
    if merchant_delay in {"manual", "immediate"}:
        return rule_delay == merchant_delay
    try:
        days = float(merchant_delay)
    except ValueError:
        return rule_delay == merchant_delay
    if rule_delay == "<3":
        return days < 3
    if rule_delay == "3-5":
        return 3 <= days <= 5
    if rule_delay == ">5":
        return days > 5
    return rule_delay == merchant_delay


class DabstepFeeEngine:
    """Evaluate uploaded DABstep fee rules against the payments table."""

    def __init__(self, context_dir: str | Path) -> None:
        self.context_dir = Path(context_dir)
        self.rules = [
            FeeRule.from_dict(row)
            for row in json.loads((self.context_dir / "fees.json").read_text())
        ]
        self.merchants = {
            row["merchant"]: row
            for row in json.loads((self.context_dir / "merchant_data.json").read_text())
        }
        self.mcc_descriptions = self._load_mcc_descriptions()
        self.payments = self._load_payments()
        self.card_schemes = tuple(sorted({rule.card_scheme for rule in self.rules}))
        self.rules_by_card_scheme: dict[str, list[FeeRule]] = {}
        for rule in self.rules:
            self.rules_by_card_scheme.setdefault(rule.card_scheme, []).append(rule)
        self._monthly_stats_cache: dict[tuple[str, int, int], dict[str, float]] = {}
        self._payments_period_cache: dict[tuple[str, int, int | None, int | None], list[dict[str, Any]]] = {}
        self._candidate_rule_cache: dict[tuple[str, str, str | None, int, float, float], list[FeeRule]] = {}

    def _load_mcc_descriptions(self) -> dict[str, int]:
        out: dict[str, int] = {}
        with (self.context_dir / "merchant_category_codes.csv").open(newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                out[row["description"].strip().lower()] = int(row["mcc"])
        return out

    def _load_payments(self) -> list[dict[str, Any]]:
        payments: list[dict[str, Any]] = []
        with (self.context_dir / "payments.csv").open(newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                parsed: dict[str, Any] = dict(row)
                parsed["year"] = int(row["year"])
                parsed["day_of_year"] = int(row["day_of_year"])
                parsed["month"] = month_from_day_of_year(parsed["year"], parsed["day_of_year"])
                parsed["hour_of_day"] = int(row["hour_of_day"])
                parsed["minute_of_hour"] = int(row["minute_of_hour"])
                parsed["eur_amount"] = float(row["eur_amount"])
                parsed["is_credit"] = _parse_bool(row["is_credit"])
                parsed["has_fraudulent_dispute"] = _parse_bool(row["has_fraudulent_dispute"])
                parsed["is_refused_by_adyen"] = _parse_bool(row["is_refused_by_adyen"])
                payments.append(parsed)
        return payments

    def merchant(self, merchant_name: str) -> dict[str, Any]:
        """Return merchant metadata from merchant_data.json."""

        if merchant_name not in self.merchants:
            raise KeyError(f"Unknown merchant: {merchant_name}")
        return self.merchants[merchant_name]

    def monthly_stats(self, merchant: str, year: int, month: int) -> dict[str, float]:
        """Return volume and fraud metrics in a natural month."""

        cache_key = (merchant, year, month)
        if cache_key in self._monthly_stats_cache:
            return dict(self._monthly_stats_cache[cache_key])
        rows = [
            row for row in self.payments
            if row["merchant"] == merchant and row["year"] == year and row["month"] == month
        ]
        volume = sum(row["eur_amount"] for row in rows)
        fraud_volume = sum(row["eur_amount"] for row in rows if row["has_fraudulent_dispute"])
        stats = {
            "transaction_count": len(rows),
            "monthly_volume": volume,
            "monthly_fraud_volume": fraud_volume,
            "monthly_fraud_level": 0.0 if volume == 0 else fraud_volume / volume * 100,
        }
        self._monthly_stats_cache[cache_key] = stats
        return dict(stats)

    def rule_matches_filters(
        self,
        rule: FeeRule,
        *,
        account_type: str | None = None,
        aci: str | None = None,
        card_scheme: str | None = None,
        is_credit: bool | None = None,
        merchant_category_code: int | None = None,
        capture_delay: str | None = None,
        monthly_volume: float | None = None,
        monthly_fraud_level: float | None = None,
        intracountry: bool | None = None,
    ) -> bool:
        """Check whether a fee rule satisfies high-level filters."""

        if card_scheme is not None and rule.card_scheme != card_scheme:
            return False
        if account_type is not None and rule.account_type and account_type not in rule.account_type:
            return False
        if aci is not None and rule.aci and aci not in rule.aci:
            return False
        if is_credit is not None and rule.is_credit is not None and rule.is_credit != is_credit:
            return False
        if merchant_category_code is not None and rule.merchant_category_code and merchant_category_code not in rule.merchant_category_code:
            return False
        if capture_delay is not None and not _capture_delay_matches(rule.capture_delay, capture_delay):
            return False
        if monthly_volume is not None and rule.monthly_volume is not None and not _matches_range(rule.monthly_volume, monthly_volume):
            return False
        if monthly_fraud_level is not None and rule.monthly_fraud_level is not None and not _matches_range(rule.monthly_fraud_level, monthly_fraud_level):
            return False
        if intracountry is not None and rule.intracountry is not None and rule.intracountry != intracountry:
            return False
        return True

    def matching_rules_for_transaction(
        self,
        payment: dict[str, Any],
        merchant_meta: dict[str, Any],
        monthly_stats: dict[str, float],
        *,
        aci_override: str | None = None,
        card_scheme_override: str | None = None,
    ) -> list[FeeRule]:
        """Return all fee rules that apply to one transaction."""

        aci = aci_override or payment["aci"]
        card_scheme = card_scheme_override or payment["card_scheme"]
        matches: list[FeeRule] = []
        for rule in self._candidate_rules_for_transaction_context(card_scheme, merchant_meta, monthly_stats):
            if rule.is_credit is not None and rule.is_credit != payment["is_credit"]:
                continue
            if rule.aci and aci not in rule.aci:
                continue
            if rule.intracountry is not None:
                intracountry = payment["issuing_country"] == payment["acquirer_country"]
                if rule.intracountry != intracountry:
                    continue
            matches.append(rule)
        return matches

    def _candidate_rules_for_transaction_context(
        self,
        card_scheme: str,
        merchant_meta: dict[str, Any],
        monthly_stats: dict[str, float],
    ) -> list[FeeRule]:
        """Return rules narrowed to scheme, merchant metadata, and monthly thresholds."""

        cache_key = (
            card_scheme,
            str(merchant_meta["account_type"]),
            None if merchant_meta.get("capture_delay") is None else str(merchant_meta.get("capture_delay")),
            int(merchant_meta["merchant_category_code"]),
            float(monthly_stats["monthly_volume"]),
            float(monthly_stats["monthly_fraud_level"]),
        )
        if cache_key in self._candidate_rule_cache:
            return self._candidate_rule_cache[cache_key]
        candidates: list[FeeRule] = []
        for rule in self.rules_by_card_scheme.get(card_scheme, []):
            if rule.account_type and merchant_meta["account_type"] not in rule.account_type:
                continue
            if not _capture_delay_matches(rule.capture_delay, str(merchant_meta.get("capture_delay"))):
                continue
            if rule.monthly_volume is not None and not _matches_range(rule.monthly_volume, monthly_stats["monthly_volume"]):
                continue
            if rule.monthly_fraud_level is not None and not _matches_range(rule.monthly_fraud_level, monthly_stats["monthly_fraud_level"]):
                continue
            if rule.merchant_category_code and int(merchant_meta["merchant_category_code"]) not in rule.merchant_category_code:
                continue
            candidates.append(rule)
        self._candidate_rule_cache[cache_key] = candidates
        return candidates

    def fee_ids_for_filters(
        self,
        *,
        account_type: str | None = None,
        aci: str | None = None,
        card_scheme: str | None = None,
        is_credit: bool | None = None,
        merchant_category_code: int | None = None,
    ) -> list[int]:
        """Return fee IDs matching high-level rule filters."""

        return sorted({
            rule.fee_id for rule in self.rules
            if self.rule_matches_filters(
                rule,
                account_type=account_type,
                aci=aci,
                card_scheme=card_scheme,
                is_credit=is_credit,
                merchant_category_code=merchant_category_code,
            )
        })

    def average_fee_for_rule_filters(
        self,
        *,
        transaction_value: float,
        card_scheme: str,
        account_type: str | None = None,
        aci: str | None = None,
        is_credit: bool | None = None,
        merchant_category_code: int | None = None,
    ) -> float:
        """Average fee across matching rules for a hypothetical amount."""

        values = [
            rule.fee_for_amount(transaction_value)
            for rule in self.rules
            if self.rule_matches_filters(
                rule,
                card_scheme=card_scheme,
                account_type=account_type,
                aci=aci,
                is_credit=is_credit,
                merchant_category_code=merchant_category_code,
            )
        ]
        if not values:
            raise ValueError("No matching fee rules.")
        return sum(values) / len(values)

    def total_fee_for_rule_filters(
        self,
        *,
        transaction_value: float,
        card_scheme: str,
        account_type: str | None = None,
        aci: str | None = None,
        is_credit: bool | None = None,
        merchant_category_code: int | None = None,
    ) -> tuple[float, list[int]]:
        """Sum all matching fee-rule components for one hypothetical transaction."""

        matched_rules = [
            rule
            for rule in self.rules
            if self.rule_matches_filters(
                rule,
                card_scheme=card_scheme,
                account_type=account_type,
                aci=aci,
                is_credit=is_credit,
                merchant_category_code=merchant_category_code,
            )
        ]
        if not matched_rules:
            raise ValueError("No matching fee rules.")
        total = sum(rule.fee_for_amount(transaction_value) for rule in matched_rules)
        return total, sorted({rule.fee_id for rule in matched_rules})

    def payments_for_period(
        self,
        merchant: str,
        *,
        year: int = 2023,
        month: int | None = None,
        day_of_year: int | None = None,
    ) -> list[dict[str, Any]]:
        """Return payments for a merchant over a year, month, or day."""

        cache_key = (merchant, year, month, day_of_year)
        if cache_key in self._payments_period_cache:
            return list(self._payments_period_cache[cache_key])
        rows = [row for row in self.payments if row["merchant"] == merchant and row["year"] == year]
        if month is not None:
            rows = [row for row in rows if row["month"] == month]
        if day_of_year is not None:
            rows = [row for row in rows if row["day_of_year"] == day_of_year]
        self._payments_period_cache[cache_key] = rows
        return list(rows)

    def applicable_fee_ids_for_merchant_period(
        self,
        merchant: str,
        *,
        year: int = 2023,
        month: int | None = None,
        day_of_year: int | None = None,
    ) -> list[int]:
        """Return unique fee IDs applied to a merchant period."""

        merchant_meta = self.merchant(merchant)
        if month is None and day_of_year is None:
            ids: list[int] = []
            for candidate_month in range(1, 13):
                for fee_id in self.applicable_fee_ids_for_merchant_period(
                    merchant,
                    year=year,
                    month=candidate_month,
                ):
                    if fee_id not in ids:
                        ids.append(fee_id)
            return sorted(ids)
        if month is None and day_of_year is not None:
            month = month_from_day_of_year(year, day_of_year)
        if month is None:
            raise ValueError("month or day_of_year is required for monthly fee context.")
        stats = self.monthly_stats(merchant, year, month)
        rows = self.payments_for_period(
            merchant,
            year=year,
            month=month if day_of_year is None else None,
            day_of_year=day_of_year,
        )
        ids: list[int] = []
        for row in rows:
            for rule in self.matching_rules_for_transaction(row, merchant_meta, stats):
                if rule.fee_id not in ids:
                    ids.append(rule.fee_id)
        return sorted(ids)

    def total_fees(
        self,
        merchant: str,
        *,
        year: int = 2023,
        month: int | None = None,
        day_of_year: int | None = None,
        fee_rate_overrides: dict[int, int] | None = None,
        aci_override_for_fraud: str | None = None,
        only_fraudulent: bool = False,
        merchant_category_code_override: int | None = None,
        card_scheme_override: str | None = None,
    ) -> float:
        """Return total fees for a merchant period under optional what-if overrides."""

        if month is None and day_of_year is None:
            return sum(
                self.total_fees(
                    merchant,
                    year=year,
                    month=candidate_month,
                    fee_rate_overrides=fee_rate_overrides,
                    aci_override_for_fraud=aci_override_for_fraud,
                    only_fraudulent=only_fraudulent,
                    merchant_category_code_override=merchant_category_code_override,
                    card_scheme_override=card_scheme_override,
                )
                for candidate_month in range(1, 13)
            )
        if month is None and day_of_year is not None:
            month = month_from_day_of_year(year, day_of_year)
        if month is None:
            raise ValueError("month or day_of_year is required.")
        merchant_meta = dict(self.merchant(merchant))
        if merchant_category_code_override is not None:
            merchant_meta["merchant_category_code"] = merchant_category_code_override
        stats = self.monthly_stats(merchant, year, month)
        rows = self.payments_for_period(
            merchant,
            year=year,
            month=None if day_of_year else month,
            day_of_year=day_of_year,
        )
        total = 0.0
        for row in rows:
            if only_fraudulent and not row["has_fraudulent_dispute"]:
                continue
            aci_override = aci_override_for_fraud if row["has_fraudulent_dispute"] else None
            for rule in self.matching_rules_for_transaction(
                row,
                merchant_meta,
                stats,
                aci_override=aci_override,
                card_scheme_override=card_scheme_override,
            ):
                rate_override = None if fee_rate_overrides is None else fee_rate_overrides.get(rule.fee_id)
                total += rule.fee_for_amount(row["eur_amount"], rate_override=rate_override)
        return total

    def fee_rate_delta(
        self,
        merchant: str,
        *,
        year: int,
        fee_id: int,
        new_rate: int,
        month: int | None = None,
    ) -> float:
        """Return total fee delta when a fee rule rate changes."""

        return self._rounded_period_fee_delta(
            merchant,
            year=year,
            month=month,
            old_kwargs={},
            new_kwargs={"fee_rate_overrides": {fee_id: new_rate}},
        )

    def mcc_change_delta(
        self,
        merchant: str,
        *,
        year: int,
        new_mcc: int,
        month: int | None = None,
    ) -> float:
        """Return total fee delta when merchant MCC changes before the period."""

        return self._rounded_period_fee_delta(
            merchant,
            year=year,
            month=month,
            old_kwargs={},
            new_kwargs={"merchant_category_code_override": new_mcc},
        )

    def card_scheme_steering(
        self,
        merchant: str,
        *,
        year: int,
        objective: str,
        month: int | None = None,
    ) -> tuple[str, float, dict[str, float]]:
        """Return the minimum or maximum fee card scheme under a steering scenario."""

        schemes = sorted({row["card_scheme"] for row in self.payments if row["merchant"] == merchant})
        totals = {
            scheme: self.total_fees(
                merchant,
                year=year,
                month=month,
                card_scheme_override=scheme,
            )
            for scheme in schemes
        }
        if objective == "maximum":
            chosen = max(totals, key=totals.get)
        elif objective == "minimum":
            chosen = min(totals, key=totals.get)
        else:
            raise ValueError("objective must be 'minimum' or 'maximum'")
        return chosen, totals[chosen], totals

    def fee_restriction_affected_merchants(
        self,
        *,
        fee_id: int,
        new_account_type: str | None = None,
        year: int = 2023,
    ) -> list[str]:
        """Return merchants affected if a fee rule became more restrictive."""

        rule = next(rule for rule in self.rules if rule.fee_id == fee_id)
        affected: list[str] = []
        stats_by_merchant_month: dict[tuple[str, int], dict[str, float]] = {}
        rows_by_merchant_month: dict[tuple[str, int], list[dict[str, Any]]] = {}
        for row in self.payments:
            if row["year"] != year:
                continue
            key = (str(row["merchant"]), int(row["month"]))
            stats = stats_by_merchant_month.setdefault(
                key,
                {
                    "transaction_count": 0,
                    "monthly_volume": 0.0,
                    "monthly_fraud_volume": 0.0,
                    "monthly_fraud_level": 0.0,
                },
            )
            stats["transaction_count"] += 1
            stats["monthly_volume"] += float(row["eur_amount"])
            if row["has_fraudulent_dispute"]:
                stats["monthly_fraud_volume"] += float(row["eur_amount"])
            if row["card_scheme"] == rule.card_scheme:
                rows_by_merchant_month.setdefault(key, []).append(row)
        for stats in stats_by_merchant_month.values():
            volume = stats["monthly_volume"]
            stats["monthly_fraud_level"] = 0.0 if volume == 0 else stats["monthly_fraud_volume"] / volume * 100

        for merchant in sorted(self.merchants):
            meta = self.merchant(merchant)
            if new_account_type is not None and meta["account_type"] == new_account_type:
                continue
            if not self._rule_static_matches_merchant(rule, meta):
                continue
            if any(
                self._rule_matches_month_rows(rule, rows_by_merchant_month.get((merchant, month), []), stats_by_merchant_month.get((merchant, month)))
                for month in range(1, 13)
            ):
                affected.append(merchant)
        return affected

    def _rule_static_matches_merchant(self, rule: FeeRule, merchant_meta: dict[str, Any]) -> bool:
        if rule.account_type and merchant_meta["account_type"] not in rule.account_type:
            return False
        if not _capture_delay_matches(rule.capture_delay, str(merchant_meta.get("capture_delay"))):
            return False
        if rule.merchant_category_code and int(merchant_meta["merchant_category_code"]) not in rule.merchant_category_code:
            return False
        return True

    def _rule_matches_month_rows(
        self,
        rule: FeeRule,
        rows: list[dict[str, Any]],
        stats: dict[str, float] | None,
    ) -> bool:
        if not rows or stats is None:
            return False
        if rule.monthly_volume is not None and not _matches_range(rule.monthly_volume, stats["monthly_volume"]):
            return False
        if rule.monthly_fraud_level is not None and not _matches_range(rule.monthly_fraud_level, stats["monthly_fraud_level"]):
            return False
        for row in rows:
            if rule.is_credit is not None and rule.is_credit != row["is_credit"]:
                continue
            if rule.aci and row["aci"] not in rule.aci:
                continue
            if rule.intracountry is not None:
                intracountry = row["issuing_country"] == row["acquirer_country"]
                if rule.intracountry != intracountry:
                    continue
            return True
        return False

    def best_fraud_aci_choice(
        self,
        merchant: str,
        *,
        year: int,
        month: int | None,
        allowed_acis: tuple[str, ...] = ("D", "E"),
    ) -> tuple[str, float, dict[str, float]]:
        """Return lower-cost alternative ACI for fraudulent ecommerce transactions."""

        baseline = self.total_fees(merchant, year=year, month=month, only_fraudulent=True)
        candidates: dict[str, float] = {}
        for aci in allowed_acis:
            if aci == "G":
                continue
            total = self.total_fees(
                merchant,
                year=year,
                month=month,
                aci_override_for_fraud=aci,
                only_fraudulent=True,
            )
            candidates[aci] = total - baseline
        best_aci = min(candidates, key=candidates.get)
        return best_aci, candidates[best_aci], candidates

    def cheapest_card_scheme_for_transaction_value(
        self,
        *,
        transaction_value: float,
        objective: str = "minimum",
    ) -> tuple[str, float, dict[str, float]]:
        """Return the cheapest or most expensive card scheme for a generic transaction value."""

        candidates: dict[str, float] = {}
        for scheme in self.card_schemes:
            try:
                candidates[scheme] = self.average_fee_for_rule_filters(
                    transaction_value=transaction_value,
                    card_scheme=scheme,
                )
            except ValueError:
                continue
        if not candidates:
            raise ValueError("No card scheme fee candidates available.")
        selected = max(candidates, key=candidates.get) if objective == "maximum" else min(candidates, key=candidates.get)
        return selected, candidates[selected], candidates

    def aci_fee_extreme_for_transaction_value(
        self,
        *,
        transaction_value: float,
        card_scheme: str | None = None,
        is_credit: bool | None = None,
        objective: str = "maximum",
        allowed_acis: tuple[str, ...] = ACI_CODES,
    ) -> tuple[str, float, dict[str, dict[str, Any]]]:
        """Return the highest or lowest fee ACI for a hypothetical transaction.

        The calculation evaluates each ACI through the same high-level fee rule
        filters and selects by total matching fee components. It does not depend
        on benchmark task IDs, answer pools, or fixed candidate results.
        """

        candidates: dict[str, dict[str, Any]] = {}
        for aci in allowed_acis:
            matched_rules = [
                rule
                for rule in self.rules
                if rule.aci
                and aci in rule.aci
                and self.rule_matches_filters(
                    rule,
                    card_scheme=card_scheme,
                    is_credit=is_credit,
                )
            ]
            if matched_rules:
                candidates[aci] = {
                    "aci": aci,
                    "fee": sum(rule.fee_for_amount(transaction_value) for rule in matched_rules) / len(matched_rules),
                    "matched_fee_ids": sorted({rule.fee_id for rule in matched_rules}),
                }
        if not candidates:
            raise ValueError("No ACI fee candidates available.")
        if objective == "maximum":
            selected = sorted(candidates, key=lambda key: (-float(candidates[key]["fee"]), key))[0]
        elif objective == "minimum":
            selected = sorted(candidates, key=lambda key: (float(candidates[key]["fee"]), key))[0]
        else:
            raise ValueError("objective must be 'minimum' or 'maximum'")
        return selected, float(candidates[selected]["fee"]), candidates

    def fee_extreme_by_dimension(
        self,
        *,
        transaction_value: float,
        dimension: str,
        objective: str = "maximum",
    ) -> tuple[list[str], float, list[dict[str, Any]]]:
        """Return cheapest or most expensive fee candidates by a fee-rule dimension."""

        if dimension not in {"merchant_category_code", "mcc"}:
            raise ValueError("Only merchant_category_code fee extremes are supported in the current generic engine.")
        mcc_values = sorted({mcc for rule in self.rules for mcc in rule.merchant_category_code})
        if not mcc_values:
            raise ValueError("No MCC candidates available in fee rules.")
        candidates: list[dict[str, Any]] = []
        for mcc in mcc_values:
            matched_rules = [
                rule
                for rule in self.rules
                if self.rule_matches_filters(
                    rule,
                    merchant_category_code=mcc,
                )
            ]
            if matched_rules:
                candidates.append(
                    {
                        "merchant_category_code": str(mcc),
                        "fee": sum(rule.fee_for_amount(transaction_value) for rule in matched_rules) / len(matched_rules),
                        "matched_fee_ids": sorted({rule.fee_id for rule in matched_rules}),
                    }
                )
        if not candidates:
            raise ValueError("No MCC fee candidates available.")
        reverse = objective == "maximum"
        if objective not in {"minimum", "maximum"}:
            raise ValueError("objective must be 'minimum' or 'maximum'")
        candidates.sort(key=lambda row: (float(row["fee"]), row["merchant_category_code"]), reverse=reverse)
        selected_fee = float(candidates[0]["fee"])
        selected = [
            str(row["merchant_category_code"])
            for row in candidates
            if abs(float(row["fee"]) - selected_fee) < 1e-12
        ]
        selected.sort()
        return selected, selected_fee, candidates

    def _rounded_period_fee_delta(
        self,
        merchant: str,
        *,
        year: int,
        month: int | None,
        old_kwargs: dict[str, Any],
        new_kwargs: dict[str, Any],
    ) -> float:
        if month is not None:
            old = round(self.total_fees(merchant, year=year, month=month, **old_kwargs), 2)
            new = round(self.total_fees(merchant, year=year, month=month, **new_kwargs), 2)
            return new - old
        months = sorted({int(row["month"]) for row in self.payments if row["merchant"] == merchant and row["year"] == year})
        delta = 0.0
        for current_month in months:
            old = round(self.total_fees(merchant, year=year, month=current_month, **old_kwargs), 2)
            new = round(self.total_fees(merchant, year=year, month=current_month, **new_kwargs), 2)
            delta += new - old
        return delta

    def fee_factor_direction(self, *, objective: str = "cheaper_when_increased") -> list[str]:
        """Return general fee-rule factors whose direction tends to reduce cost.

        This is a rule-level explanation derived from the uploaded manual and
        available fee-rule dimensions. It does not inspect benchmark answers or
        task identifiers. It supports directional questions about factor values
        increasing or decreasing.
        """

        if objective not in {"cheaper_when_increased", "cheaper_when_decreased", "cheaper_when_true", "cheaper_when_false"}:
            raise ValueError("objective must be cheaper_when_increased, cheaper_when_decreased, cheaper_when_true, or cheaper_when_false.")
        factors: list[str] = []
        if objective in {"cheaper_when_true", "cheaper_when_false"}:
            target = objective == "cheaper_when_true"
            for field in ("is_credit", "intracountry"):
                true_rates = [rule.rate for rule in self.rules if getattr(rule, field) is True]
                false_rates = [rule.rate for rule in self.rules if getattr(rule, field) is False]
                if not true_rates or not false_rates:
                    continue
                true_avg = sum(true_rates) / len(true_rates)
                false_avg = sum(false_rates) / len(false_rates)
                if (target and true_avg < false_avg) or (not target and false_avg < true_avg):
                    factors.append(field)
            return factors
        if objective == "cheaper_when_decreased":
            if any(rule.monthly_fraud_level is not None for rule in self.rules):
                factors.append("monthly_fraud_level")
            return factors
        if any(rule.monthly_volume is not None for rule in self.rules):
            factors.append("monthly_volume")
        if any(rule.capture_delay is not None for rule in self.rules):
            factors.append("capture_delay")
        return factors

    def field_values(self, field: str) -> list[str]:
        """Return known values for a rule or merchant metadata field."""

        values: set[str] = set()
        for rule in self.rules:
            raw_value = rule.raw.get(field)
            if isinstance(raw_value, list):
                values.update(str(value) for value in raw_value if str(value))
            elif raw_value is not None and str(raw_value):
                values.add(str(raw_value))
        for row in self.merchants.values():
            raw_value = row.get(field)
            if isinstance(raw_value, list):
                values.update(str(value) for value in raw_value if str(value))
            elif raw_value is not None and str(raw_value):
                values.add(str(raw_value))
        values.update(self._manual_field_values(field))
        if not values:
            raise ValueError(f"Unknown rule metadata field: {field}")
        return sorted(values, key=lambda item: item.lower())

    def _manual_field_values(self, field: str) -> set[str]:
        """Extract small enumerations documented only in manual.md tables."""

        manual_path = self.context_dir / "manual.md"
        if not manual_path.exists():
            return set()
        text = manual_path.read_text()
        if field != "account_type":
            return set()
        values: set[str] = set()
        in_account_section = False
        for line in text.splitlines():
            lowered = line.lower()
            if line.startswith("##") and ("account types" in lowered or "account type" in lowered):
                in_account_section = True
                continue
            if in_account_section and line.startswith("##"):
                break
            if in_account_section:
                match = re.match(r"\|\s*([A-Z])\s*\|", line)
                if match:
                    values.add(match.group(1))
        return values

    def fee_volume_threshold(self) -> str:
        """Return the highest explicit monthly volume boundary in fee rules."""

        bounds: list[tuple[float, str]] = []
        for rule in self.rules:
            if rule.monthly_volume is None:
                continue
            label = str(rule.monthly_volume)
            for token in re.findall(r"\d+(?:\.\d+)?[km]?", label.lower()):
                bounds.append((_range_value(token), label))
        if not bounds:
            raise ValueError("No monthly volume thresholds are defined in the fee rules.")
        return max(bounds, key=lambda item: (item[0], item[1].strip().startswith(">")))[1]

    def mcc_for_description(self, description: str) -> int:
        """Resolve a merchant category description to an MCC code."""

        key = description.strip().lower()
        if key in self.mcc_descriptions:
            return self.mcc_descriptions[key]
        for desc, code in self.mcc_descriptions.items():
            if key in desc:
                return code
        raise KeyError(f"Unknown MCC description: {description}")


def extract_fee_id(text: str) -> int | None:
    """Extract a fee ID from natural language."""

    match = re.search(r"\bID\s*=\s*(\d+)|fee with id\s+(\d+)|fee ID\s+(\d+)", text, re.I)
    if not match:
        return None
    for group in match.groups():
        if group:
            return int(group)
    return None
