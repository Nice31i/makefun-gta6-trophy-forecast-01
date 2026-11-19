"""gta6-trophy-rarity-forecast-01: forecast each GTA VI trophy's Exophase rarity
at the case target, as five quantiles (5/25/50/75/95%) per trophy.

Method (see DESIGN.md in the work dir; implemented from that doc only):
  1. Median: least-squares fit of logit(rate) against ln(1 + t) over the case's
     last 24 hours of reads (t = hours since the first read in the history),
     extrapolated to the target. Flat history -> the trophy's last rate
     (persistence).
  2. Type ceiling: the median is capped at 100 * s_i * 1.05, where s_i is the
     trophy type's eventual share of tracked players (a documented prior,
     floored at 1.10x the trophy's last rate, capped at 0.98). The ceiling
     only binds on runaway extrapolations; it never raises a median.
  3. Story-chain monotonicity (one-sided cap, only lowers): Chapter 1 >=
     Chapter 2 >= Chapter 3 >= Chapter 4 >= final mission >= 100% completion
     >= platinum; platinum is also capped at the lowest median of any trophy.
  4. Spread on the logit scale: sigma = sqrt(0.40^2 + (0.35 * sqrt(d))^2),
     d = horizon in days; q_tau = logistic(logit(median) + z_tau * sigma),
     z = [-1.645, -0.674, 0, 0.674, 1.645], rounded to 4 decimals, half up.

Trophy types are derived from the case's own trophy fields (tier, points,
description) -- never from hard-coded names -- so the program stays general
and never invents a trophy: every trophy id comes from the case file.

Python 3.13, standard library only. Deterministic: no randomness, no
wall-clock reads, sorted iteration. Run as:
    mkdir -p out && MAKEFUN_INPUT_DIR=input MAKEFUN_OUTPUT_DIR=out python3 main.py
"""

import json
import math
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

# The grader's -P leaves /bot off sys.path: put it back first, so a module
# shipped beside this file would import (same pattern as the starter).
sys.path.insert(0, str(Path(__file__).resolve().parent))

INPUT_DIR = Path(os.environ.get("MAKEFUN_INPUT_DIR", "/input"))
OUTPUT_DIR = Path(os.environ.get("MAKEFUN_OUTPUT_DIR", "/output"))

LEVELS = [0.05, 0.25, 0.5, 0.75, 0.95]
Z = [-1.645, -0.674, 0, 0.674, 1.645]

# Spread parameters (DESIGN.md section 3.5): deliberately wider than the
# synthetic optimum -- the real final has launch dynamics a smooth simulator
# cannot see (non-random Exophase sample, irregular refreshes, discrete
# story progression). At the final (d = 4.52 days) sigma is about 0.85.
SIGMA0 = 0.40
SIGMA1 = 0.35

# Eventual shares by trophy type (DESIGN.md section 3.4). Generous priors:
# they only bind on runaway extrapolations; the fitted trend does the work.
SHARE_PLATINUM = 0.004
SHARE_COMPLETION = 0.008
SHARE_FINAL_MISSION = 0.35
SHARE_CHAPTER = {1: 0.90, 2: 0.75, 3: 0.60, 4: 0.50}
SHARE_MISSION_STRAND = 0.30
SHARE_GRIND_SILVER = 0.03
SHARE_ACTIVITY_BRONZE = 0.15

CHAPTER_RE = re.compile(r"Complete Chapter (\d)")


def clamp_pct(x: float) -> float:
    return min(99.99, max(0.01, x))


def logit(pct: float) -> float:
    p = clamp_pct(pct)
    return math.log(p / (100.0 - p))


def logistic(logit_value: float) -> float:
    return 100.0 / (1.0 + math.exp(-logit_value))


def round4(x: float) -> float | int:
    """x rounded to 4 decimals, half up, as JavaScript's
    Math.round(x * 10000) / 10000 rounds it (same as the starter)."""
    scaled = x * 10000
    whole = math.floor(scaled)
    if scaled - whole >= 0.5:
        whole += 1
    value = whole / 10000
    return int(value) if value.is_integer() else value


def parse_time(text: str) -> datetime:
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


def trophy_type(trophy: dict) -> str:
    """Classify a trophy from its own fields (tier / description).

    Returns one of: 'platinum', 'completion', 'final', 'chapter1'..'chapter4',
    'strand', 'grind', 'activity'. Checks run in the DESIGN.md order:
    platinum, 100% completion, final mission, story chapter, mission strand,
    grind silver, activity bronze.
    """
    desc = trophy.get("description", "") or ""
    tier = trophy.get("tier", "") or ""
    if tier == "platinum":
        return "platinum"
    if "100%" in desc:
        return "completion"
    # The story-final mission is the trophy whose description is exactly
    # "Complete the final mission." A character strand's "final mission for
    # X" names that character's mission strand, not the story finale, so it
    # falls through to the strand rule below (share 0.30, not 0.35).
    if desc.strip().rstrip(".") == "Complete the final mission":
        return "final"
    m = CHAPTER_RE.search(desc)
    if m:
        return "chapter%d" % int(m.group(1))
    if trophy.get("secret") and desc.startswith("Complete "):
        return "strand"
    if tier == "silver":
        return "grind"
    return "activity"


