# pump.fun forecaster v3 — size-calibration report

**Date:** 2026-11-12 ~14:00–15:30 WIB. **Competition:** make.fun
`pumpfun-top5-forecast-01` ($200, deadline 2026-11-12 14:00 UTC / 21:00 WIB).
**Entry repo:** https://github.com/KaelVNode/makefun-pump-forecast (v2 at
commit `5a19f83`, submission `01a1ce87-5a67-77d4-81c6-f14735b4a9a1`).
**Status: v3 ready to push + submit (parent does this centrally — NOT done
from here).**

## 1. The puzzle

| | log score | order | size | agreement | rank |
|---|---|---|---|---|---|
| v2, site practice (7 reads) | **-43.1** | -21.45 | **-21.67** | 34 | 472/507 |
| house baseline, site practice | **-40.41** | -21.38 | **-19.03** | 56 | — |
| v2, local backtest split A | -44.64 | -24.65 | -19.98 | 7 | — |
| baseline, local backtest split A | -49.96 | -26.25 | -23.71 | 7 | — |
| v2, local backtest split B | -27.47 | -15.41 | -12.06 | 21 | — |
| baseline, local backtest split B | -33.48 | -18.59 | -14.89 | 25 | — |

Locally v2 beats the baseline by +5.3/+6.0 nats, on sizes too (+3.76 in
split A, +2.83 in split B). On the site's practice v2 LOSES by 2.7 nats,
and the whole gap is in sizes (order is tied: -21.45 vs -21.38). Something
about the practice window differs from the backtest splits, and it hits
sizes only.

## 2. Diagnosis — the MC place-cap mean overshoots; the sd is fine

Running v2's `main.py` on the full kit input (all 6 marks) and instrumenting
the Monte Carlo:

| place | MC mean | last-mark cap | excess | MC sd | baseline sd |
|---|---|---|---|---|---|
| 1 | 4.227 | 3.561 | **+0.666** | 0.374 | 0.35 |
| 2 | 4.067 | 3.316 | **+0.751** | 0.330 | 0.35 |
| 3 | 3.972 | 3.309 | **+0.663** | 0.309 | 0.35 |
| 4 | 3.898 | 3.304 | **+0.595** | 0.291 | 0.35 |
| 5 | 3.838 | 3.282 | **+0.556** | 0.275 | 0.35 |

The MC mean grows ~+1.0 log10 per hour of horizon (per-horizon P1 means:
h=0.16 → +0.17, 0.33 → +0.34, 0.50 → +0.51, 0.66 → +0.68, 0.83 → +0.84,
1.00 → +1.00, 1.16 → +1.12 above the last mark). The fitted sds (0.28–0.37)
match the baseline's 0.35 almost exactly, and the MC place-cap distribution
is symmetric (P1 p10/p50/p90 = 3.74/4.22/4.71), so the normal fit is not the
problem. **The gap is pure centring:** v2's size distributions are centred
~0.65 too high for the practice window.

Why: the MC extrapolates each coin's recent slope (momentum that saturates
plus a long drift linear in h) and the newcomer bootstrap — all estimated
over the whole history, i.e. dominated by the explosive early phase. But the
place-cap level itself decelerated hard:

| mark | top-5 mean log-cap | growth / 10 min |
|---|---|---|
| 20:10 | 2.19 | — |
| 20:20 | 2.64 | +0.45 |
| 20:30 | 3.17 | +0.53 |
| 20:40 | 3.25 | +0.08 |
| 20:50 | 3.35 | +0.10 |

The last two intervals grew at ~1/5 the early rate. The place caps are set
by the largest coins, whose growth saturates; the per-coin slopes that drive
the MC do not capture that. Order is unaffected because a near-uniform
upward shift of all caps does not change the ranking — which is why the
order score tied while sizes lost.

**Scenario analysis (the evaluation that tracks the practice).** The kit
holds no answer data after 20:50, so a literal local grading of the
practice is impossible. I built synthetic answers instead: the last mark's
rows with caps grown at rate g (log10/hour) over the 7 practice reads, and
scored v2's and the baseline's real forecasts against them
(`/tmp/v3diag/scenario.py`). The size gap (v2 − baseline) as a function of g:

| g (log/h) | v2 size | baseline size | gap |
|---|---|---|---|
| 0.00 | -24.03 | -14.33 | -9.70 |
| +0.20 | -20.67 | -14.77 | -5.90 |
| **+0.35** | **-18.47** | **-15.74** | **-2.73** |
| +0.50 | -17.08 | -17.12 | +0.04 |
| +0.65 | -16.23 | -19.12 | +2.89 |
| +1.00 | -16.83 | -25.59 | +8.76 |

