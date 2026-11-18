"""Dip-bounce mean-reversion bot for cbBTC (CBBTC/USDC), 1-minute bars.
Aggressive variant (N60): shorter 1-hour trailing high, shallower dip,
shorter cooldown — catches the early bounces the 3-hour version misses.

Strategy, in one line: buy a confirmed dip below the 1-hour trailing high,
sell when the position is 0.6% in profit, cut it if it falls 2% under cost.

Rules, all in integer arithmetic so two runs on the same bars are identical:
- Trailing high: the highest close of the last 60 bars (1 hour), not
  counting the current bar.
- FLAT and the close is 1.0% or more below that trailing high AND the last
  3 closes rose in a row (bounce confirmation) -> buy with all cash.
- LONG and the position's value is 0.6% or more above its cost (fees
  included) -> sell everything (take profit).
- LONG and the position's value is 2% or more below its cost -> sell
  everything (stop-loss).
- After a sale, stay out for 30 bars before buying again.
- Never trade during warm-up batches, never trade before 60 closes exist,
  never order when the batch carries no CBBTC bar.
- One order per reply at most, max_slippage_bps 100 (1%): a fill that would
  land more than 1% away from the close we decided on is refused instead.
- Price-impact guard on buys: skip the buy when the pool impact of the
  full-cash order is over 30 bps (half the take-profit). Never fires on
  the dev window (deep pool, a few bps); it only protects the live race
  if the pool ever runs shallow.
- No clock, no network, no files, no randomness: the orders are a pure
  function of the bars the harness sent.

Why this shape: the 3-hour version (N180, dip 1.2%, cooldown 60) is
conservative — it waits for a deep dip below a slow-moving high and
catches only 2 bounces on the dev window (+$10.98). A 60-bar trailing
high hugs the falling price much closer, so a 1.0% dip below it fires
earlier, and the 30-bar cooldown lets the bot re-enter sooner. On the
dev window this catches 2 early bounces the slow version misses
(bar 73->81 +$5.80 and bar 111->407 +$6.34) for +$12.13. The trade-off:
in the second half of the dev window the fast high adapts to the drift
so no setup ever fires (h2 $0.00) — the bot is a first-half bot on this
window. It is the aggressive sibling of the conservative entry, not a
replacement: both race, and the aggressive one wins when the live window
has early dips.

Backtest (exact integer fill model, dev window 2026-11-17 14:44 UTC ->
2026-11-18 14:44 UTC, BTC -2.80%, buy-and-hold -$31.63):
  dev PnL +$12.13 (+1.21%), max drawdown 1.00%, 2 round trips (both wins),
  fees $1.61, first half +$12.13, second half $0.00, +$10.52 at 2x fees.
  Same bot on the 2026-11-16/17 window (flat +0.49%): +$9.44.
  Head-to-head vs the conservative N180 across 5 windows (1444, 0603,
  0828, 2314, scratch): N60 wins 4, ties 1, loses 0; aggregate
  -$7.07 vs -$56.98.

Replay verification (replay-driver.py, real main.py over the wire
protocol, exact integer fill model): 1x PnL +$12.13, DD 1.00%, fees
$1.61 — identical to the backtest to the cent. Trades: buy bar 73
$63,870.54 -> sell bar 81 $64,292.18 (+$5.80); buy bar 111 $63,999.24
-> sell bar 407 $64,454.08 (+$6.34). 2x fees: PnL +$10.52, DD 1.08%.
One order was rejected by the harness (slippage/impact guard) and the
bot carried on — the PnL above already counts it.
"""

import os
import sys
from collections import deque

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "vendor"))
import makefun_bars

SYMBOL = "CBBTC"
WINDOW = 60            # bars in the trailing high (1 hour of 1-minute bars)
DIP_NUM = 990          # buy when close <= trailing high * 990/1000 (1.0% below)
DIP_DEN = 1000
BOUNCE = 3             # consecutive rising closes required before buying
TP_NUM = 1006          # sell when value >= cost * 1006/1000 (+0.6%)
TP_DEN = 1000
STOP_NUM = 98          # sell when value <= cost * 98/100 (2% below cost)
STOP_DEN = 100
COOLDOWN_BARS = 30     # bars to stay out after a sale before buying again
MAX_SLIP_BPS = 100     # refuse a fill more than 1% from the decided close
MAX_IMPACT_BPS = 30    # skip a buy when the pool impact alone would eat half the take-profit


class DipBounceBot:
    """Trailing 60-bar high + 3-bar bounce confirmation + TP/SL."""

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
        # Trailing high: max of the closes BEFORE this bar (None until 60 exist).
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
