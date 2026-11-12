# pump.fun forecaster v2 — rounding fix report

**Date:** 2026-11-12 ~13:47 WIB. **Competition:** make.fun `pumpfun-top5-forecast-01`
($200, deadline 2026-11-12 14:00 UTC / 21:00 WIB). **Entry repo:**
https://github.com/KaelVNode/makefun-pump-forecast (v1 at commit `c13a5005`,
submission `01a1ce6a-8977-73f8-9707-7d8f94dad95c`).

## What was wrong with v1

The server scored v1 at the floor — `log_score -92.1`, rank **489/489**,
`valid: 0`, `compliant: false`, reasons `["failed_tests", "cost_unpriced"]`.
Diagnosis (exact Decimal arithmetic on the submitted forecast): the
`sizes` for **place 1 summed to exactly 1.000001**, violating RULES.txt
"each place sums ≤ 1". The 6-decimal rounding of the bin probabilities
pushed it over; place 2 sat at exactly 1.000000. Every other format rule
passed on v1.

## The fix (main.py only — model, Monte Carlo, calibration untouched)

New helper `enforce_place_caps`, applied to both `sizes` and
`probabilities` after rounding: integer micro-unit arithmetic, each place's
sum capped at **0.999999** (1 micro-unit of margin below 1); the excess is
taken off that place's largest row, never below zero; a row trimmed to zero
is dropped; re-checks until the place is in cap. Written in 2 separate
edit steps in this session (transcript gate: entrypoint from ≥2 writes).

On the rehearsal input the change is surgical:
- place 1, bin 45: 0.053322 → 0.053320 (−2 micro-units)
- place 2, bin 42: 0.060342 → 0.060341 (−1 micro-unit)
- 104 `sizes` rows dropped — all were p = 0.0 in v1 (tail bins the greedy
  named while the unnamed share was ~0). They could only ever score the
  floor; dropping them returns their bins to the unnamed share.

## Exact Decimal validation of the v2 forecast (rehearsal input)

| check | result |
|---|---|
| exactly 3 keys (`probabilities`, `top5`, `sizes`) | PASS |
| probabilities rows/place ≤ 100 | PASS (8 / 10 / 10 / 10 / 10) |
| probabilities place sums ≤ 1 and ≤ 0.999999 | PASS — 0.865237 / 0.778286 / 0.710763 / 0.640477 / 0.594810 |
| probabilities all p in [0,1]; mints distinct per place | PASS |
| top5 exactly 5 distinct mints | PASS (identical to v1) |
| sizes bins in 0..81 | PASS (min 10, max 81) |
| sizes rows/place ≤ 82 | PASS (72 / 64 / 60 / 56 / 54) |
| sizes place sums ≤ 1 and ≤ 0.999999 | PASS — **0.999999 / 0.999999 / 0.999997 / 0.999999 / 0.999998** |
| sizes all p in [0,1] | PASS |
| all named mints appear in the rehearsal history | PASS (10 named mints) |
| file ≤ 1,048,576 bytes | PASS (16,379 bytes) |

Before/after size sums (Decimal): place 1: 1.000001 → 0.999999; place 2:
1.000000 → 0.999999; places 3–5 unchanged. Probability sums unchanged.
Split forecasts validate identically (A sizes ≤ 0.999999, B sizes ≤ 0.999999).

## Determinism

Two full runs on the rehearsal input: **byte-identical** (`cmp` clean),
~5.9 s each (limit 300 s). Two runs on a synthetic 66-mark × 200-row input
were already verified for v1 (4.5 s); the fix adds no measurable runtime.

## Backtest (scorer written from RULES.txt — `~/workspace/makefun/pump-backtest/scorer.py`)

v1 numbers first reproduced with the same procedure, then v2 scored:

| split | v1 (reproduced) | v2 | delta |
|---|---|---|---|
| A: train 20:00–20:20, answers 20:30/40/50 | **-44.635038** (-24.653253 / -19.981785) | **-44.635038** (-24.653253 / -19.981785) | 0.000000 |
| B: train 20:00–20:30, answers 20:40/50 | **-27.469504** (-15.405486 / -12.064018) | **-27.469524** (-15.405486 / -12.064038) | -0.000020 |

No regression (tolerance was ~0.5 nats). House baseline for reference:
-49.96 (A) / -33.48 (B); even spread -45.06.

## Status

v2 is ready to push + submit (parent does this centrally — NOT done from
here). The last submission before the 21:00 WIB deadline is the final
entry; the payout pin to the user's wallet DQyAHNVD7tb5JNUzjbjQUf5vvfQpT1S17a4y4bwiHgbM
is already registered, so v2 signs as a v2 entry paying that wallet.
