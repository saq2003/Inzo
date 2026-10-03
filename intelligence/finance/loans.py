"""Loan amortization schedule built on ``calculations.loan_emi`` (pure)."""

from __future__ import annotations

from decimal import Decimal
from typing import TypedDict

from intelligence.finance.calculations import loan_emi

_CENT = Decimal("0.01")


class AmortRow(TypedDict):
    """One month of the schedule: payment split and remaining balance."""

    month: int
    payment: Decimal
    principal: Decimal
    interest: Decimal
    balance: Decimal


def amortization_schedule(
    principal: Decimal, annual_rate_pct: Decimal, months: int
) -> list[AmortRow]:
    """Monthly amortization schedule; the final row absorbs rounding.

    Raises ``ValueError`` for non-positive principal/months or a negative rate.
    """
    if principal <= 0:
        raise ValueError("principal must be positive")
    if months <= 0:
        raise ValueError("months must be positive")
    if annual_rate_pct < 0:
        raise ValueError("rate must be >= 0")
    emi = loan_emi(principal, annual_rate_pct, months)
    monthly_rate = annual_rate_pct / Decimal("1200")
    balance = principal
    rows: list[AmortRow] = []
    for month in range(1, months + 1):
        interest = (balance * monthly_rate).quantize(_CENT)
        if month == months:
            principal_part = balance
            payment = (principal_part + interest).quantize(_CENT)
        else:
            principal_part = (emi - interest).quantize(_CENT)
            payment = emi
        balance = (balance - principal_part).quantize(_CENT)
        rows.append(
            AmortRow(
                month=month,
                payment=payment,
                principal=principal_part,
                interest=interest,
                balance=max(balance, Decimal("0")),
            )
        )
    return rows