def eventual_share(trophy: dict, last_rate: float | None) -> float:
    """Type prior share s_i, floored at 1.10x the last observed rate and
    capped at 0.98 (DESIGN.md section 3.4)."""
    kind = trophy_type(trophy)
    if kind == "platinum":
        s = SHARE_PLATINUM
    elif kind == "completion":
        s = SHARE_COMPLETION
    elif kind == "final":
        s = SHARE_FINAL_MISSION
    elif kind.startswith("chapter"):
        s = SHARE_CHAPTER.get(int(kind[-1]), 0.50)
    elif kind == "strand":
        s = SHARE_MISSION_STRAND
    elif kind == "grind":
        s = SHARE_GRIND_SILVER
    else:
        s = SHARE_ACTIVITY_BRONZE
    if last_rate is not None:
        s = max(s, 1.10 * last_rate / 100.0)
    return min(s, 0.98)


def last_non_null_rate(history: list, idx: int) -> float | None:
    """The trophy's most recent non-null rate in the history, or None."""
    for read in reversed(history):
        rate = read["rates"][idx]
        if rate is not None:
            return float(rate)
    return None


def fit_median(history: list, idx: int, t_origin: datetime,
               target: datetime) -> float:
    """Least-squares log-linear extrapolation of the rate (DESIGN.md 3.1).

    Fits logit(rate) against ln(1 + t) over the last 24 hours of reads,
    t in hours since the first read in the history, and extrapolates to the
    target. Falls back to the last non-null rate when the window has fewer
    than 3 reads, fewer than 2 distinct ln(1 + t) values, or no usable rate.
    """
    last_rate = last_non_null_rate(history, idx)
    if last_rate is None:
        return 0.01
    if len(history) < 3:
        return last_rate
    last_at = parse_time(history[-1]["at"])
    window_start = last_at.timestamp() - 24 * 3600
    points = []
    for read in history:
        if parse_time(read["at"]).timestamp() < window_start:
            continue
        rate = read["rates"][idx]
        if rate is None:
            continue
        t = (parse_time(read["at"]) - t_origin).total_seconds() / 3600.0
        points.append((math.log1p(max(t, 0.0)), logit(float(rate))))
    if len(points) < 3:
        return last_rate
    xs = [p[0] for p in points]
    if len(set(xs)) < 2:
        return last_rate
    n = len(points)
    mean_x = sum(xs) / n
    mean_y = sum(p[1] for p in points) / n
    sxx = sum((x - mean_x) ** 2 for x in xs)
    if sxx <= 0:
        return last_rate
    sxy = sum((p[0] - mean_x) * (p[1] - mean_y) for p in points)
    slope = sxy / sxx
    intercept = mean_y - slope * mean_x
    t_target = (target - t_origin).total_seconds() / 3600.0
    return clamp_pct(logistic(intercept + slope * math.log1p(max(t_target, 0.0))))


def chain_indices(trophies: list) -> list:
    """Indices of the story-chain trophies, top to bottom (DESIGN.md 3.3):
    Chapter 1, Chapter 2, Chapter 3, Chapter 4, final mission, 100%
    completion, platinum. A link is skipped when the case has no such
    trophy."""
    by_kind: dict[str, int] = {}
    for i, trophy in enumerate(trophies):
        kind = trophy_type(trophy)
        # The chain's "final mission" is the story-final trophy, not a
        # character strand's final mission.
        if kind == "final" and trophy.get("description", "") == "Complete the final mission.":
            by_kind["final"] = i
        elif kind not in by_kind:
            by_kind[kind] = i
    order = ["chapter1", "chapter2", "chapter3", "chapter4",
             "final", "completion", "platinum"]
    return [by_kind[k] for k in order if k in by_kind]


def forecast_case(case: dict, name: str) -> dict:
    if case["levels"] != LEVELS:
        raise ValueError(f"{name} asks for levels {case['levels']}, not {LEVELS}")
    trophies = case["trophies"]
    history = case.get("history") or []
    horizon_days = case["horizon_minutes"] / 1440.0
    sigma = math.sqrt(SIGMA0 ** 2 + (SIGMA1 * math.sqrt(horizon_days)) ** 2)

    if not history:
        medians = [0.01] * len(trophies)
    else:
        t_origin = parse_time(history[0]["at"])
        target = parse_time(case["target"])
        medians = []
        for idx, trophy in enumerate(trophies):
            median = fit_median(history, idx, t_origin, target)
            last_rate = last_non_null_rate(history, idx)
            share = eventual_share(trophy, last_rate)
            # Type ceiling (cap, never a target).
            median = min(median, 100.0 * share * 1.05)
            medians.append(median)

        # Story-chain monotonicity: one-sided cap, only lowers.
        chain = chain_indices(trophies)
        for prev, nxt in zip(chain, chain[1:]):
            if medians[nxt] > medians[prev]:
                medians[nxt] = medians[prev]
        # Platinum requires every other trophy: it cannot exceed the
        # lowest median of any trophy.
        plat = [i for i, t in enumerate(trophies) if t.get("tier") == "platinum"]
        if plat and medians:
            floor = min(medians)
            for i in plat:
                if medians[i] > floor:
                    medians[i] = floor

    rows = []
    for trophy, median in zip(trophies, medians):
        base = logit(median)
        qs = []
        for z in Z:
            q = clamp_pct(logistic(base + z * sigma))
            qs.append(round4(q))
        # Non-decreasing by construction; enforce it after rounding.
        for j in range(1, len(qs)):
            if qs[j] < qs[j - 1]:
                qs[j] = qs[j - 1]
        rows.append({"id": trophy["id"], "q": qs})
    rows.sort(key=lambda r: r["id"])
    return {"trophies": rows}


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    # Every case file, in name order, so two runs write the same bytes.
    for path in sorted(INPUT_DIR.glob("*.in")):
        case = json.loads(path.read_text(encoding="utf-8"))
        forecast = forecast_case(case, path.name)
        (OUTPUT_DIR / f"{path.stem}.out").write_text(
            json.dumps(forecast, separators=(",", ":")) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
