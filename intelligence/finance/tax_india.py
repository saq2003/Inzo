"""New-regime income tax for India, FY 2025-26 (pure, deterministic).

Slabs (marginal): 0-4L 0%, 4-8L 5%, 8-12L 10%, 12-16L 15%, 16-20L 20%,
20-24L 25%, above 24L 30%. Salaried taxpayers get a Rs 75,000 standard
deduction; rebate u/s 87A zeroes the tax when taxable income <= Rs 12L.
"""

from __future__ import annotations

from decimal import Decimal
from typing import TypedDict

_CENT = Decimal("0.01")

STANDARD_DEDUCTION = Decimal("75000")
REBATE_LIMIT = Decimal("1200000")

#: (upper bound, marginal rate) for the new regime, FY 2025-26.
_SLABS: tuple[tuple[Decimal, Decimal], ...] = (
    (Decimal("400000"), Decimal("0")),
    (Decimal("800000"), Decimal("0.05")),
    (Decimal("1200000"), Decimal("0.10")),
    (Decimal("1600000"), Decimal("0.15")),
    (Decimal("2000000"), Decimal("0.20")),
    (Decimal("2400000"), Decimal("0.25")),
    (Decimal("Infinity"), Decimal("0.30")),
)


class TaxBreakdown(TypedDict):
    """Full breakdown of a new-regime tax computation."""

    gross_income: Decimal
    standard_deduction: Decimal
    taxable_income: Decimal
    slab_tax: Decimal
    rebate_87a: Decimal
    total_tax: Decimal
    effective_rate_pct: Decimal


def _slab_tax(taxable: Decimal) -> Decimal:
    tax = Decimal("0")
    lower = Decimal("0")
    for upper, rate in _SLABS:
        if taxable <= lower:
            break
        tax += (min(taxable, upper) - lower) * rate
        lower = upper
    return tax


def compute_tax(income: Decimal, salaried: bool = True) -> TaxBreakdown:
    """Compute new-regime income tax for FY 2025-26.

    Applies the Rs 75,000 standard deduction for salaried income and the
    section 87A rebate (tax = 0 when taxable income is at most Rs 12L).
    """
    if income < 0:
        raise ValueError("income must be >= 0")
    deduction = STANDARD_DEDUCTION if salaried else Decimal("0")
    taxable = max(Decimal("0"), income - deduction)
    slab_tax = _slab_tax(taxable).quantize(_CENT)
    rebate = slab_tax if taxable <= REBATE_LIMIT else Decimal("0")
    total = (slab_tax - rebate).quantize(_CENT)
    effective = (total / income * 100).quantize(_CENT) if income > 0 else Decimal("0")
    return TaxBreakdown(
        gross_income=income.quantize(_CENT),
        standard_deduction=deduction.quantize(_CENT),
        taxable_income=taxable.quantize(_CENT),
        slab_tax=slab_tax,
        rebate_87a=rebate,
        total_tax=total,
        effective_rate_pct=effective,
    )
