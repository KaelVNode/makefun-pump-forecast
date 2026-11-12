#!/usr/bin/env python3
"""Forecast the 5 largest pump.fun coins by market cap at the answer reads.

Reads $MAKEFUN_INPUT_DIR (else /input): task.json + history.ndjson (10-minute
market-cap snapshots of every pump.fun coin launched since the opening).
Writes $MAKEFUN_OUTPUT_DIR/forecast.json (else /output/forecast.json).

Model (all parameters read from task.json / estimated from the history):
  * Per-coin log10-cap trajectories.  Each coin gets a forecast distribution
    at every answer read: a short-term momentum term that saturates within
    about an hour (young pool coins that are steadily growing keep growing
    briefly, then plateau) plus a long-run drift that blends the coin's own
    trend with its class drift.  Volatility comes from the coin's own
    step-to-step changes when it has enough marks, else its class.
  * Curve coins graduate to the pool with an empirical rate and an
    empirical graduation jump (usually a crash: the curve price stands on
    virtual reserves).  Migrating coins are treated as pool coins.
  * Newcomers dominate: coins born after the history ends take most top-5
    places, and their caps are what set the place sizes.  The Monte Carlo
    merges the known candidates' simulated caps with a bootstrapped
    top-5 of young coins (per rank, the r-th largest cap among coins under
    an hour old at recent marks, scaled by the recent growth of young top
    caps), so newcomers displace known coins and set place sizes the way
    they do in the history.
  * Seeded Monte Carlo ranks the merged list at each answer read; place
    probabilities are the frequencies averaged over the seven reads, and
    the unnamed share at a place is exactly the share newcomers take there.
  * Sizes: per place, the distribution of the simulated place cap (which
    already includes newcomers), binned over task.json's 82 bins.  Rows are
    chosen greedily: a row is named only when its probability beats the
    unnamed share it would otherwise receive.
Standard library only, deterministic (fixed seed), no network.
"""
import json
import math
import os
import random
from datetime import datetime

INPUT_DIR = os.environ.get("MAKEFUN_INPUT_DIR", "/input")
OUTPUT_DIR = os.environ.get("MAKEFUN_OUTPUT_DIR", "/output")
SEED = 20261112
N_PATHS = 3000
MAX_CANDIDATES = 100
COMMON_SHOCK_SD = 0.08
YOUNG_AGE_H = 1.0
YOUNG_MARKS = 12


