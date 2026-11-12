# pump.fun top-5 forecaster — entry report

Bounty: make.fun `pumpfun-top5-forecast-01` ($200, deadline 2026-11-12 14:00 UTC /
21:00 WIB). Entry repo: https://github.com/KaelVNode/makefun-pump-forecast
(public, created after the competition opened). Files: `main.py`, `LICENSE`
(MIT), `README.md`, `.makefun/owner.json` (claim file, wallet
`CTqrxd2y5BnSWukjaYU7BtSg8o1f78BQNR4wNZUDRGg1`).

**Status: submittable v1.** Built in this session (started after the opening),
`main.py` written in several separate write/edit steps. Do NOT push/submit
from here — the parent pushes and submits centrally. Note the payout
pinning: the user will pin payouts to his own Binance Agentic Wallet
**before** the first submission (a pin set after signing does not move that
entry's reward).

## Model (`main.py`, Python 3.13, stdlib only, deterministic seed 20261112)

- Per-coin log10-cap trajectories from the history. Forecast distribution
  per answer read: a short-term momentum term (own recent slope, shrunk
  toward the class drift) that saturates within ~45 min, plus a long-run
  drift blending the coin's own trend with its class drift. Volatility from
  the coin's own step-to-step changes (steady growers get tight
  distributions); fallback is a robust class MAD, not the cross-sectional
  sd (that sd inflated the max-of-many-draws and put place-1 caps at
  ~17,000 SOL on the rehearsal).
- Curve coins graduate with an empirical rate and jump (usually a crash:
  curve prices stand on virtual reserves). Migrating coins count as pool.
- **Newcomers dominate.** The Monte Carlo merges the known candidates'
  simulated caps with a bootstrapped top-5 of young coins (per rank, the
  r-th largest cap among coins under an hour old at recent marks, scaled by
  the recent growth of young top caps). Newcomers displace known coins and
  set the place sizes, the way they do in the history. No separate
  newcomer share parameter — the unnamed mass at a place is exactly the
  share the simulation gives newcomers there.
- Seeded Monte Carlo (3,000 paths × 7 reads) ranks the merged list;
  place probabilities are frequencies averaged over the reads. Sizes come
  from the simulated place caps (newcomers included), binned over the 82
  bins from `task.json`. Rows are chosen greedily: a row is named only
  while its probability beats the unnamed share it would otherwise get.
- All times/reads come from `task.json`, never hardcoded.

## Backtest (rehearsal, scorer written from RULES.txt — `~/workspace/makefun/pump-backtest/scorer.py`)

Forecast from the first 3 marks, scored on the later marks as
pseudo-answer reads; same ground for the house baseline (`starter/main.ts`).

| split | mine (order / size) | baseline (order / size) | gain |
|---|---|---|---|
| A: train 20:00–20:20, answers 20:30/40/50 | **-44.64** (-24.65 / -19.98) | -49.96 (-26.25 / -23.71) | **+5.32** |
| B: train 20:00–20:30, answers 20:40/50 | **-27.47** (-15.41 / -12.06) | -33.48 (-18.59 / -14.89) | **+6.01** |

Even spread scores -45.06. Split A is a worst case (20 min of history in a
brand-new cohort: 3–4 of 5 top-5 places at every answer read are coins the
history never saw). The final's 66-mark history is a much richer regime;
the model re-calibrates everything from that history.

## Sanity checks (full rehearsal input, all 6 marks)

- Deterministic: two runs byte-identical. Runtime ~5–12 s on the
  rehearsal; 4.5 s on a synthetic 66-mark × 200-row input (well inside the
  300 s limit). Forecast 20,030 bytes (limit 1,048,576).
- Top-5 sanity vs the published 22:00 answer top-5 (Max, MIHAO VI, Google,
  NIHAONOON, HAMSTER): MIHAO VI is #3 in my top5; Google is named at all
  five places. Max / NIHAONOON / HAMSTER were born after the history ended
  (20:50), so no forecast can name them — correctly absent.

## Transcript gate

`bundle --dry-run` finds this session:
`sessions/muse-app/18aba070-bd1f-495d-9e63-21ed9e483cc1.jsonl` (39 turns,
140 lines kept), plus the parent session. The gate's thresholds
(≥30% reproduced lines, ≥5 assistant turns, ≥2 file writes of the
entrypoint) are met by construction. Run the real `bundle` + `check` before
submitting.

## What score to expect

No local grader exists; the server grades. The house baseline scored
-40.408345 on the practice (7 reads, 21:00–22:00). My backtest beats it by
5–6 nats on the rehearsal's short-horizon reads, mostly on sizes (the
baseline centers sizes on stale last-mark caps) and on the unnamed share.
The other bar is the house AI model forecast (one-shot, latest 12 marks'
top 30) — unobservable. The main risk is newcomer calibration at the
final's 7–13 h horizons: if newcomers take even more places than modeled,
the unnamed share is too small; if the established 13:00 top coins persist,
it is too big. The model reads all of this from the final history itself.
