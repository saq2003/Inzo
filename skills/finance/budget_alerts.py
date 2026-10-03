"""Budget alerts: set per-category budgets; background tick warns at 80%/100%."""

from __future__ import annotations

import inspect
import json
from datetime import datetime
from decimal import Decimal

from intelligence.finance.budget import check_budgets
from intelligence.finance.calculations import format_money
from intelligence.finance.expenses import totals_by_category
from skills.base import Skill, SkillContext, require_data_dir
from skills.finance.expense_tracker import _load_expenses, _to_decimal
from storage.sqlite_store import SQLiteKVStore

_STORE = "budgets.db"
_INDEX_KEY = "budgets:index"


def _load_categories(kv: SQLiteKVStore) -> list[str]:
    raw = kv.get(_INDEX_KEY)
    if raw is None:
        return []
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError("corrupt budget index") from exc
    if not isinstance(data, list):
        raise ValueError("corrupt budget index")
    return [str(item) for item in data]


async def _notify(context: SkillContext, text: str) -> bool:
    """Deliver a notification when a notification center is wired."""
    center = context.notifications
    if center is None:
        return False
    send = getattr(center, "send", None) or getattr(center, "notify", None)
    if send is None:
        return False
    result = send(text)
    if inspect.isawaitable(result):
        await result
    return True


class BudgetAlertsSkill(Skill):
    """Sets per-category budgets and warns when spend crosses 80% or 100%."""

    name = "budget_alerts"
    description = (
        "Budget guardrails: 'set <category> <amount>' stores a monthly budget; "
        "the hourly tick compares it against this month's expenses and notifies "
        "when a category hits 80% (warning) or 100% (exceeded)."
    )
    intents = ("budget.set", "budget.check")
    required_capabilities = ("skills.execute", "memory.write", "memory.read", "notify.send")
    background = True
    local_only = True
    tick_interval_s = 3600.0

    async def handle(self, context: SkillContext) -> str:
        text = context.message.strip()
        if text.lower().startswith("set "):
            return self._set(context, text[4:])
        return await self._check(context)

    def _set(self, context: SkillContext, arg: str) -> str:
        parts = arg.rsplit(None, 1)
        if len(parts) != 2:
            return "budget usage: 'set <category> <amount>'"
        category = parts[0].strip().lower()
        try:
            amount = _to_decimal(parts[1])
        except ValueError as exc:
            return f"budget set failed: {exc}"
        if not category or amount <= 0:
            return "budget set failed: need a category and a positive amount"
        kv = SQLiteKVStore(require_data_dir(context) / _STORE)
        kv.put(f"budget:{category}", str(amount))
        categories = _load_categories(kv)
        if category not in categories:
            categories.append(category)
            kv.put(_INDEX_KEY, json.dumps(sorted(categories)))
        return f"budget set: {category} = {format_money(amount)}"

    async def _check(self, context: SkillContext) -> str:
        kv = SQLiteKVStore(require_data_dir(context) / _STORE)
        categories = _load_categories(kv)
        if not categories:
            return "no budgets set — use 'set <category> <amount>'"
        budgets: dict[str, Decimal] = {}
        for category in categories:
            raw = kv.get(f"budget:{category}")
            if raw is not None:
                budgets[category] = _to_decimal(raw)
        month = datetime.now().astimezone().strftime("%Y-%m")
        expenses = [e for e in _load_expenses(context) if e.date.startswith(month)]
        spend = totals_by_category(expenses)
        alerts = check_budgets(budgets, spend)
        if not alerts:
            return f"budgets ok for {month} — nothing at 80%+"
        lines: list[str] = []
        for alert in alerts:
            level = "exceeded" if alert["pct"] >= 100 else "warning"
            msg = (
                f"budget {level}: {alert['category']} spent "
                f"{format_money(alert['spent'])} of {format_money(alert['budget'])} "
                f"({alert['pct']}%)"
            )
            lines.append(msg)
            await _notify(context, msg)
        return "\n".join(lines)


SKILLS: list[Skill] = [BudgetAlertsSkill()]
