"""SMA-crossover signals and a tiny long-only backtester (pure, deterministic)."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import TypedDict

_CENT = Decimal("0.01")


@dataclass(frozen=True)
class OHLC:
    """One price bar: ISO date plus open/high/low/close."""

    date: str
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal


class BacktestResult(TypedDict):
    """Summary metrics of a backtest run."""

    total_return_pct: Decimal
    max_drawdown_pct: Decimal
    win_rate: Decimal
    trades: int


def _sma(values: list[Decimal], window: int, index: int) -> Decimal:
    return sum(values[index - window + 1 : index + 1], Decimal("0")) / window


def sma_cross(prices: list[Decimal], fast: int, slow: int) -> list[int]:
    """SMA crossover signals: 1 = buy, -1 = sell, 0 = hold.

    A buy fires when the fast SMA crosses above the slow SMA, a sell when it
    crosses below. The first bar where both SMAs exist seeds the signal from
    their relative position.
    """
    if fast < 1 or slow < 1:
        raise ValueError("windows must be >= 1")
    if fast >= slow:
        raise ValueError("fast window must be smaller than slow window")
    if len(prices) < slow:
        raise ValueError("need at least `slow` prices")
    signals = [0] * len(prices)
    for i in range(slow - 1, len(prices)):
        fast_now = _sma(prices, fast, i)
        slow_now = _sma(prices, slow, i)
        if i == slow - 1:
            if fast_now > slow_now:
                signals[i] = 1
            elif fast_now < slow_now:
                signals[i] = -1
        else:
            fast_prev = _sma(prices, fast, i - 1)
            slow_prev = _sma(prices, slow, i - 1)
            if fast_prev <= slow_prev and fast_now > slow_now:
                signals[i] = 1
            elif fast_prev >= slow_prev and fast_now < slow_now:
                signals[i] = -1
    return signals


def backtest(
    ohlc: list[OHLC], signals: list[int], capital: Decimal
) -> BacktestResult:
    """Long-only simulation: 1 buys with all cash at the close, -1 exits.

    Tracks equity bar-by-bar for max drawdown; win rate counts closed trades
    that exited above their entry price. Any open position is marked to the
    final close for the return figure.
    """
    if capital <= 0:
        raise ValueError("capital must be positive")
    if not ohlc:
        raise ValueError("ohlc must not be empty")
    if len(ohlc) != len(signals):
        raise ValueError("ohlc and signals must have equal length")
    cash = capital
    position = Decimal("0")
    entry = Decimal("0")
    peak = capital
    max_drawdown = Decimal("0")
    trades = 0
    wins = 0
    for bar, signal in zip(ohlc, signals, strict=True):
        price = bar.close
        if signal == 1 and position == 0 and cash > 0:
            position = cash / price
            entry = price
            cash = Decimal("0")
        elif signal == -1 and position > 0:
            cash = position * price
            trades += 1
            if price > entry:
                wins += 1
            position = Decimal("0")
        equity = cash + position * price
        peak = max(peak, equity)
        if peak > 0:
            drawdown = (peak - equity) / peak * 100
            max_drawdown = max(max_drawdown, drawdown)
    final_equity = cash + position * ohlc[-1].close
    total_return = (final_equity - capital) / capital * 100
    win_rate = (Decimal(wins) / Decimal(trades) * 100) if trades else Decimal("0")
    return BacktestResult(
        total_return_pct=total_return.quantize(_CENT),
        max_drawdown_pct=max_drawdown.quantize(_CENT),
        win_rate=win_rate.quantize(_CENT),
        trades=trades,
    )
