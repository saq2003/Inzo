"""Expense parsing, categorization, and aggregation (pure, deterministic)."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path

_CENT = Decimal("0.01")

#: Keyword rules mapping a category to the substrings that select it.
#: Checked in order; the first category with a matching keyword wins.
CATEGORY_KEYWORDS: dict[str, tuple[str, ...]] = {
    "food": (
        "restaurant", "cafe", "coffee", "food", "dinner", "lunch", "breakfast",
        "pizza", "burger", "swiggy", "zomato", "dominos", "mcdonald", "tea",
        "snack", "grocery", "groceries", "supermarket", "dmart", "bigbasket",
        "blinkit", "zepto",
    ),
    "finance": (
        "emi", "loan", "insurance", "premium", "mutual fund", "sip",
        "investment", "bank", "credit card", "interest", "brokerage",
    ),
    "transport": (
        "uber", "ola", "taxi", "cab", "fuel", "petrol", "diesel", "metro",
        "bus", "train", "flight", "airline", "parking", "toll", "bike",
    ),
    "utilities": (
        "electricity", "water", "gas", "internet", "broadband", "mobile",
        "recharge", "rent", "bill", "jio", "airtel", "wifi",
    ),
    "shopping": (
        "amazon", "flipkart", "myntra", "shopping", "clothes", "apparel",
        "shoes", "mall", "store",
    ),
    "health": (
        "hospital", "doctor", "pharmacy", "medicine", "medical", "clinic",
        "apollo", "pharmeasy", "gym", "fitness",
    ),
    "entertainment": (
        "movie", "cinema", "netflix", "spotify", "concert", "game",
        "theatre", "bookmyshow", "hotstar", "prime",
    ),
    "education": (
        "course", "tuition", "school", "college", "udemy", "coursera",
        "exam", "kindle",
    ),
    "travel": (
        "hotel", "airbnb", "makemytrip", "trip", "vacation", "holiday",
    ),
}


@dataclass(frozen=True)
class Expense:
    """One expense line: ISO date, description, amount, and category."""

    date: str  # ISO YYYY-MM-DD
    description: str
    amount: Decimal
    category: str


def categorize(description: str) -> str:
    """Classify a description with keyword rules; falls back to ``"other"``."""
    text = description.lower()
    for category, keywords in CATEGORY_KEYWORDS.items():
        if any(keyword in text for keyword in keywords):
            return category
    return "other"


def _parse_amount(raw: str) -> Decimal:
    try:
        value = Decimal(raw.replace(",", "").strip())
    except InvalidOperation as exc:
        raise ValueError(f"invalid amount: {raw!r}") from exc
    return value.quantize(_CENT)


def parse_csv(path: str | Path) -> list[Expense]:
    """Parse a CSV with ``date,description,amount`` columns into expenses.

    Raises ``ValueError`` on unreadable files, missing columns, or bad rows.
    """
    csv_path = Path(path)
    try:
        handle = csv_path.open("r", encoding="utf-8-sig", newline="")
    except OSError as exc:
        raise ValueError(f"cannot read csv file: {csv_path}") from exc
    expenses: list[Expense] = []
    with handle:
        reader = csv.DictReader(handle)
        headers = {(h or "").lower() for h in (reader.fieldnames or [])}
        missing = {"date", "description", "amount"} - headers
        if missing:
            raise ValueError(f"csv missing columns: {sorted(missing)}")
        for lineno, row in enumerate(reader, start=2):
            norm: dict[str, str] = {}
            for key, value in row.items():
                if key is not None:
                    norm[key.lower()] = (value or "").strip()
            raw_date = norm.get("date", "")
            try:
                date.fromisoformat(raw_date)
            except ValueError as exc:
                raise ValueError(f"row {lineno}: invalid ISO date: {raw_date!r}") from exc
            description = norm.get("description", "")
            amount = _parse_amount(norm.get("amount", ""))
            expenses.append(
                Expense(
                    date=raw_date,
                    description=description,
                    amount=amount,
                    category=categorize(description),
                )
            )
    return expenses


def totals_by_category(expenses: list[Expense]) -> dict[str, Decimal]:
    """Sum amounts per category, sorted by category name."""
    totals: dict[str, Decimal] = {}
    for expense in expenses:
        totals[expense.category] = totals.get(expense.category, Decimal("0")) + expense.amount
    return {k: v.quantize(_CENT) for k, v in sorted(totals.items())}


def totals_by_month(expenses: list[Expense]) -> dict[str, Decimal]:
    """Sum amounts per ``YYYY-MM`` month, sorted chronologically."""
    totals: dict[str, Decimal] = {}
    for expense in expenses:
        month = expense.date[:7]
        totals[month] = totals.get(month, Decimal("0")) + expense.amount
    return {k: v.quantize(_CENT) for k, v in sorted(totals.items())}
