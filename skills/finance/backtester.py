"""Backtesting: SMA-crossover strategy over an OHLC csv."""

from __future__ import annotations

import csv
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path

from intelligence.finance.backtest import OHLC, backtest, sma_cross
from skills.base import Skill, SkillContext, require_data_dir

_DEFAULT_CAPITAL = Decimal("100000")


def _to_decimal(raw: str, lineno: int, column: str) -> Decimal:
    try:
        return Decimal(raw.replace(",", "").strip())
    except InvalidOperation as exc:
        raise ValueError(f"row {lineno}: invalid {column}: {raw!r}") from exc


def _parse_ohlc_csv(path: Path) -> list[OHLC]:
    try:
        handle = path.open("r", encoding="utf-8-sig", newline="")
    except OSError as exc:
        raise ValueError(f"cannot read csv file: {path}") from exc
    bars: list[OHLC] = []
    with handle:
        reader = csv.DictReader(handle)
        headers = {(h or "").lower() for h in (reader.fieldnames or [])}
        missing = {"date", "open", "high", "low", "close"} - headers
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
            bars.append(
                OHLC(
                    date=raw_date,
                    open=_to_decimal(norm.get("open", ""), lineno, "open"),
                    high=_to_decimal(norm.get("high", ""), lineno, "high"),
                    low=_to_decimal(norm.get("low", ""), lineno, "low"),
                    close=_to_decimal(norm.get("close", ""), lineno, "close"),
                )
            )
    if not bars:
        raise ValueError("csv has no data rows")
    return bars


class BacktesterSkill(Skill):
    """Runs an SMA-crossover backtest over an OHLC csv (pure local math)."""

    name = "backtester"
    description = (
        "Backtests a strategy: 'run <csvpath> [fast] [slow]' reads a "
        "date,open,high,low,close csv, builds SMA-crossover signals, and reports "
        "total return %, max drawdown %, win rate, and trade count on Rs 100000."
    )
    intents = ("backtest.run",)
    required_capabilities = ("skills.execute", "system.read")
    background = True
    local_only = True

    async def handle(self, context: SkillContext) -> str:
        text = context.message.strip()
        if not text.lower().startswith("run "):
            return (
                "backtester usage: 'run <csvpath> [fast] [slow]' "
                "(csv columns: date,open,high,low,close)"
            )
        parts = text[4:].split()
        try:
            fast = int(parts[1]) if len(parts) > 1 else 10
            slow = int(parts[2]) if len(parts) > 2 else 20
        except ValueError as exc:
            return f"backtest failed: windows must be integers ({exc})"
        candidate = Path(parts[0])
        if not candidate.is_absolute():
            candidate = require_data_dir(context) / candidate
        path = candidate.resolve()
        if not path.is_file():
            return f"backtest failed: csv not found: {parts[0]}"
        try:
            bars = _parse_ohlc_csv(path)
            signals = sma_cross([b.close for b in bars], fast, slow)
            result = backtest(bars, signals, _DEFAULT_CAPITAL)
        except ValueError as exc:
            return f"backtest failed: {exc}"
        return (
            f"backtest sma({fast},{slow}) on {path.name} — {len(bars)} bars, "
            f"capital {_DEFAULT_CAPITAL:,.0f}\n"
            f"total return: {result['total_return_pct']}%\n"
            f"max drawdown: {result['max_drawdown_pct']}%\n"
            f"win rate: {result['win_rate']}% over {result['trades']} trades"
        )


SKILLS: list[Skill] = [BacktesterSkill()]