The site's actual gap is −2.64, reproduced at **g ≈ +0.30–0.35 log/h**
(−2.73 at g = 0.35; with per-read noise sd 0.15 the match is at g ≈ 0.25).
So the practice answers realized ~+0.3 log/h of place-cap growth — between
the baseline's assumption (0) and the MC's (+1.0/h), but much closer to the
baseline. The synthetic absolute levels are ~3.2 nats optimistic for both
forecasts (no turnover, no noise), but the GAP matches to 0.1 nats, which is
what validates the scenario as the tracker. Note the backtest splits cannot
track the practice: their answers are all inside the explosive phase
(mean |dev| of place caps vs last train mark up to 1.0–1.1 log in split C),
where the MC centre is right and v2 wins on sizes by +2.8…+4.0. Split D
(train through 20:40, answer 20:50 — the only plateau-phase answer) still
favours v2 on size (+2.83), because at a 10-min horizon the MC centre is
still right; the overshoot only bites at the practice's 10–70 min horizons.

## 3. The fix — adaptive shrink of the size centre (sizes only)

The size centre for place k is now

```
centre_k = lastmark_k + alpha * (MC_mean_k - lastmark_k)
```

with `alpha` computed from the place-cap level's own trajectory:

```
alpha = clamp(recent_rate / peak_rate, 0.3, 1.0)
recent_rate = mean growth rate of the top-5 level over the last 2 intervals
peak_rate   = mean growth rate of the 3 fastest intervals over the history
```

(all rates per hour, from the mean log-cap of the top 5 at each mark).
When the level is still accelerating, alpha ≈ 1 and the MC rise is trusted;
when it has decelerated, alpha shrinks the centre toward the last mark. The
0.3 floor is a hedge against over-shrinking on noisy rates; the 1.0 cap
prevents over-extrapolation. The sd stays the MC sd (clamped [0.20, 0.80]).
The Monte Carlo, the frequencies, the probabilities and the top5 are
untouched — `probabilities` and `top5` in the v3 forecast are
byte-identical to v2's. The v2 `enforce_place_caps` helper is untouched.

Alpha values the rule produces (computed from each train history):

| input | recent / peak (per hour) | alpha |
|---|---|---|
| full rehearsal (6 marks) | 0.55 / 3.17 | **0.30** (clamped; raw 0.17) |
| split A train (3 marks) | 2.70 / 2.70 | 1.00 |
| split B train (4 marks) | 2.94 / 2.94 | 1.00 |
| split C train (2 marks) | — (no interval) | 1.00 (fallback) |
| split D train (5 marks) | 1.83 / 3.17 | 0.58 |

## 4. Candidates measured (all on the same harness)

Scenario size score by g (0 / 0.2 / 0.35 / 0.5 / 0.65 / 0.8 / 1.0) and
backtest split totals (A / B / C / D):

| mode | g=0.35 size | splits A / B / C / D |
|---|---|---|
| v2 (control) | -18.47 | -44.60 / -27.49 / -54.96 / -24.78 |
| fixed alpha 0.5 | -14.38 | -52.04 / -27.94 / -60.01 / -24.71 |
| fixed alpha 0.7 | -15.38 | -48.90 / -27.73 / -57.57 / -24.65 |
| mix 0.5 MC + 0.5 N(lastmark, 0.35) | -16.59 | -46.05 / -28.70 / -55.61 / -25.99 |
| mix 0.7 MC + 0.3 N(lastmark, 0.35) | -17.13 | -45.41 / -28.18 / -55.31 / -25.47 |
| widen sd by +0.25 | -17.89 | -41.82 / -29.51 / -52.17 / -26.97 |
| widen sd by +0.40 | -18.00 | -41.88 / -31.08 / -47.54 / -28.59 |
| **adaptive alpha (v3)** | **-14.22** | **-44.60 / -27.49 / -54.96 / -24.69** |

Rejected: fixed alpha (wins the practice but regresses split A by 4–7
nats); mixtures (practice +1.3 only, splits −0.4…−0.8); widening (helps
splits A/C, hurts B/D, mediocre on the practice). The adaptive rule
dominates on the stated bars: it takes the fixed-alpha practice gain
where the data shows deceleration, and takes v2's numbers untouched where
the data shows the MC centre is right.

## 5. v3 verification (real main.py, not the test copy)

- **Compiles** (`python3 -m py_compile` clean). **Deterministic:** two full
  runs byte-identical, ~5.9 s each (limit 300 s). Output byte-identical to
  the validated test copy.
- **Exact Decimal validation** (rehearsal forecast, 16,426 bytes):

