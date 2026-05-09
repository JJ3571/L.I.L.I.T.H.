"""Unit tests for brainrot timing and burst composition helpers."""

from __future__ import annotations

import random
from pathlib import Path

from main_bot.cogs.production import brainrot as br


def test_roll_brainrot_silence_cap_within_three_to_fifteen_minutes() -> None:
    rng = random.Random(12345)
    for _ in range(100):
        cap = br.roll_brainrot_silence_cap_sec(rng)
        assert br.BRAINROT_SILENCE_CAP_MIN_SEC <= cap <= br.BRAINROT_SILENCE_CAP_MAX_SEC


def test_schedule_next_wake_respects_deadline() -> None:
    rng = random.Random(42)
    now = 1000.0
    deadline = now + 100.0
    for _ in range(300):
        step = br.schedule_next_wake_seconds(
            rng,
            now_mono=now,
            deadline_mono=deadline,
            min_gap_sec=30.0,
            max_gap_sec=180.0,
        )
        assert 0.0 <= step <= 100.0 + 1e-6


def test_schedule_immediate_when_deadline_elapsed() -> None:
    rng = random.Random(0)
    assert (
        br.schedule_next_wake_seconds(
            rng,
            now_mono=2000.0,
            deadline_mono=1999.0,
            min_gap_sec=30.0,
            max_gap_sec=180.0,
        )
        == 0.0
    )


def test_dodgeball_burst_count_escalation_and_cap() -> None:
    assert br.dodgeball_burst_count(0.0, base=1, escalation_sec=60.0, max_dodgeballs=12) == 1
    assert br.dodgeball_burst_count(59.9, base=1, escalation_sec=60.0, max_dodgeballs=12) == 1
    assert br.dodgeball_burst_count(120.0, base=1, escalation_sec=60.0, max_dodgeballs=12) == 3
    assert br.dodgeball_burst_count(3600.0, base=1, escalation_sec=60.0, max_dodgeballs=5) == 5


def test_build_burst_paths_same_seed_same_order() -> None:
    rng_a = random.Random(999)
    rng_b = random.Random(999)
    d = Path("dodge.mp3")
    p = Path("plank.mp3")
    s = Path("pipe.mp3")
    sd = Path("smoke.mp3")
    elapsed = 120.0
    pend_p = 1
    pend_s = 2
    pend_sm = 1
    paths_a = br.build_burst_paths(
        rng_a,
        elapsed_since_last_trigger_sec=elapsed,
        dodgeball_path=d,
        plankton_path=p,
        steel_pipe_path=s,
        smoke_detector_path=sd,
        pending_plankton=pend_p,
        pending_pipe=pend_s,
        pending_smoke=pend_sm,
    )
    paths_b = br.build_burst_paths(
        rng_b,
        elapsed_since_last_trigger_sec=elapsed,
        dodgeball_path=d,
        plankton_path=p,
        steel_pipe_path=s,
        smoke_detector_path=sd,
        pending_plankton=pend_p,
        pending_pipe=pend_s,
        pending_smoke=pend_sm,
    )
    assert paths_a == paths_b
    n_dodge = br.dodgeball_burst_count(elapsed, base=br.BRAINROT_BASE_DODGEBALLS, escalation_sec=br.BRAINROT_ESCALATION_SEC, max_dodgeballs=br.BRAINROT_MAX_DODGEBALLS)
    assert len(paths_a) == n_dodge + pend_p + pend_s + pend_sm
