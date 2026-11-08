"""Reproducible arithmetic: no model-estimated counts or denominators."""
from __future__ import annotations

import csv
from collections import defaultdict
import math
from pathlib import Path
from statistics import NormalDist


def number(value, name: str, minimum: float = 0) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{name}: нужен числовой показатель.")
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name}: пропуск или нечисловое значение.") from exc
    if not math.isfinite(result) or result < minimum:
        raise ValueError(f"{name}: значение должно быть конечным и ≥ {minimum}.")
    return result


def wilson(successes: int, total: int, z: float = 1.959963984540054) -> list[float]:
    p = successes / total
    center = (p + z * z / (2 * total)) / (1 + z * z / total)
    radius = z * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total)) / (1 + z * z / total)
    return [max(0.0, center - radius), min(1.0, center + radius)]


def analyze_csv(path: Path, numerator: str, denominator: str, group_by: str | None = None, period_column: str | None = None, unit: str = "users") -> dict:
    if unit not in {"users", "accounts", "events", "sessions", "families"}:
        raise ValueError("unit: users, accounts, events, sessions или families.")
    groups = defaultdict(lambda: {"numerator": 0, "denominator": 0, "rows": [], "periods": set()})
    with path.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        required = {numerator, denominator} | ({group_by} if group_by else set()) | ({period_column} if period_column else set())
        if not reader.fieldnames or not required.issubset(reader.fieldnames):
            raise ValueError("В CSV нет всех заданных столбцов: " + ", ".join(sorted(required)))
        if len(set(reader.fieldnames)) != len(reader.fieldnames):
            raise ValueError("Повторяющиеся названия столбцов CSV.")
        seen_rows = set()
        for line, row in enumerate(reader, 2):
            if None in row:
                raise ValueError(f"Строка {line}: лишние ячейки.")
            if "unit" in row and row["unit"] != unit:
                raise ValueError(f"Строка {line}: единица CSV не совпадает с unit={unit}.")
            fingerprint = tuple(row.items())
            if fingerprint in seen_rows:
                raise ValueError(f"Строка {line}: точный дубль строки; проверьте двойной учёт.")
            seen_rows.add(fingerprint)
            count = number(row[numerator], f"Строка {line}, {numerator}")
            total = number(row[denominator], f"Строка {line}, {denominator}")
            if not count.is_integer() or not total.is_integer() or total <= 0 or count > total:
                raise ValueError(f"Строка {line}: требуются целые счётчики 0 ≤ numerator ≤ denominator и denominator > 0.")
            key = row[group_by].strip() if group_by else "all"
            if not key or (period_column and not row[period_column]):
                raise ValueError(f"Строка {line}: пропущена группа или период.")
            item = groups[key]
            item["numerator"] += int(count)
            item["denominator"] += int(total)
            item["rows"].append(line)
            if period_column:
                item["periods"].add(row[period_column])
    if not groups:
        raise ValueError("CSV не содержит наблюдений.")
    values = []
    for key, item in groups.items():
        values.append({"group": key, **item, "periods": sorted(item["periods"]), "rate": item["numerator"] / item["denominator"], "wilson_95": wilson(item["numerator"], item["denominator"])})
    return {"method": "ratio_of_sums; Wilson 95%", "formula": "sum(numerator)/sum(denominator)", "unit": unit, "numerator_column": numerator, "denominator_column": denominator, "group_by": group_by, "period_column": period_column, "groups": values, "assumptions": ["Строки описывают непересекающиеся выборки; инструмент не может установить это из счётчиков.", "Интервал предполагает независимые бинарные наблюдения. Для повторных событий по пользователю нужен кластерный анализ.", "Наблюдаемая разница не доказывает причинность."], "warnings": ([] if period_column else ["Период не задан; нельзя сравнивать результаты с другим периодом без проверки."])}


def economics(scenarios: list[dict], currency: str = "RUB", period: str = "month") -> dict:
    if not isinstance(scenarios, list) or not 1 <= len(scenarios) <= 20:
        raise ValueError("Нужны 1–20 сценариев.")
    result = []
    for scenario in scenarios:
        users = number(scenario.get("users"), "users")
        conversion = number(scenario.get("conversion_rate"), "conversion_rate")
        price = number(scenario.get("price"), "price")
        variable = number(scenario.get("variable_cost_per_user"), "variable_cost_per_user")
        fixed = number(scenario.get("fixed_cost"), "fixed_cost")
        basis = scenario.get("variable_cost_basis", "all_users")
        if basis not in ("all_users", "paying_users"):
            raise ValueError("variable_cost_basis: all_users или paying_users; укажите знаменатель затрат из источника.")
        if conversion > 1:
            raise ValueError("conversion_rate должна быть долей от 0 до 1.")
        revenue = users * conversion * price
        cost_users = users if basis == "all_users" else users * conversion
        costs = cost_users * variable + fixed
        margin_per_user = conversion * price - variable * (1 if basis == "all_users" else conversion)
        if not all(math.isfinite(v) for v in (revenue, costs, margin_per_user, revenue - costs)):
            raise ValueError("Сценарий вызывает переполнение: проверьте порядок величин и единицы.")
        result.append({"name": str(scenario.get("name", "Сценарий")), "inputs": scenario, "variable_cost_basis": basis, "variable_cost_users": cost_users,
                       "warnings": [] if "variable_cost_basis" in scenario else ["Знаменатель затрат не задан: для совместимости принят all_users. Проверьте источник до использования результата."],
                       "revenue": round(revenue, 2), "costs": round(costs, 2), "contribution": round(revenue - costs, 2), "break_even_users": math.ceil(fixed / margin_per_user) if margin_per_user > 0 else None})
    return {"kind": "forecast", "currency": currency, "period": period, "scenarios": result, "formula": "revenue=users*conversion_rate*price; costs=variable_cost_users*variable_cost_per_user+fixed_cost; variable_cost_users=users for all_users, users*conversion_rate for paying_users", "limitations": ["Входные числа — сценарные допущения, пока не привязаны к источникам.", "conversion_rate — доля платящих, не активация. Знаменатель затрат должен соответствовать источнику.", "Цена и затраты должны относиться к одному периоду. CAC не является повторяющимся расходом: учитывайте приобретение клиентов отдельно, не дублируя его каждый месяц."]}


def experiment_size(baseline: float, absolute_mde: float, alpha: float = .05, power: float = .8) -> dict:
    baseline = number(baseline, "baseline")
    mde = number(absolute_mde, "absolute_mde")
    if not 0 < baseline < 1 or not 0 < baseline + mde < 1 or mde <= 0 or not 0 < alpha < .5 or not .5 < power < 1:
        raise ValueError("Нужны baseline ∈ (0,1), положительный absolute_mde с baseline+mde<1, alpha∈(0,.5), power∈(.5,1).")
    p1, p2 = baseline, baseline + mde
    pooled = (p1 + p2) / 2
    za, zb = NormalDist().inv_cdf(1 - alpha / 2), NormalDist().inv_cdf(power)
    n = math.ceil((za * math.sqrt(2 * pooled * (1 - pooled)) + zb * math.sqrt(p1 * (1 - p1) + p2 * (1 - p2))) ** 2 / mde ** 2)
    return {"users_per_arm": n, "arms": 2, "baseline": baseline, "absolute_mde": mde, "alpha": alpha, "power": power, "method": "normal approximation, two-sided two proportions, equal allocation", "limitations": ["Планировочная оценка, не результат эксперимента.", "Независимые пользователи, одна основная метрика; для кластеров, множественных проверок или ранних остановок нужен другой дизайн."]}
