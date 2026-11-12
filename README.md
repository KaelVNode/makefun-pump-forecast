# pump.fun top-5 forecaster

Entry for make.fun bounty `pumpfun-top5-forecast-01`: forecast the 5 largest
pump.fun coins by market cap at each of seven answer reads.

`main.py` (Python 3.13, standard library only) reads the house's 10-minute
market-cap snapshots from `$MAKEFUN_INPUT_DIR` (else `/input`) and writes
one forecast to `$MAKEFUN_OUTPUT_DIR/forecast.json` (else `/output`).

## Model

- Per-coin log10-cap trajectories. Each coin gets a forecast distribution at
  every answer read: a short-term momentum term that saturates within about
  an hour plus a class long-run drift (most coins fade), with per-coin
  volatility from its own residuals.
- Curve coins graduate to the pool with an empirical rate and jump
  (usually a crash: curve prices stand on virtual reserves).
- Seeded Monte Carlo ranks the candidates at each answer read; place
  probabilities are the frequencies averaged over the seven reads.
- Newcomers (coins born after the history ends) cannot be named. Their
  take-rate per place is fitted from the history itself (mark pairs) and
  left unnamed at every place.
- Sizes: per place, a mixture of the simulated known-coin caps and a
  newcomer cap component, binned over the 82 bins from `task.json`.

Run locally:

```sh
mkdir -p out
MAKEFUN_INPUT_DIR=<kit>/input MAKEFUN_OUTPUT_DIR=out python3 main.py
```
