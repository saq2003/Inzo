"""Expense tracking: add, CSV import, and spend reports."""

from __future__ import annotations

import re
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import cast

from intelligence.finance.calculations import format_money
from intelligence.finance.expenses import Expense, categorize, parse_csv, totals_by_category
from skills.base import Skill, SkillContext, require_data_dir
from storage.sqlite_store import SQLiteDocumentStore

_STORE = "expenses.db"
_MONTH_RE = re.compile(r"^\d{4}-\d{2}$")


def _to_decimal(raw: str) -> Decimal:
    try:
        return Decimal(raw.replace(",", "").strip())
    except InvalidOperation as exc:
        raise ValueError(f"invalid amount: {raw!r}") from exc


def _resolve_csv_path(context: SkillContext, raw: str) -> Path:
    """Accept a path inside the skill data dir or an absolute path; no shell."""
    candidate = Path(raw.strip())
    if not candidate.is_absolute():
        candidate = require_data_dir(context) / candidate
    resolved = candidate.resolve()
    if not resolved.is_file():
        raise ValueError(f"csv not found: {raw.strip()}")
    return resolved


def _expense_doc(expense: Expense) -> dict[str, str]:
    return {
        "date": expense.date,
        "description": expense.description,
        "amount": str(expense.amount),
        "category": expense.category,
    }


def _load_expenses(context: SkillContext) -> list[Expense]:
    """Read all stored expenses; tolerate a missing store file."""
    path = require_data_dir(context) / _STORE
    if not path.exists():
        return []
    store = SQLiteDocumentStore(path)
    expenses: list[Expense] = []
    for doc in store.search("", limit=100000):
        data = cast(dict[str, str], doc)
        expenses.append(
            Expense(
                date=str(data.get("date", "")),
                description=str(data.get("description", "")),
                amount=_to_decimal(str(data.get("amount", "0"))),
                category=str(data.get("category", "other")),
            )
        )
    return expenses


class ExpenseTrackerSkill(Skill):
    """Records expenses with auto-categorization, imports bank CSVs, reports spend."""

    name = "expense_tracker"
    description = (
        "Tracks expenses: 'add <amount> <description>' stores a categorized expense, "
        "'import <csvpath>' loads a date,description,amount CSV, 'report [YYYY-MM]' "
        "shows totals by category."
    )
    intents = ("expense.add", "expense.import", "expense.report")
    required_capabilities = ("skills.execute", "memory.write", "memory.read", "system.read")
    background = True
    local_only = True

    async def handle(self, context: SkillContext) -> str:
        text = context.message.strip()
        lowered = text.lower()
        if lowered.startswith("add "):
            return self._add(context, text[4:])
        if lowered.startswith("import "):
            return self._import(context, text[7:])
        if lowered.startswith("report"):
            return self._report(context, text[6:].strip())
        return (
            "expense_tracker: 'add <amount> <description>' | 'import <csvpath>' | "
            "'report [YYYY-MM]'"
        )

    def _add(self, context: SkillContext, arg: str) -> str:
        parts = arg.split(None, 1)
        if len(parts) != 2:
            return "add usage: 'add <amount> <description>'"
        try:
            amount = _to_decimal(parts[0])
        except ValueError as exc:
            return f"add failed: {exc}"
        if amount <= 0:
            return "add failed: amount must be positive"
        description = parts[1].strip()
        expense = Expense(
            date=datetime.now().astimezone().date().isoformat(),
            description=description,
            amount=amount,
            category=categorize(description),
        )
        store = SQLiteDocumentStore(require_data_dir(context) / _STORE)
        store.add(_expense_doc(expense))
        return f"added {format_money(amount)} — {description} [{expense.category}]"

    def _import(self, context: SkillContext, arg: str) -> str:
        try:
            path = _resolve_csv_path(context, arg)
            parsed = parse_csv(path)
        except ValueError as exc:
            return f"import failed: {exc}"
        store = SQLiteDocumentStore(require_data_dir(context) / _STORE)
        for expense in parsed:
            store.add(_expense_doc(expense))
        return f"imported {len(parsed)} expenses from {path.name}"

    def _report(self, context: SkillContext, arg: str) -> str:
        month = arg.strip()
        if month and not _MONTH_RE.match(month):
            return "report usage: 'report' or 'report YYYY-MM'"
        expenses = [
            e for e in _load_expenses(context) if not month or e.date.startswith(month)
        ]
        if not expenses:
            return f"no expenses recorded{f' for {month}' if month else ''}"
        totals = totals_by_category(expenses)
        grand = sum(totals.values(), Decimal("0"))
        lines = [f"spend report{f' {month}' if month else ''} — total {format_money(grand)}"]
        lines.extend(f"  {cat}: {format_money(amount)}" for cat, amount in totals.items())
        return "\n".join(lines)


SKILLS: list[Skill] = [ExpenseTrackerSkill()]
