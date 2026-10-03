"""Price alerts: watch tickers; the background tick notifies on threshold cross."""

from __future__ import annotations

import inspect
import json
import re
import uuid
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import cast

from intelligence.finance.calculations import format_money
from intelligence.finance.portfolio import (
    NotConfiguredError,
    PriceFeedProtocol,
    StubPriceFeed,
)
from skills.base import Skill, SkillContext, require_data_dir
from storage.sqlite_store import SQLiteKVStore

_STORE = "market.db"
_INDEX_KEY = "alerts:index"
_WATCH_RE = re.compile(r"^watch\s+([A-Za-z0-9.\-]+)\s+(above|below)\s+([\d.,]+)\s*$")


@dataclass(frozen=True)
class PriceAlert:
    """A stored watch: ticker, direction, and trigger price."""

    id: str
    ticker: str
    direction: str  # "above" | "below"
    target: Decimal
    created: str


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


def _to_decimal(raw: str) -> Decimal:
    try:
        return Decimal(raw.replace(",", "").strip())
    except InvalidOperation as exc:
        raise ValueError(f"invalid price: {raw!r}") from exc


class PriceAlertsSkill(Skill):
    """Watches tickers and notifies when the price crosses above/below a level."""

    name = "price_alerts"
    description = (
        "Price watches: 'watch <ticker> above|below <price>' stores an alert, "
        "'list' shows active watches; the 5-minute tick fetches prices through "
        "the configured PriceFeedProtocol adapter and notifies on a crossing."
    )
    intents = ("alert.watch", "alert.list")
    required_capabilities = (
        "skills.execute",
        "memory.write",
        "memory.read",
        "network.fetch",
        "notify.send",
    )
    background = True
    local_only = False
    adapter_note = (
        "Live prices come from a PriceFeedProtocol adapter "
        "(intelligence.finance.portfolio). The default StubPriceFeed raises "
        "NotConfiguredError — plug a real feed in by setting "
        "skill.price_feed to your implementation (stdlib urllib, timeout, "
        "at most 3 retries, no hard-coded provider or key)."
    )
    tick_interval_s = 300.0
    price_feed: PriceFeedProtocol = StubPriceFeed()

    async def handle(self, context: SkillContext) -> str:
        text = context.message.strip()
        lowered = text.lower()
        if lowered.startswith("watch"):
            return self._watch(context, text)
        if lowered == "list":
            return self._list(context)
        return await self._tick(context)

    def _store(self, context: SkillContext) -> SQLiteKVStore:
        return SQLiteKVStore(require_data_dir(context) / _STORE)

    def _alerts(self, context: SkillContext) -> list[PriceAlert]:
        kv = self._store(context)
        raw_index = kv.get(_INDEX_KEY)
        ids: list[str] = cast(list[str], json.loads(raw_index)) if raw_index else []
        alerts: list[PriceAlert] = []
        for alert_id in ids:
            raw = kv.get(f"alert:{alert_id}")
            if raw is None:
                continue
            data = cast(dict[str, str], json.loads(raw))
            alerts.append(
                PriceAlert(
                    id=alert_id,
                    ticker=str(data.get("ticker", "")),
                    direction=str(data.get("direction", "above")),
                    target=_to_decimal(str(data.get("target", "0"))),
                    created=str(data.get("created", "")),
                )
            )
        return alerts

    def _save_index(self, context: SkillContext, ids: list[str]) -> None:
        self._store(context).put(_INDEX_KEY, json.dumps(ids))

    def _watch(self, context: SkillContext, text: str) -> str:
        match = _WATCH_RE.match(text)
        if not match:
            return "watch usage: 'watch <ticker> above|below <price>'"
        ticker, direction, raw_target = match.group(1).upper(), match.group(2).lower(), match.group(3)
        try:
            target = _to_decimal(raw_target)
        except ValueError as exc:
            return f"watch failed: {exc}"
        if target <= 0:
            return "watch failed: price must be positive"
        alert = PriceAlert(
            id=uuid.uuid4().hex[:8],
            ticker=ticker,
            direction=direction,
            target=target,
            created=datetime.now().astimezone().isoformat(),
        )
        kv = self._store(context)
        kv.put(
            f"alert:{alert.id}",
            json.dumps(
                {
                    "ticker": alert.ticker,
                    "direction": alert.direction,
                    "target": str(alert.target),
                    "created": alert.created,
                }
            ),
        )
        ids = [a.id for a in self._alerts(context)]
        self._save_index(context, sorted(set(ids)))
        return (
            f"watching {ticker} {direction} {format_money(target)} (id {alert.id})"
        )

    def _list(self, context: SkillContext) -> str:
        alerts = self._alerts(context)
        if not alerts:
            return "no price watches — use 'watch <ticker> above|below <price>'"
        lines = ["price watches:"]
        lines.extend(
            f"  {a.id}: {a.ticker} {a.direction} {format_money(a.target)}" for a in alerts
        )
        return "\n".join(lines)

    async def _tick(self, context: SkillContext) -> str:
        alerts = self._alerts(context)
        if not alerts:
            return "no price watches set"
        tickers = sorted({a.ticker for a in alerts})
        try:
            prices = self.price_feed.get_prices(tickers)
        except NotConfiguredError:
            return (
                "price feed not configured — watches are stored but cannot be "
                "checked. Plug a PriceFeedProtocol adapter into this skill's "
                "price_feed attribute (see the adapter_note)."
            )
        fired: list[PriceAlert] = []
        kv = self._store(context)
        for alert in alerts:
            price = prices.get(alert.ticker)
            if price is None:
                continue
            crossed = (
                price >= alert.target
                if alert.direction == "above"
                else price <= alert.target
            )
            if crossed:
                msg = (
                    f"price alert: {alert.ticker} at {format_money(price)} crossed "
                    f"{alert.direction} {format_money(alert.target)}"
                )
                fired.append(alert)
                kv.delete(f"alert:{alert.id}")
                await _notify(context, msg)
        self._save_index(context, sorted(a.id for a in alerts if a not in fired))
        if not fired:
            return f"checked {len(alerts)} watch(es) — no crossings"
        return "fired: " + "; ".join(
            f"{a.ticker} {a.direction} {format_money(a.target)}" for a in fired
        )


SKILLS: list[Skill] = [PriceAlertsSkill()]
