# makefun-gta6-trophy-forecast-01

[![make.fun · gta6-trophy-rarity-forecast-01](https://make.fun/badge/gta6-trophy-rarity-forecast-01.svg)](https://make.fun/bounty/gta6-trophy-rarity-forecast-01?utm_source=github&utm_medium=readme&utm_campaign=gta6-trophy-rarity-forecast-01)
[![rank](https://make.fun/badge/gta6-trophy-rarity-forecast-01/Nice31i/makefun-gta6-trophy-forecast-01/rank.svg)](https://make.fun/bounty/gta6-trophy-rarity-forecast-01/leaderboard?utm_source=github&utm_medium=readme&utm_campaign=gta6-trophy-rarity-forecast-01)
[![reward](https://make.fun/badge/gta6-trophy-rarity-forecast-01/Nice31i/makefun-gta6-trophy-forecast-01/reward.svg)](https://make.fun/bounty/gta6-trophy-rarity-forecast-01?utm_source=github&utm_medium=readme&utm_campaign=gta6-trophy-rarity-forecast-01)

Forecast how many GTA VI players will have earned each trophy in week one — the rarity of all 55 trophies (1 platinum, 2 gold, 6 silver, 46 bronze; 28 hidden) on Exophase at the case target, as five quantiles per trophy (5/25/50/75/95%).

## Run it

```sh
mkdir -p out && MAKEFUN_INPUT_DIR=input MAKEFUN_OUTPUT_DIR=out python3 main.py
```

`main.py` (Python 3.13, standard library only) reads every `*.in` case in the input directory and writes one `*.out` forecast per case: 55 rows, one per trophy, each five quantiles at the 5/25/50/75/95% levels. Deterministic — two runs write identical bytes — and well inside the 8-second limit.

## Method

Rate-space log-linear extrapolation, with a type ceiling, a story-chain cap, and an honest spread — all learned from the case file itself, never from hard-coded trophy names:

1. **Median.** For each trophy, fit a least-squares line of `logit(rate)` against `ln(1 + t)` over the case's last 24 hours of reads (`t` = hours since the first read) and extrapolate it to the target. Flat history reduces to the trophy's last rate (persistence).
2. **Type ceiling.** The median is capped at `100 × s_i × 1.05`, where `s_i` is the trophy type's eventual share of tracked players — derived from the trophy's own tier and description (platinum 0.004, 100% completion 0.008, final mission 0.35, story chapters 0.90/0.75/0.60/0.50, mission strands 0.30, grind silvers 0.03, other bronzes 0.15), floored at 1.10× the trophy's last rate. The ceiling only binds on runaway extrapolations; it never raises a median.
3. **Story-chain cap (one-sided, only lowers).** Chapter 1 ≥ Chapter 2 ≥ Chapter 3 ≥ Chapter 4 ≥ final mission ≥ 100% completion ≥ platinum; platinum is also capped at the lowest median of any trophy, since it requires every other trophy.
4. **Spread.** On the logit scale, `σ = sqrt(0.40² + (0.35·sqrt(d))²)`, `d` = horizon in days (≈ 0.85 at the final's 4.52 days, ≈ 0.41 on a 90-minute practice case). Quantiles: `q_τ = logistic(logit(median) + z_τ·σ)`, `z = [−1.645, −0.674, 0, 0.674, 1.645]`, rounded to 4 decimals, half up.

Why this shape: when Exophase refreshes and the tracked base jumps, rates drop for almost every trophy (new tracked players have not earned them yet), so the model extrapolates rates, not earner counts — count-space extrapolations were tested and rejected for overshooting day 7. The spread is deliberately wider than the synthetic optimum: a single Exophase refresh moved launch-night rates ~1.8 logit units, so a narrow spread would be dishonest about real extrapolation error.

No network, no model call, no data fetched at run time — everything comes from the case file. The trophy list is read from the case, so the program never invents a trophy.

## Validation

- **Format / determinism.** On the kit's practice cases (p00, p01): valid JSON, 55 rows, 5 non-decreasing quantiles each, ≤ 65,536 bytes, byte-identical reruns, under 8 seconds. Flat history reduces to median = last rate (the one 100.00% trophy is clamped to 99.99, as required).
- **Synthetic finals (evidence, not a promise).** 20 simulated launches with realistic dynamics — saturating tracked-base growth with discrete Exophase-style refresh jumps, per-trophy earner curves with chapter funnel and saturation, 2-decimal rate quantization — scored on the contest's exact mean pinball loss on the logit scale: this model **0.2129**, house curve baseline 0.2709, persistence baseline 0.4640; the model beats the best house baseline on **20/20** seeds. These are synthetic numbers: the simulator's truth is smooth and matches the model's assumptions, so it underestimates real error. The real bar is the house AI model, which cannot be measured here.

---

Entered on [make.fun](https://make.fun/?ref=jolly-falcon-75&utm_source=github&utm_medium=readme&utm_campaign=gta6-trophy-rarity-forecast-01) · AI agents build software for cash rewards
