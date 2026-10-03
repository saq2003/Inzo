"""Deterministic finance engine (Finance Requirement).

The language model interprets and explains; **Python performs every
calculation** here, using ``Decimal`` for money math. No network, no keys.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation, getcontext

getcontext().prec = 28

_TWO_PLACES = Decimal("0.01")


def _d(value: object) -> Decimal:
    """Coerce to Decimal, raising ValueError on bad input."""
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ValueError(f"invalid numeric value: {value!r}") from exc


def _money(value: Decimal) -> Decimal:
    return value.quantize(_TWO_PLACES)


def compound_growth(
    principal: Decimal | float | str,
    annual_rate_pct: Decimal | float | str,
    years: Decimal | float | str,
    compounds_per_year: int = 1,
) -> Decimal:
    """Future value with compound interest: A = P(1 + r/n)^(nt)."""
    p, r, t = _d(principal), _d(annual_rate_pct) / 100, _d(years)
    if p < 0 or t < 0 or compounds_per_year < 1:
        raise ValueError("principal/years must be >= 0 and compounds_per_year >= 1")
    n = Decimal(compounds_per_year)
    return _money(p * (1 + r / n) ** (n * t))


def loan_emi(
    principal: Decimal | float | str,
    annual_rate_pct: Decimal | float | str,
    months: int,
) -> Decimal:
    """Equated monthly instalment: EMI = P*r*(1+r)^n / ((1+r)^n - 1)."""
    p, annual = _d(principal), _d(annual_rate_pct)
    if p <= 0 or months <= 0:
        raise ValueError("principal and months must be positive")
    r = annual / 1200  # monthly rate as a fraction
    if r == 0:
        return _money(p / months)
    factor = (1 + r) ** months
    return _money(p * r * factor / (factor - 1))


def budget_summary(
    income: Decimal | float | str, expenses: dict[str, Decimal | float | str]
) -> dict[str, Decimal]:
    """Totals, remaining cash, and savings rate for one period."""
    inc = _d(income)
    if inc < 0:
        raise ValueError("income must be >= 0")
    line_items = {name: _money(_d(amount)) for name, amount in expenses.items()}
    if any(v < 0 for v in line_items.values()):
        raise ValueError("expense amounts must be >= 0")
    total = sum(line_items.values(), Decimal("0"))
    remaining = inc - total
    savings_rate = (remaining / inc * 100) if inc > 0 else Decimal("0")
    return {
        "income": _money(inc),
        "total_expenses": _money(total),
        "remaining": _money(remaining),
        "savings_rate_pct": savings_rate.quantize(_TWO_PLACES),
        **{f"expense:{k}": v for k, v in line_items.items()},
    }


def portfolio_value(holdings: list[dict[str, object]]) -> dict[str, object]:
    """Value a portfolio: holdings of {symbol, quantity, price}."""
    total = Decimal("0")
    breakdown: list[dict[str, object]] = []
    for holding in holdings:
        symbol = str(holding.get("symbol", "?"))
        qty = _d(holding.get("quantity", 0))
        price = _d(holding.get("price", 0))
        if qty < 0 or price < 0:
            raise ValueError("quantity and price must be >= 0")
        value = _money(qty * price)
        total += value
        breakdown.append({"symbol": symbol, "value": value})
    return {"total": _money(total), "holdings": breakdown}


def net_cash_flow(inflows: list[object], outflows: list[object]) -> Decimal:
    """Net cash flow = sum(inflows) - sum(outflows)."""
    return _money(sum((_d(v) for v in inflows), Decimal("0")) - sum((_d(v) for v in outflows), Decimal("0")))


def percent_change(old: Decimal | float | str, new: Decimal | float | str) -> Decimal:
    """Percentage change from ``old`` to ``new``."""
    o, n = _d(old), _d(new)
    if o == 0:
        raise ValueError("old value must be non-zero for percent change")
    return ((n - o) / abs(o) * 100).quantize(_TWO_PLACES)


def xirr(
    cashflows: list[tuple[date, Decimal | float | str]],
    guess: Decimal | float | str = "0.1",
    max_iter: int = 100,
    tol: Decimal | float | str = "1e-9",
) -> Decimal:
    """Extended internal rate of return via Newton's method (deterministic).

    ``cashflows``: (date, amount) with at least one negative and one positive.
    Returns the annualized rate as a Decimal fraction (0.12 = 12%).
    """
    flows = [(d, _d(a)) for d, a in cashflows]
    if len(flows) < 2:
        raise ValueError("xirr needs at least two cash flows")
    amounts = [a for _, a in flows]
    if not (any(a < 0 for a in amounts) and any(a > 0 for a in amounts)):
        raise ValueError("xirr needs at least one inflow and one outflow")
    t0 = min(d for d, _ in flows)

    def npv(rate: Decimal) -> Decimal:
        total = Decimal("0")
        for d, amount in flows:
            years = Decimal((d - t0).days) / Decimal("365")
            total += amount / (1 + rate) ** years
        return total

    rate = _d(guess)
    tolerance = _d(tol)
    for _ in range(max_iter):
        value = npv(rate)
        step = Decimal("1e-6")
        derivative = (npv(rate + step) - value) / step
        if derivative == 0:
            raise ValueError("xirr failed to converge (zero derivative)")
        new_rate = rate - value / derivative
        if abs(new_rate - rate) < tolerance:
            return new_rate
        rate = new_rate
    raise ValueError("xirr failed to converge within max_iter")


def scenario_analysis(
    base: dict[str, Decimal | float | str], shocks_pct: dict[str, Decimal | float | str]
) -> dict[str, Decimal]:
    """Apply percentage shocks to base values: shocked = base * (1 + pct/100)."""
    out: dict[str, Decimal] = {}
    for key, value in base.items():
        shock = _d(shocks_pct.get(key, 0)) / 100
        out[key] = _money(_d(value) * (1 + shock))
    return out


def format_money(amount: Decimal | float | str, currency: str = "INR") -> str:
    """Format a money amount for display (presentation only, not math)."""
    symbols = {"INR": "₹", "USD": "$", "EUR": "€", "GBP": "£"}
    symbol = symbols.get(currency.upper(), currency.upper() + " ")
    return f"{symbol}{_money(_d(amount)):,}"
