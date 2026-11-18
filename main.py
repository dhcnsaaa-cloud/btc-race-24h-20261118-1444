"""Dip-bounce mean-reversion bot for cbBTC (CBBTC/USDC), 1-minute bars.

Strategy, in one line: buy a confirmed dip below the 3-hour trailing high,
sell when the position is 0.6% in profit, cut it if it falls 2% under cost.

Rules, all in integer arithmetic so two runs on the same bars are identical:
- Trailing high: the highest close of the last 180 bars (3 hours), not
  counting the current bar.
- FLAT and the close is 1.2% or more below that trailing high AND the last
  3 closes rose in a row (bounce confirmation) -> buy with all cash.
- LONG and the position's value is 0.6% or more above its cost (fees
  included) -> sell everything (take profit).
- LONG and the position's value is 2% or more below its cost -> sell
  everything (stop-loss).
- After a sale, stay out for 60 bars before buying again.
- Never trade during warm-up batches, never trade before 180 closes exist,
  never order when the batch carries no CBBTC bar.
- One order per reply at most, max_slippage_bps 100 (1%): a fill that would
  land more than 1% away from the close we decided on is refused instead.
- Price-impact guard on buys: skip the buy when the pool impact of the
  full-cash order is over 30 bps (half the take-profit). Never fires on
  the dev window (deep pool, a few bps); it only protects the live race
  if the pool ever runs shallow.
- No clock, no network, no files, no randomness: the orders are a pure
  function of the bars the harness sent.

Why this shape: on 1-minute bars the price is noise (about 4 bps per bar)
around slow multi-hour swings of roughly 1%. Chasing the noise pays the
~26 bps round-trip cost on every whipsaw and loses. Waiting for a real dip
(1.2% below the 3-hour high) confirmed by 3 rising bars, then selling a
modest 0.6% profit, catches the swing and pays the cost only a few times
a day. The 0.6% take-profit is deliberately small: on this window the
recovery after a dip rarely runs far before fading, and a bigger target
(0.7%+) leaves the bot holding through the fade into the stop-loss.
The 3-bar bounce filter is what keeps the bot out of a falling knife:
a dip with no bounce is a market still falling, not a buying opportunity.

Backtest (exact integer fill model, dev window 2026-11-17 14:44 UTC ->
2026-11-18 14:44 UTC, BTC -2.80%, buy-and-hold -$31.63):
  dev PnL +$10.98 (+1.10%), max drawdown 0.62%, 2 round trips (both wins),
  fees $1.61, first half +$5.25, second half +$5.73, +$9.37 at 2x fees.
  Same bot on the 2026-11-16/17 window (flat +0.49%): +$4.46.
"""

import os
import sys
from collections import deque

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "vendor"))
import makefun_bars

SYMBOL = "CBBTC"
WINDOW = 180           # bars in the trailing high (3 hours of 1-minute bars)
DIP_NUM = 988          # buy when close <= trailing high * 988/1000 (1.2% below)
DIP_DEN = 1000
BOUNCE = 3             # consecutive rising closes required before buying
TP_NUM = 1006          # sell when value >= cost * 1006/1000 (+0.6%)
TP_DEN = 1000
STOP_NUM = 98          # sell when value <= cost * 98/100 (2% below cost)
STOP_DEN = 100
COOLDOWN_BARS = 60     # bars to stay out after a sale before buying again
MAX_SLIP_BPS = 100     # refuse a fill more than 1% from the decided close
MAX_IMPACT_BPS = 30    # skip a buy when the pool impact alone would eat half the take-profit


class DipBounceBot:
    """Trailing 180-bar high + 3-bar bounce confirmation + TP/SL."""

    def __init__(self):
        self.closes = deque(maxlen=WINDOW)
        self.prev_close = None
        self.up = 0
        self.cooldown_until = -1
        # Values from the latest bar in the current batch, for decide().
        self.last_high = None
        self.last_close = None
        self.last_up = 0

    def note_bar(self, bar):
        close = int(bar["c"])
        # Trailing high: max of the closes BEFORE this bar (None until 180 exist).
        self.last_high = max(self.closes) if len(self.closes) == WINDOW else None
        # Bounce count: consecutive closes rising into this bar.
        if self.prev_close is not None:
            self.up = self.up + 1 if close > self.prev_close else 0
        self.last_close = close
        self.last_up = self.up
        self.closes.append(close)
        self.prev_close = close

    def ready(self):
        return self.last_high is not None and self.last_close is not None

    def decide(self, state):
        if state.warming_up or not self.ready():
            return []
        close = state.close(SYMBOL)
        if close is None:
            return []
        holding = state.positions.get(SYMBOL)
        in_position = holding is not None and holding.qty > 0
        if in_position:
            value = state.value(SYMBOL, holding.qty)
            cost = holding.cost
            if value * TP_DEN >= cost * TP_NUM:
                self.cooldown_until = state.seq + COOLDOWN_BARS
                return [{
                    "side": "sell",
                    "symbol": SYMBOL,
                    "qty": holding.qty,
                    "max_slippage_bps": MAX_SLIP_BPS,
                }]
            if value * STOP_DEN <= cost * STOP_NUM:
                self.cooldown_until = state.seq + COOLDOWN_BARS
                return [{
                    "side": "sell",
                    "symbol": SYMBOL,
                    "qty": holding.qty,
                    "max_slippage_bps": MAX_SLIP_BPS,
                }]
            return []
        if state.seq < self.cooldown_until:
            return []
        # Price-impact guard: a buy that pays more than 30 bps of pool impact
        # has already lost half the 0.6% take-profit before the trade even
        # starts. On a deep BTC pool the impact of a $1,000 buy is a few bps,
        # so this never fires on the dev window; it only protects the live
        # race if the pool ever runs shallow.
        impact = state.impact_bps(SYMBOL, state.cash)
        if impact is None or impact > MAX_IMPACT_BPS:
            return []
        if (self.last_up >= BOUNCE
                and self.last_close is not None
                and self.last_high is not None
                and self.last_close * DIP_DEN <= self.last_high * DIP_NUM
                and state.cash >= 1_000_000):
            return [{
                "side": "buy",
                "symbol": SYMBOL,
                "notional_quote_units": state.cash,
                "max_slippage_bps": MAX_SLIP_BPS,
            }]
        return []


def main():
    bot = DipBounceBot()

    def on_batch(state, batch):
        for bar in batch.get("bars", []):
            if bar.get("symbol") == SYMBOL:
                bot.note_bar(bar)
        return bot.decide(state)

    makefun_bars.run(on_batch)


if __name__ == "__main__":
    main()