def parse_time(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def logcap_sol(lamports):
    return math.log10(int(lamports)) - 9.0


def erfc(x):
    z = abs(x)
    t = 1.0 / (1.0 + 0.5 * z)
    r = t * math.exp(-z * z - 1.26551223 + t * (1.00002368 + t * (0.37409196 + t * (0.09678418 + t * (-0.18628806 + t * (0.27886807 + t * (-1.13520398 + t * (1.48851587 + t * (-0.82215223 + t * 0.17087277)))))))))
    return r if x >= 0 else 2.0 - r


def norm_cdf(x, mean, sd):
    if sd <= 0:
        return 1.0 if x >= mean else 0.0
    return 0.5 * erfc(-(x - mean) / (sd * math.sqrt(2.0)))


def mean(xs):
    return sum(xs) / len(xs) if xs else 0.0


def stdev(xs):
    if len(xs) < 2:
        return 0.0
    m = mean(xs)
    return math.sqrt(sum((x - m) ** 2 for x in xs) / (len(xs) - 1))


def clamp(x, lo, hi):
    return lo if x < lo else hi if x > hi else x


def age_bucket(age_h):
    if age_h < 0.5:
        return 0
    if age_h < 2.0:
        return 1
    if age_h < 6.0:
        return 2
    return 3


def load_input():
    with open(os.path.join(INPUT_DIR, "task.json")) as f:
        task = json.load(f)
    marks = []
    with open(os.path.join(INPUT_DIR, "history.ndjson")) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            m = json.loads(line)
            if m.get("ok") and isinstance(m.get("rows"), list):
                marks.append(m)
    marks.sort(key=lambda m: m["at"])
    return task, marks


def main():
    task, marks = load_input()
    places = int(task.get("places", 5))
    edges = [float(e) for e in task["size"]["edges"]]
    nbins = len(edges) + 1
    reads = [parse_time(r) for r in task["reads"]]
    cut = parse_time(marks[-1]["at"]) if marks else parse_time(task["history_until"])
    horizons = [max(0.0, (r - cut).total_seconds() / 3600.0) for r in reads]

    traj = {}
    created = {}
    for m in marks:
        t = parse_time(m["at"])
        for r in m["rows"]:
            mint = r["mint"]
            created[mint] = parse_time(r["created_at"])
            traj.setdefault(mint, []).append(
                (t, logcap_sol(r["market_cap_lamports"]), r["venue"],
                 bool(r.get("complete")), bool(r.get("mayhem"))))
    for mint in traj:
        traj[mint].sort(key=lambda x: x[0])

    last_mark = marks[-1] if marks else None
    last_rows = sorted(last_mark["rows"], key=lambda r: r["rank"]) if last_mark else []
    if len(last_rows) < places:
        raise SystemExit("the last mark ranks fewer coins than the places")

    # ---- top-5 level growth (v3: adaptive size shrink) ----
    # Mean log-cap of the top 5 at each mark with rows; per-interval growth
    # rates (per hour).  adaptive_alpha() is the ratio of the RECENT rate
    # (mean of the last 2 intervals) to the PEAK rate (mean of the 3 fastest
    # intervals), clamped to [0.3, 1.0].  It measures whether the place-cap
    # level is still accelerating (ratio ~1: trust the Monte Carlo's
    # predicted rise) or has decelerated (ratio << 1: shrink it toward the
    # last mark).  See the sizes block for why this exists.
    _levels = []
    for _m in marks:
        _rr = sorted(_m["rows"], key=lambda r: r["rank"])[:places] if _m.get("rows") else []
        if len(_rr) >= places:
            _levels.append((parse_time(_m["at"]),
                            mean([logcap_sol(r["market_cap_lamports"]) for r in _rr])))
    _rates = []
    for _i in range(1, len(_levels)):
        _dt = (_levels[_i][0] - _levels[_i - 1][0]).total_seconds() / 3600.0
        if _dt > 0:
            _rates.append((_levels[_i][1] - _levels[_i - 1][1]) / _dt)

    def adaptive_alpha():
        if len(_rates) < 1:
            return 1.0
        recent = mean(_rates[-2:])
        peak = mean(sorted(_rates, reverse=True)[:3])
        if peak <= 0:
            return 1.0
        return clamp(recent / peak, 0.3, 1.0)

    # ---- class statistics from mark pairs (adjacent marks only) ----
    # Per-mark dicts so mint lookups are O(1): the final has 66 marks and
    # a linear scan per lookup would not fit the 300 s budget.
    mark_rows = [{r["mint"]: r for r in m["rows"]} for m in marks]
    drift_samples = {}
    vol_samples = {}
    mad_samples = {}
    long_drift_samples = {}
    grad_jumps = []
    grad_events = 0
    grad_exposure_h = 0.0
    for i in range(len(marks)):
        ti = parse_time(marks[i]["at"])
        rows_i = mark_rows[i]
        for j in range(i + 1, len(marks)):
            tj = parse_time(marks[j]["at"])
            dt_h = (tj - ti).total_seconds() / 3600.0
            if dt_h <= 0:
                continue
            rows_j = mark_rows[j]
            for mint, ri in rows_i.items():
                rj = rows_j.get(mint)
                if rj is None:
                    continue
                d = logcap_sol(rj["market_cap_lamports"]) - logcap_sol(ri["market_cap_lamports"])
                age = (ti - parse_time(ri["created_at"])).total_seconds() / 3600.0
                key = (ri["venue"], age_bucket(max(0.0, age)))
                if dt_h <= 0.5:
                    drift_samples.setdefault(key, []).append(d / dt_h)
                    vol_samples.setdefault(key, []).append(d / math.sqrt(dt_h))
                    mad_samples.setdefault(key, []).append(abs(d))
                if dt_h >= 1.0:
                    long_drift_samples.setdefault(key, []).append(d / dt_h)
                if ri["venue"] == "curve" and rj["venue"] == "pool":
                    grad_jumps.append(d)
            if dt_h <= 0.5:
                for mint, ri in rows_i.items():
                    if ri["venue"] == "curve":
                        grad_exposure_h += dt_h
                        if rows_j.get(mint, {}).get("venue") == "pool":
                            grad_events += 1

    def class_stat(samples, key, default):
        xs = samples.get(key) or []
        if len(xs) >= 8:
            return mean(xs)
        venue_xs = [x for (v, _b), ys in samples.items() if v == key[0] for x in ys]
        if len(venue_xs) >= 8:
            return mean(venue_xs)
        all_xs = [x for ys in samples.values() for x in ys]
        if len(all_xs) >= 8:
            return mean(all_xs)
        return default

    def class_sd(samples, key, default):
        xs = samples.get(key) or []
        if len(xs) >= 8:
            return max(0.05, stdev(xs))
        venue_xs = [x for (v, _b), ys in samples.items() if v == key[0] for x in ys]
        if len(venue_xs) >= 8:
            return max(0.05, stdev(venue_xs))
        all_xs = [x for ys in samples.values() for x in ys]
        if len(all_xs) >= 8:
            return max(0.05, stdev(all_xs))
        return default

    def class_mad_sigma(key, default):
        # Robust per-step volatility: median |change| / 0.6745, per sqrt-hour.
        # The plain sd is inflated by the cross-section (coins moving in
        # opposite directions); the median absolute change is what a single
        # coin's next step typically looks like.
        xs = mad_samples.get(key) or []
        if len(xs) >= 8:
            s = sorted(xs)
            med = s[len(s) // 2]
            return clamp(med / 0.6745 / math.sqrt(1.0 / 6.0), 0.08, 0.40)
        venue_xs = [x for (v, _b), ys in mad_samples.items() if v == key[0] for x in ys]
        if len(venue_xs) >= 8:
            s = sorted(venue_xs)
            med = s[len(s) // 2]
            return clamp(med / 0.6745 / math.sqrt(1.0 / 6.0), 0.08, 0.40)
        all_xs = [x for ys in mad_samples.values() for x in ys]
        if len(all_xs) >= 8:
            s = sorted(all_xs)
            med = s[len(s) // 2]
            return clamp(med / 0.6745 / math.sqrt(1.0 / 6.0), 0.08, 0.40)
        return default

    grad_rate = (grad_events / grad_exposure_h) if grad_exposure_h > 0 else 0.10
    grad_rate = clamp(grad_rate, 0.02, 0.60)
    jump_mean = mean(grad_jumps) if len(grad_jumps) >= 3 else -0.30
    jump_sd = clamp(stdev(grad_jumps), 0.25, 0.80) if len(grad_jumps) >= 3 else 0.55

    # ---- young-coin top-5 bootstrap (the newcomer proxy) ----
    # Per rank, the r-th largest cap among coins under an hour old at each
    # recent mark.  A single mark's young top-5 is steep (its #3-5 are much
    # smaller than its #1), but the top-5 at an answer read is flat: five
    # different explosive coins.  Drawing each rank from its own marginal
    # across marks, then sorting, gives that flat shape.
    young_by_rank = [[] for _ in range(5)]
    for m in marks[-YOUNG_MARKS:]:
        t = parse_time(m["at"])
        young = []
        for r in m["rows"]:
            age = (t - parse_time(r["created_at"])).total_seconds() / 3600.0
            if 0.0 <= age <= YOUNG_AGE_H:
                young.append(logcap_sol(r["market_cap_lamports"]))
        young.sort(reverse=True)
        for r in range(min(5, len(young))):
            young_by_rank[r].append(young[r])
    # growth rate of the young #1 cap over recent marks (per hour, clamped)
    young_growth = 0.0
    g_pts = []
    for m in marks[-6:]:
        t = parse_time(m["at"])
        caps = []
        for r in m["rows"]:
            age = (t - parse_time(r["created_at"])).total_seconds() / 3600.0
            if 0.0 <= age <= YOUNG_AGE_H:
                caps.append(logcap_sol(r["market_cap_lamports"]))
        if caps:
            g_pts.append((t, max(caps)))
    if len(g_pts) >= 2:
        t_ref = g_pts[-1][0]
        xs = [(p[0] - t_ref).total_seconds() / 3600.0 for p in g_pts]
        ys = [p[1] for p in g_pts]
        mx = mean(xs)
        my = mean(ys)
        den = sum((x - mx) ** 2 for x in xs)
        if den > 1e-9:
            young_growth = clamp(
                sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / den, -0.5, 1.5)

    # ---- per-coin forecast parameters ----
    candidates = []
    for r in last_rows:
        mint = r["mint"]
        y0 = logcap_sol(r["market_cap_lamports"])
        venue = r["venue"]
        complete = bool(r.get("complete"))
        obs = traj[mint]
        age_h = max(0.0, (cut - created[mint]).total_seconds() / 3600.0)
        key = (venue, age_bucket(age_h))
        drift_c = class_stat(drift_samples, key, -0.05)
        long_c = class_stat(long_drift_samples, key, drift_c * 0.3)
        vol_c = class_sd(vol_samples, key, 0.45)
        # recent slope: weighted regression on last up to 6 observations
        pts = obs[-6:]
        slope = drift_c
        if len(pts) >= 2:
            t_ref = pts[-1][0]
            xs = [(p[0] - t_ref).total_seconds() / 3600.0 for p in pts]
            ys = [p[1] for p in pts]
            w = [1.0 + 0.5 * k for k in range(len(pts))]
            sw = sum(w)
            mx = sum(wi * xi for wi, xi in zip(w, xs)) / sw
            my = sum(wi * yi for wi, yi in zip(w, ys)) / sw
            den = sum(wi * (xi - mx) ** 2 for wi, xi in zip(w, xs))
            if den > 1e-9:
                raw = sum(wi * (xi - mx) * (yi - my) for wi, xi, yi in zip(w, xs, ys)) / den
                raw = clamp(raw, -2.0, 2.0)
                n_int = len(pts) - 1
                slope = (n_int * raw + 1.0 * drift_c) / (n_int + 1.0)
        # per-coin step volatility from consecutive differences; the
        # steady growers that matter have small own-volatility, while the
        # class sd is inflated by the cross-section.  Fall back to the
        # robust class MAD when the coin has too few observations.
        diffs = [pts[k + 1][1] - pts[k][1] for k in range(len(pts) - 1)]
        dt_step = 1.0 / 6.0
        if len(diffs) >= 2:
            step_sd = stdev(diffs)
            sigma_sqrt_h = step_sd / math.sqrt(dt_step) if step_sd > 0 else class_mad_sigma(key, 0.20)
        else:
            sigma_sqrt_h = class_mad_sigma(key, 0.20)
        sigma_sqrt_h = clamp(sigma_sqrt_h, 0.08, 0.40)
        long_i = clamp(0.3 * slope + 0.7 * long_c, -0.5, 0.5)
        candidates.append({
            "mint": mint, "y0": y0, "venue": venue, "complete": complete,
            "age_h": age_h, "slope": slope, "long": long_i,
            "sigma": sigma_sqrt_h,
        })
    candidates.sort(key=lambda c: c["y0"], reverse=True)
    top_by_cap = candidates[:MAX_CANDIDATES]
    growers = sorted(candidates, key=lambda c: c["slope"], reverse=True)[:40]
    keep = {c["mint"]: c for c in top_by_cap}
    for c in growers:
        keep[c["mint"]] = c
    candidates = sorted(keep.values(), key=lambda c: c["y0"], reverse=True)

    # ---- Monte Carlo over answer reads (known coins + bootstrapped newcomers) ----
    rng = random.Random(SEED)
    n_cand = len(candidates)
    freq = [[0.0] * (places + 1) for _ in range(n_cand)]
    place_caps = [[] for _ in range(places)]
    tau_g = 0.75
    for _ in range(N_PATHS):
        for h in horizons:
            shock = rng.gauss(0.0, COMMON_SHOCK_SD)
            vals = []
            for idx, c in enumerate(candidates):
                grow = c["slope"] * tau_g * (1.0 - math.exp(-h / tau_g)) if h > 0 else 0.0
                grow = clamp(grow, -0.75, 0.75)
                mu = c["y0"] + grow + c["long"] * h
                sd = math.sqrt((c["sigma"] ** 2) * h + (0.05 * h) ** 2 + 0.05 ** 2)
                sd = clamp(sd, 0.08, 0.70)
                y = mu + sd * rng.gauss(0.0, 1.0) + shock
                if c["venue"] == "curve" and not c["complete"]:
                    p_grad = 1.0 - math.exp(-grad_rate * h) if h > 0 else 0.0
                    if rng.random() < p_grad:
                        y = y + rng.gauss(jump_mean, jump_sd)
                vals.append((y, idx))
            if young_by_rank[0]:
                scale = 10.0 ** clamp(young_growth * h, -0.3, 1.0)
                new_caps = []
                for r in range(5):
                    vals_r = young_by_rank[r]
                    if vals_r:
                        new_caps.append(vals_r[rng.randrange(len(vals_r))]
                                        + math.log10(scale) + rng.gauss(0.0, 0.08))
                new_caps.sort(reverse=True)
                for yv in new_caps:
                    vals.append((yv, -1))
            vals.sort(key=lambda v: (-v[0], candidates[v[1]]["mint"] if v[1] >= 0 else ""))
            for k in range(places):
                y_top, idx = vals[k]
                place_caps[k].append(y_top)
                if idx >= 0:
                    freq[idx][k + 1] += 1.0
    n_sims = N_PATHS * len(horizons)
    for i in range(n_cand):
        for k in range(1, places + 1):
            freq[i][k] /= n_sims

    def greedy_rows(items, total_slots):
        """items: (key, p) sorted desc. Name a row only while its p beats the
        unnamed share it would otherwise receive."""
        named = []
        s = 0.0
        for key, p in items:
            if p <= 0:
                break
            n_after = len(named) + 1
            u_after = (1.0 - s - p) / max(1, total_slots - n_after)
            if p > u_after:
                named.append((key, p))
                s += p
            else:
                break
        return named

    def enforce_place_caps(rows, cap_units=999999):
        """v2 fix: after 6-decimal rounding, cap each place's sum at
        cap_units micro-units (0.999999) so no place can exceed 1.
        Rounding alone pushed place-1 sizes to 1.000001 in v1 and the
        server marked the entry invalid (valid: 0, floor score -92.1).
        Work in integer micro-units: the excess (a few units at most) is
        taken off that place's largest row, never below zero; a row
        trimmed to zero is dropped. Re-checks until the place is in cap.
        The model, Monte Carlo and calibration are untouched."""
        by_place = {}
        for r in rows:
            by_place.setdefault(r["place"], []).append(r)
        kept = []
        for place in sorted(by_place):
            rs = by_place[place]
            units = [int(round(r["p"] * 1_000_000)) for r in rs]
            total = sum(units)
            while total > cap_units:
                j = max(range(len(rs)), key=lambda i: units[i])
                if units[j] <= 0:
                    break
                cut = min(units[j], total - cap_units)
                units[j] -= cut
                total -= cut
            for r, u in zip(rs, units):
                if u > 0:
                    r["p"] = u / 1_000_000
                    kept.append(r)
        return kept

    probabilities = []
    for k in range(1, places + 1):
        items = sorted(((candidates[i]["mint"], freq[i][k]) for i in range(n_cand)),
                       key=lambda x: (-x[1], x[0]))
        for mint, p in greedy_rows(items, 100):
            probabilities.append({"mint": mint, "place": k, "p": round(p, 6)})
    probabilities.sort(key=lambda r: (r["place"], -r["p"], r["mint"]))

    # ---- sizes from the simulated place caps (newcomers included) ----
    # v3: the MC place-cap mean overshoots the realized caps at practice
    # horizons.  On the rehearsal the MC mean sits +0.56..+0.75 above the
    # last mark's place caps (mean +0.65), but the practice answers realized
    # only ~+0.23 (inferred from the site's size gap: v2 -21.67 vs the
    # baseline's -19.03, with matching sds ~0.33 vs 0.35 — the whole gap is
    # this centring error).  The MC's per-coin slopes extrapolate the
    # explosive early phase; the place-cap level itself decelerates.  So the
    # size centre is the last mark's place-k cap plus the MC's predicted
    # rise shrunk by adaptive_alpha() (see above): when the level is still
    # accelerating the MC rise is trusted, when it has decelerated the
    # centre moves toward the last mark.  The Monte Carlo, the frequencies,
    # the probabilities and the top5 are untouched — sizes only.
    last_caps = [logcap_sol(r["market_cap_lamports"]) for r in last_rows[:places]]
    alpha = adaptive_alpha()
    sizes = []
    for k in range(1, places + 1):
        caps = place_caps[k - 1]
        if not caps:
            continue
        m_k = last_caps[k - 1] + alpha * (mean(caps) - last_caps[k - 1])
        s_k = clamp(stdev(caps), 0.20, 0.80)

        def cdf(x):
            return norm_cdf(x, m_k, s_k)

        bin_p = []
        for b in range(nbins):
            if b == 0:
                p_b = cdf(edges[0])
            elif b == nbins - 1:
                p_b = 1.0 - cdf(edges[-1])
            else:
                p_b = cdf(edges[b]) - cdf(edges[b - 1])
            bin_p.append((b, max(0.0, p_b)))
        items = sorted(bin_p, key=lambda x: (-x[1], x[0]))
        for b, p in greedy_rows(items, nbins):
            sizes.append({"place": k, "bin": b, "p": round(p, 6)})
    sizes.sort(key=lambda r: (r["place"], r["bin"]))

    # ---- top5: greedy by place frequency ----
    top5 = []
    used = set()
    for k in range(1, places + 1):
        best = None
        best_f = -1.0
        for i in range(n_cand):
            if candidates[i]["mint"] in used:
                continue
            if freq[i][k] > best_f:
                best_f = freq[i][k]
                best = candidates[i]["mint"]
        if best is not None:
            top5.append(best)
            used.add(best)
    if len(top5) < places:
        exp_rank = []
        for i in range(n_cand):
            er = sum(k * freq[i][k] for k in range(1, places + 1))
            exp_rank.append((er, candidates[i]["mint"]))
        exp_rank.sort()
        for _, mint in exp_rank:
            if mint not in used:
                top5.append(mint)
                used.add(mint)
            if len(top5) == places:
                break

    # v2 fix: cap every place's rounded sum at 0.999999 (see
    # enforce_place_caps) so the forecast can never breach the
    # "each place sums <= 1" rule, for sizes and probabilities alike.
    probabilities = enforce_place_caps(probabilities)
    sizes = enforce_place_caps(sizes)

    doc = {"probabilities": probabilities, "top5": top5[:places], "sizes": sizes}
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    out_path = os.path.join(OUTPUT_DIR, task.get("output", "forecast.json"))
    with open(out_path, "w") as f:
        f.write(json.dumps(doc) + "\n")


if __name__ == "__main__":
    main()
