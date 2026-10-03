"""Finance engine tests: deterministic calculations (no LLM involved)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from intelligence.finance import calculations as fin


def test_compound_growth_exact():
    assert fin.compound_growth(1000, 10, 1) == Decimal("1100.00")


def test_compound_growth_five_years():
    # 10000 * 1.08^5 = 14693.28 (rounded)
    assert fin.compound_growth(10000, 8, 5) == Decimal("14693.28")


def test_compound_growth_monthly_compounding():
    result = fin.compound_growth(1200, 12, 1, compounds_per_year=12)
    assert result == Decimal("1352.19")  # 1200 * (1.01)^12


def test_compound_growth_rejects_negative():
    with pytest.raises(ValueError):
        fin.compound_growth(-100, 5, 1)


def test_loan_emi_range_and_math():
    emi = fin.loan_emi(500000, 9, 60)
    # Sanity: total repaid exceeds principal; EMI in a tight plausible band.
    assert emi * 60 > Decimal("500000")
    assert Decimal("10000") < emi < Decimal("11000")


def test_loan_emi_zero_rate():
    assert fin.loan_emi(12000, 0, 12) == Decimal("1000.00")


def test_loan_emi_rejects_bad_input():
    with pytest.raises(ValueError):
        fin.loan_emi(0, 9, 60)
    with pytest.raises(ValueError):
        fin.loan_emi(1000, 9, 0)


def test_budget_summary():
    out = fin.budget_summary(5000, {"rent": 1500, "food": 800})
    assert out["total_expenses"] == Decimal("2300.00")
    assert out["remaining"] == Decimal("2700.00")
    assert out["savings_rate_pct"] == Decimal("54.00")


def test_budget_summary_rejects_negative_expense():
    with pytest.raises(ValueError):
        fin.budget_summary(5000, {"rent": -10})


def test_portfolio_value():
    out = fin.portfolio_value(
        [
            {"symbol": "AAA", "quantity": 10, "price": "100.50"},
            {"symbol": "BBB", "quantity": 5, "price": 20},
        ]
    )
    assert out["total"] == Decimal("1105.00")
    assert len(out["holdings"]) == 2


def test_net_cash_flow():
    assert fin.net_cash_flow([1000, 250.5], [400, 100]) == Decimal("750.50")


def test_percent_change():
    assert fin.percent_change(100, 120) == Decimal("20.00")
    with pytest.raises(ValueError):
        fin.percent_change(0, 10)


def test_xirr_simple_one_year():
    # -1000 then +1100 ~366 days later ≈ 10%.
    rate = fin.xirr([(date(2024, 1, 1), -1000), (date(2025, 1, 1), 1100)])
    assert float(rate) == pytest.approx(0.10, rel=0.02)


def test_xirr_needs_inflow_and_outflow():
    with pytest.raises(ValueError):
        fin.xirr([(date(2024, 1, 1), 100), (date(2025, 1, 1), 200)])


def test_scenario_analysis():
    out = fin.scenario_analysis({"rev": 1000}, {"rev": 10})
    assert out["rev"] == Decimal("1100.00")


def test_format_money():
    assert fin.format_money("14693.28", "INR") == "₹14,693.28"
