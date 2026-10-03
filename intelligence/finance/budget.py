"""Budget-vs-spend alerting (pure, deterministic)."""

from __future__ import annotations

from decimal import Decimal
from typing import TypedDict

_ALERT_THRESHOLD_PCT = Decimal("80")


class BudgetAlert(TypedDict):
    """One breached (or nearly breached) budget."""

    category: str
    budget: Decimal
    spent: Decimal
    pct: Decimal


def check_budgets(
    budgets: dict[str, Decimal], spend: dict[str, Decimal]
) -> list[BudgetAlert]:
    """Return alerts for categories at or above 80% of budget, worst first.

    Categories with a non-positive budget are skipped.
    """
    alerts: list[BudgetAlert] = []
    for category, budget in budgets.items():
        if budget <= 0:
            continue
        spent = spend.get(category, Decimal("0"))
        pct = (spent / budget * 100).quantize(Decimal("0.01"))
        if pct >= _ALERT_THRESHOLD_PCT:
            alerts.append(
                BudgetAlert(category=category, budget=budget, spent=spent, pct=pct)
            )
    alerts.sort(key=lambda alert: alert["pct"], reverse=True)
    return alerts
