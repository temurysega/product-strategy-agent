"""Reproduce authored synthetic case arithmetic; no network or model calls."""
from __future__ import annotations

import csv
import json
import math
from pathlib import Path


def calculate(root: Path | None = None) -> dict:
    root = root or Path(__file__).resolve().parent
    with (root / "materials" / "activation.csv").open(encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream))
    counts = {row["variant"]: (int(row["activated"]), int(row["invited"])) for row in rows}
    if len(rows) != 2 or set(counts) != {"control", "guided"}:
        raise ValueError("Expected two distinct variant rows")
    if len({row["period"] for row in rows}) != 1 or {row["unit"] for row in rows} != {"families"}:
        raise ValueError("Incompatible periods or units")
    for success, total in counts.values():
        if total <= 0 or not 0 <= success <= total:
            raise ValueError("Invalid counts")
    a, b = counts["control"], counts["guided"]
    pa, pb = a[0] / a[1], b[0] / b[1]
    delta = pb - pa
    se = math.sqrt(pa * (1 - pa) / a[1] + pb * (1 - pb) / b[1])
    average = (pa + pb) / 2
    numerator = 1.96 * math.sqrt(2 * average * (1 - average))
    numerator += 0.8416212336 * math.sqrt(pa * (1 - pa) + pb * (1 - pb))
    sample = math.ceil(numerator**2 / delta**2)
    economics = []
    with (root / "materials" / "economics.csv").open(encoding="utf-8", newline="") as stream:
        for row in csv.DictReader(stream):
            margin = float(row["price_rub"]) - float(row["variable_cost_rub"])
            churn, cac = float(row["monthly_churn"]), float(row["cac_rub"])
            if not 0 < churn <= 1 or cac <= 0 or margin <= 0:
                raise ValueError("Unsupported economics inputs")
            ltv = margin / churn
            economics.append({"scenario": row["scenario"], "margin_rub_month": margin,
                              "simple_ltv_rub": round(ltv, 6), "ltv_cac": round(ltv / cac, 6),
                              "payback_months": round(cac / margin, 6)})
    return {
        "provenance": "synthetic", "model_calls": 0, "empirical_product_effect": False,
        "activation": {"control": pa, "guided": pb, "absolute_lift_pp": round(100 * delta, 6),
                       "relative_lift_percent": round(100 * delta / pa, 6),
                       "difference_95_ci_pp_normal": [round(100 * (delta - 1.96 * se), 6),
                                                     round(100 * (delta + 1.96 * se), 6)],
                       "approximate_minimum_per_arm": sample},
        "economics": economics,
        "standalone_max_variable_cost_for_ltv_eq_cac": 149 - 700 * .08,
        "pilot_break_even_extra_families_assumed": 900000 / 600,
        "pilot_break_even_extra_families_revised_assumed": 900000 / 100,
        "limitations": ["No observed customer outcomes", "No discounting, tax or fixed costs in simple LTV",
                        "Normal approximation for difference; one predeclared primary metric"]
    }


if __name__ == "__main__":
    print(json.dumps(calculate(), ensure_ascii=False, indent=2))
