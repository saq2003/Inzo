"""Portfolio tracking with a pluggable price feed (stub raises honestly)."""

from __future__ import annotations

import json
from decimal import Decimal, InvalidOperation
from typing import cast

from intelligence.finance.calculations import format_money
from intelligence.finance.portfolio import (
    Holding,
    NotConfiguredError,
    PriceFeedProtocol,
    StubPriceFeed,
    pnl,
)
from skills.base import Skill, SkillContext, require_data_dir
from storage.sqlite_store import SQLiteKVStore

_STORE = "market.db"
_INDEX_KEY = "holdings:index"


def _to_decimal(raw: str) -> Decimal:
    try:
        return Decimal(raw.replace(",", "").strip())
    except InvalidOperation as exc:
        raise ValueError(f"invalid number: {raw!r}") from exc


class PortfolioTrackerSkill(Skill):
    """Records holdings and values the portfolio via a pluggable price feed."""

    name = "portfolio_tracker"
    description = (
        "Portfolio ledger: 'add <ticker> <qty> <avg_cost>' records a holding "
        "(repeat adds average down/up), 'value' prices every holding with the "
        "configured PriceFeedProtocol adapter and shows value plus P&L."
    )
    intents = ("portfolio.add", "portfolio.value")
    required_capabilities = ("skills.execute", "memory.write", "memory.read", "network.fetch")
    background = True
    local_only = False
    adapter_note = (
        "Live prices come from a PriceFeedProtocol adapter "
        "(intelligence.finance.portfolio). The default StubPriceFeed raises "
        "NotConfiguredError on every call — plug a real feed in by setting "
        "skill.price_feed to your implementation (stdlib urllib, timeout, "
        "at most 3 retries, no hard-coded provider or key)."
    )
    price_feed: PriceFeedProtocol = StubPriceFeed()

    async def handle(self, context: SkillContext) -> str:
        text = context.message.strip()
        if text.lower().startswith("add "):
            return self._add(context, text[4:])
        return self._value(context)

    def _store(self, context: SkillContext) -> SQLiteKVStore:
        return SQLiteKVStore(require_data_dir(context) / _STORE)

    def _tickers(self, context: SkillContext) -> list[str]:
        raw = self._store(context).get(_INDEX_KEY)
        if raw is None:
            return []
        data = cast(list[str], json.loads(raw))
        return sorted(str(t) for t in data)

    def _holdings(self, context: SkillContext) -> list[Holding]:
        kv = self._store(context)
        holdings: list[Holding] = []
        for ticker in self._tickers(context):
            raw = kv.get(f"holding:{ticker}")
            if raw is None:
                continue
            data = cast(dict[str, str], json.loads(raw))
            holdings.append(
                Holding(
                    ticker=ticker,
                    qty=_to_decimal(str(data.get("qty", "0"))),
                    avg_cost=_to_decimal(str(data.get("avg_cost", "0"))),
                )
            )
        return holdings

    def _add(self, context: SkillContext, arg: str) -> str:
        parts = arg.split()
        if len(parts) != 3:
            return "add usage: 'add <ticker> <qty> <avg_cost>'"
        ticker = parts[0].upper()
        try:
            qty = _to_decimal(parts[1])
            avg_cost = _to_decimal(parts[2])
        except ValueError as exc:
            return f"add failed: {exc}"
        if qty <= 0 or avg_cost < 0:
            return "add failed: qty must be positive and avg_cost >= 0"
        kv = self._store(context)
        existing: Holding | None = None
        for holding in self._holdings(context):
            if holding.ticker == ticker:
                existing = holding
                break
        if existing is None:
            merged = Holding(ticker=ticker, qty=qty, avg_cost=avg_cost)
        else:
            total_qty = existing.qty + qty
            merged_cost = (
                (existing.qty * existing.avg_cost + qty * avg_cost) / total_qty
            ).quantize(Decimal("0.01"))
            merged = Holding(ticker=ticker, qty=total_qty, avg_cost=merged_cost)
        kv.put(
            f"holding:{ticker}",
            json.dumps({"qty": str(merged.qty), "avg_cost": str(merged.avg_cost)}),
        )
        tickers = self._tickers(context)
        if ticker not in tickers:
            kv.put(_INDEX_KEY, json.dumps(sorted([*tickers, ticker])))
        return (
            f"holding: {ticker} qty {merged.qty} @ {format_money(merged.avg_cost)} "
            f"(cost {format_money(merged.qty * merged.avg_cost)})"
        )

    def _value(self, context: SkillContext) -> str:
        holdings = self._holdings(context)
        if not holdings:
            return "no holdings — use 'add <ticker> <qty> <avg_cost>'"
        tickers = sorted({h.ticker for h in holdings})
        try:
            prices = self.price_feed.get_prices(tickers)
        except NotConfiguredError:
            return (
                "price feed not configured — holdings are stored but cannot be priced. "
                "Plug a PriceFeedProtocol adapter into this skill's price_feed "
                "attribute (see the adapter_note)."
            )
        summary = pnl(holdings, prices)
        lines = [
            f"portfolio value: {format_money(summary['total_value'])} "
            f"(cost {format_money(summary['total_cost'])})",
            f"P&L: {format_money(summary['pnl'])} ({summary['pnl_pct']}%)",
        ]
        for holding in holdings:
            price = prices.get(holding.ticker)
            if price is None:
                lines.append(f"  {holding.ticker}: no price")
            else:
                lines.append(
                    f"  {holding.ticker}: {holding.qty} x {format_money(price)} = "
                    f"{format_money(holding.qty * price)}"
                )
        return "\n".join(lines)


SKILLS: list[Skill] = [PortfolioTrackerSkill()]
