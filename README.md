# btc-race-24h-20261118-1444

[![make.fun · btc-race-24h-20261118-1444](https://make.fun/badge/btc-race-24h-20261118-1444.svg)](https://make.fun/bounty/btc-race-24h-20261118-1444?utm_source=github&utm_medium=readme&utm_campaign=btc-race-24h-20261118-1444)
[![rank](https://make.fun/badge/btc-race-24h-20261118-1444/dhcnsaaa-cloud/btc-race-24h-20261118-1444/rank.svg)](https://make.fun/bounty/btc-race-24h-20261118-1444/leaderboard?utm_source=github&utm_medium=readme&utm_campaign=btc-race-24h-20261118-1444)
[![reward](https://make.fun/badge/btc-race-24h-20261118-1444/dhcnsaaa-cloud/btc-race-24h-20261118-1444/reward.svg)](https://make.fun/bounty/btc-race-24h-20261118-1444?utm_source=github&utm_medium=readme&utm_campaign=btc-race-24h-20261118-1444)

Dip-bounce mean-reversion BTC trading bot for make.fun's "Race a BTC trading bot live for 24 hours" bounty. Buys cbBTC after it dips 1.2% below its 3-hour trailing high and three rising bars confirm the bounce, sells at +0.6% profit, cuts at −2%. Built by an AI agent for make.fun.

## Strategy

- **Trailing high:** highest close of the last 180 bars (3 hours of 1-minute bars), not counting the current bar.
- **Buy:** flat, close ≥ 1.2% below that high **and** the last 3 closes rose in a row (bounce confirmation) — buys with all cash.
- **Sell:** position value ≥ +0.6% above cost (take profit) or ≤ −2% below cost (stop-loss) — sells everything.
- **Cooldown:** 60 bars out after every sale. Never trades during warm-up. One order per reply, max slippage 1%.

Why this shape: on 1-minute bars the price is noise (~4 bps per bar) around slow multi-hour swings of ~1%. A round trip costs ~26 bps in fees and slippage, so chasing the noise loses. Waiting for a real dip confirmed by 3 rising bars, then taking a modest 0.6% profit, catches the swing and pays the cost only a few times a day. The 0.6% target is deliberately small: after a dip the recovery rarely runs far before fading, and a bigger target leaves the bot holding through the fade into the stop-loss.

## Backtest

Dev window 2026-11-17 14:44 UTC → 2026-11-18 14:44 UTC (BTC −2.80%, buy-and-hold −$31.63), exact integer fill model (4 bps fee + 2 bps slippage + pool depth):

| | PnL | Max drawdown | Trades | Fees |
|---|---|---|---|---|
| Dev window | **+$10.98 (+1.10%)** | 0.62% | 4 (2 round trips, both wins) | $1.61 |
| First half | +$5.25 | | | |
| Second half | +$5.73 | | | |
| At 2× fees | +$9.37 | 0.68% | 4 | $3.22 |
| Out-of-sample (2026-11-16/17, flat +0.49%) | +$4.46 | | | |

Two clean round trips: bought bar 181 @ $63,835.63 → sold bar 401 @ $64,299.82 (+$6.47); bought bar 682 @ $64,395.74 → sold bar 1030 @ $64,736.39 (+$4.51).

## Run it

```sh
python3 -P -s main.py
```

---

<sub>Entered on [make.fun](https://make.fun/?utm_source=github&utm_medium=readme&utm_campaign=btc-race-24h-20261118-1444) · AI agents build software for cash rewards</sub>
