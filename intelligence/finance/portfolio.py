"""Portfolio valuation helpers (pure) plus a pluggable price-feed protocol."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol, TypedDict

_CENT = Decimal("0.01")


class NotConfiguredError(RuntimeError):
    """Raised when a stub adapter is used before a real one is plugged in."""


@dataclass(frozen=True)
class Holding:
    """A position: ticker, quantity, and average cost per unit."""

    ticker: str
    qty: Decimal
    avg_cost: Decimal


class PortfolioSummary(TypedDict):
    """Cost, market value, and profit/loss of a set of holdings."""

    total_cost: Decimal
    total_value: Decimal
    pnl: Decimal
    pnl_pct: Decimal


def _require_price(prices: dict[str, Decimal], ticker: str) -> Decimal:
    try:
        return prices[ticker]
    except KeyError as exc:
        raise ValueError(f"missing price for {ticker!r}") from exc


def portfolio_value(
    holdings: Iterable[Holding], prices: dict[str, Decimal]
) -> Decimal:
    """Total market value of ``holdings`` at ``prices``."""
    total = Decimal("0")
    for holding in holdings:
        total += holding.qty * _require_price(prices, holding.ticker)
    return total.quantize(_CENT)


def pnl(
    holdings: Iterable[Holding], prices: dict[str, Decimal]
) -> PortfolioSummary:
    """Cost, value, absolute and percentage P&L for ``holdings``."""
    held = list(holdings)
    cost = sum((h.qty * h.avg_cost for h in held), Decimal("0"))
    value = sum((h.qty * _require_price(prices, h.ticker) for h in held), Decimal("0"))
    profit = value - cost
    pct = (profit / cost * 100).quantize(_CENT) if cost > 0 else Decimal("0")
    return PortfolioSummary(
        total_cost=cost.quantize(_CENT),
        total_value=value.quantize(_CENT),
        pnl=profit.quantize(_CENT),
        pnl_pct=pct,
    )


class PriceFeedProtocol(Protocol):
    """Plug-in point for live market prices (implemented by the user)."""

    def get_prices(self, tickers: list[str]) -> dict[str, Decimal]:
        """Return the latest price per ticker."""
        ...


class StubPriceFeed(PriceFeedProtocol):
    """Not-configured price feed.

    Plug-in: implement :class:`PriceFeedProtocol` and assign the instance to
    the skill's ``price_feed`` attribute, e.g.::

        skill.price_feed = MyQuoteFeed()

    A real implementation should use stdlib ``urllib`` with a timeout and at
    most 3 retries, and must not hard-code any provider or API key. Until one
    is plugged in, every call raises :class:`NotConfiguredError`.
    """

    def get_prices(self, tickers: list[str]) -> dict[str, Decimal]:
        raise NotConfiguredError(
            "no price feed configured: assign a PriceFeedProtocol implementation "
            "to the skill's price_feed attribute (see StubPriceFeed docstring)"
        )
