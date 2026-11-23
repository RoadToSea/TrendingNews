"""Velocity and composite hot-index scoring algorithms."""

from datetime import datetime
import math
from typing import Dict, Optional, Sequence, Tuple


def rank_to_score(rank: int) -> float:
    """Convert 1-based ranking into a bounded `[0, 50]` score.

    Args:
        rank: 1-based board rank (`1` is highest).

    Returns:
        float: Score from `50.0` (rank 1) down to `0.0` (rank >= 51).
    """
    if rank <= 0:
        return 0.0
    return float(max(0, 51 - min(rank, 51)))


def _parse_iso(ts: str) -> Optional[datetime]:
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts)
    except ValueError:
        return None


def compute_rank_velocity(
    history: Sequence[Tuple[str, int, Optional[float]]],
    first_seen_at: str,
    now: datetime,
) -> float:
    """Compute velocity for rank-only platforms using climb rate plus debut bonus.

    Args:
        history: Chronological `(recorded_at, rank, metric_value)` tuples.
        first_seen_at: ISO-8601 timestamp when item was first observed.
        now: Reference timestamp with matching timezone.

    Returns:
        float: Non-negative velocity score.
    """
    if not history:
        return 0.0

    latest_ts_str, latest_rank, _ = history[-1]
    latest_ts = _parse_iso(latest_ts_str) or now
    latest_score = rank_to_score(latest_rank)

    climb_rate = 0.0
    baseline = _find_baseline_sample(history[:-1], latest_ts)
    if baseline is not None:
        base_ts, base_rank = baseline
        delta_hours = max((latest_ts - base_ts).total_seconds() / 3600.0, 0.5)
        climb_rate = max(0.0, (latest_score - rank_to_score(base_rank)) / delta_hours)

    debut_bonus = 0.0
    first_dt = _parse_iso(first_seen_at)
    if first_dt is not None:
        age_hours = max(0.0, (now - first_dt).total_seconds() / 3600.0)
        if age_hours <= 2.0 and 0 < latest_rank <= 15:
            debut_bonus = (16 - latest_rank) * 2.5

    return round(climb_rate + debut_bonus, 2)


def _find_baseline_sample(
    prior_samples: Sequence[Tuple[str, int, Optional[float]]],
    latest_ts: datetime,
) -> Optional[Tuple[datetime, int]]:
    for ts_str, rank, _ in reversed(prior_samples):
        ts = _parse_iso(ts_str)
        if ts is None:
            continue
        if (latest_ts - ts).total_seconds() >= 1200:
            return ts, rank
    if prior_samples:
        ts = _parse_iso(prior_samples[0][0])
        if ts is not None:
            return ts, prior_samples[0][1]
    return None


def compute_raw_interaction_rate(
    history: Sequence[Tuple[str, int, Optional[float]]],
    first_seen_at: str,
    now: datetime,
) -> float:
    """Compute hourly native interaction growth rate from `metric_value` samples.

    Args:
        history: Chronological `(recorded_at, rank, metric_value)` tuples.
        first_seen_at: ISO-8601 first-seen timestamp.
        now: Reference timestamp.

    Returns:
        float: Non-negative raw hourly interaction growth rate.
    """
    numeric_samples = [(ts, val) for ts, _, val in history if val is not None]
    if not numeric_samples:
        return 0.0

    latest_str, latest_val = numeric_samples[-1]
    latest_dt = _parse_iso(latest_str) or now
    if len(numeric_samples) >= 2:
        for ts_str, prev_val in reversed(numeric_samples[:-1]):
            prev_dt = _parse_iso(ts_str)
            if prev_dt is None:
                continue
            delta_h = (latest_dt - prev_dt).total_seconds() / 3600.0
            if delta_h >= 0.33 or ts_str == numeric_samples[0][0]:
                return max(0.0, (latest_val - prev_val) / max(delta_h, 0.5))

    first_dt = _parse_iso(first_seen_at) or latest_dt
    age_h = max((now - first_dt).total_seconds() / 3600.0, 0.5)
    return max(0.0, latest_val / age_h)


def normalize_platform_interaction_velocities(raw_rates: Dict[int, float]) -> Dict[int, float]:
    """Normalize per-platform interaction growth rates to `[0, 100]` using `log1p` percentiles.

    Args:
        raw_rates: Mapping from `news_item_id` to raw hourly interaction growth rate.

    Returns:
        Dict[int, float]: Normalized velocity scores in `[0, 100]`.
    """
    if not raw_rates:
        return {}

    logged = {item_id: math.log1p(max(0.0, rate)) for item_id, rate in raw_rates.items()}
    sorted_vals = sorted(logged.values())
    max_val = sorted_vals[-1]
    if max_val <= 0.0:
        return {item_id: 0.0 for item_id in raw_rates}

    n = len(sorted_vals)
    if n == 1:
        only_id = next(iter(raw_rates))
        return {only_id: 50.0}

    normalized: Dict[int, float] = {}
    for item_id, val in logged.items():
        if val <= 0.0:
            normalized[item_id] = 0.0
            continue
        # Combine within-batch percentile rank with log-ratio against platform max for smooth ties.
        rank_pos = sum(1 for v in sorted_vals if v <= val) - 1
        percentile = (rank_pos / (n - 1)) * 100.0
        ratio_score = (val / max_val) * 100.0
        normalized[item_id] = round(0.7 * percentile + 0.3 * ratio_score, 2)
    return normalized


def compute_event_hot_index(
    *,
    platform_count: int,
    total_enabled_platforms: int,
    best_ranks: Sequence[int],
    mention_batches: int,
    total_daily_batches: int,
    max_velocity: float,
    weights: Optional[Dict[str, float]] = None,
) -> float:
    """Compute composite `[0, 100]` event hotness index across heterogeneous platforms.

    Args:
        platform_count: Distinct platforms covering this event today.
        total_enabled_platforms: Total enabled platform count for denominator scaling.
        best_ranks: Best rank reached on each covering platform.
        mention_batches: Crawl batches where this event appeared today.
        total_daily_batches: Total crawl batches run today.
        max_velocity: Maximum velocity across linked items.
        weights: Optional weight overrides (`coverage`, `rank`, `persistence`, `velocity`).

    Returns:
        float: Rounded composite hot index in `[0, 100]`.
    """
    w = weights or {"coverage": 0.35, "rank": 0.35, "persistence": 0.20, "velocity": 0.10}
    denom = max(1.0, max(total_enabled_platforms, 1) * 0.5)
    s_cov = min(100.0, (platform_count / denom) * 100.0)

    if best_ranks:
        rank_scores = [rank_to_score(r) * 2.0 for r in best_ranks]
        s_rank = sum(rank_scores) / len(rank_scores)
    else:
        s_rank = 0.0

    s_persist = min(100.0, (mention_batches / max(1, total_daily_batches)) * 100.0)
    s_vel = min(100.0, max(0.0, max_velocity) * 2.0)

    score = (
        w.get("coverage", 0.35) * s_cov
        + w.get("rank", 0.35) * s_rank
        + w.get("persistence", 0.20) * s_persist
        + w.get("velocity", 0.10) * s_vel
    )
    return round(min(100.0, max(0.0, score)), 2)