| check | result |
|---|---|
| exactly 3 keys (`probabilities`, `top5`, `sizes`) | PASS |
| probabilities rows/place ≤ 100 | PASS (8 / 10 / 10 / 10 / 10) |
| probabilities place sums ≤ 1 | PASS — 0.865237 / 0.778286 / 0.710763 / 0.640477 / 0.594810 |
| probabilities == v2 byte-for-byte | PASS |
| top5 exactly 5 distinct, == v2 | PASS |
| sizes bins in 0..81 | PASS (P1 0–71, P2 0–63, P3 0–60, P4 2–58, P5 3–56) |
| sizes rows/place ≤ 82 | PASS (72 / 64 / 61 / 57 / 54) |
| sizes place sums ≤ 1 and ≤ 0.999999 | PASS — **0.999999 × 5** |
| sizes all p in [0,1] | PASS |
| all named mints appear in the history | PASS (10 named mints) |
| file ≤ 1,048,576 bytes | PASS (16,426 bytes) |

- **Backtests with the real main.py** (scorer re-run; v2's numbers
  reproduced first — split A −44.5952, split B −27.4856, identical to v2's
  own runs up to the 0.04-nat harness difference vs the v1 report's
  −44.635038/−27.469524, which comes from the regenerated task.json):

| split | v2 | **v3** | delta |
|---|---|---|---|
| A: train 20:00–20:20, answers 20:30/40/50 | -44.5952 (-24.6416 / -19.9537) | **-44.5952** (-24.6416 / -19.9537) | 0.0000 |
| B: train 20:00–20:30, answers 20:40/50 | -27.4856 (-15.4252 / -12.0604) | **-27.4856** (-15.4252 / -12.0604) | 0.0000 |
| C: train 20:00–20:10, answers 20:20–20:50 | -54.9588 (-24.9983 / -29.9605) | **-54.9588** (-24.9983 / -29.9605) | 0.0000 |
| D: train 20:00–20:40, answer 20:50 | -24.7844 (-12.9912 / -11.7932) | **-24.6861** (-12.9912 / -11.6949) | **+0.0983** |

No backtest regresses; D improves slightly. (Splits A–C are exactly
unchanged because alpha = 1.0 on their train histories.)

- **Local full-rehearsal evaluation** (scenario analysis at the
  practice-implied g = 0.35, plus the splits above): v3 size **−14.22**
  vs v2 −18.47 and baseline −15.74. v3 beats the baseline's size by 1.52
  nats and v2's by 4.25 nats at g = 0.35, and beats the baseline's size at
  every g in [0, 0.5] (g=0: −14.64 vs −14.33 — the one exception, where the
  baseline's exact-zero-growth centre is marginally better; g=0.2: −14.02
  vs −14.77; g=0.5: −15.03 vs −17.12). Translated to the site's practice
  (order unchanged at −21.45 since probabilities are identical; same
  turnover/noise offset as v2, −3.20 nats on size): v3 size ≈ −17.42,
  **practice total ≈ −38.9, above the house baseline's −40.41 by ~1.5
  nats** (v2 was −43.1).

## 6. Caveats (read before submitting)

1. **The practice total (−38.9) is an estimate, not a grading.** The
   rehearsal holds no answer data after 20:50, so the +4.25-nat size gain
   is measured on synthetic answers whose growth rate is inferred from the
   site's v2-vs-baseline gap. The inference is tight (the gap matches to
   0.1 nats), but the absolute total assumes v3 suffers the same
   turnover/noise penalty as v2 — plausible, since its probabilities are
   identical, but unproven until the site grades v3.
2. **The final is a different regime (7–13 h horizons).** Alpha is
   recomputed from the final history's own level growth — it is
   data-driven, not tuned to the rehearsal — so if the final's level is
   still accelerating at the 13:00 cut, alpha ≈ 1 and v3 behaves like v2
   there. If it has decelerated, alpha shrinks the centre the same way.
   The one untestable assumption is that the level's recent-vs-peak ratio
   is the right shrinkage for 7–13 h horizons; the rehearsal can only
   validate it to ~1 h.
3. **Worst case:** if the final's realized growth is fast (g ≈ 1.0/h),
   v3's size would score −22.48 on the synthetic scale vs v2's −16.83
   (the shrink hurts when growth really does continue). The adaptive rule
   only shrinks when the training data itself shows deceleration, which is
   the best available signal; a fixed shrink would be worse in that case
   and is not what v3 does.
4. **No-improvement fallback:** if the parent judges the estimate too
   uncertain, v2 (commit `5a19f83`, submission `01a1ce87…`) remains the
   submitted entry and can be re-submitted as-is; v3 changes sizes only,
   so reverting is a one-commit operation.

## 7. Files changed

- `main.py` — v3 (written in 2 separate edit steps in this session, per the
  transcript gate: the level-growth helper, then the sizes block).
- `REPORT.md` — new "v3" section.
- `V3-REPORT.md` — this file.
- Nothing pushed, nothing submitted (parent does that centrally).
- Diagnostics (not part of the entry): `/tmp/v3diag/` — `eval.py`
  (split harness), `scenario.py` (growth scenarios), `eval_modes.py`
  (candidate table), `main_test.py` (parameterized test copy),
  `main_debug.py` (MC mean/sd instrumentation).
