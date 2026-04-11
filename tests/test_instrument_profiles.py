"""Regression tests for sidmatch.grid_search instrument-type constraint profiles.

Ensures the piano profile does not allow sustain=0, which silently kills
the SID envelope tail and produced the clicky piano params that had to
be reverted in PR #25 (see commit df73d33 and the investigation in the
fix/revert-piano-params-to-baseline branch).
"""

from __future__ import annotations

import pytest

from sidmatch.grid_search import (
    INSTRUMENT_PROFILES,
    _adsr_bounds_from_profile,
    get_instrument_profile,
)


class TestPianoProfileSustainFloor:
    """Piano profile must not allow sustain=0.

    A SID envelope with sustain=0 drops to silence the moment the decay
    phase finishes, regardless of how long `release` or the renderer's
    gate_frames/release_frames are. This makes every "piano" note sound
    like a ~50-300 ms click. The hand-tuned baseline uses sustain=15 on
    both 6581 and 8580; the profile must stay well clear of 0.
    """

    def test_profile_exists(self) -> None:
        assert "piano" in INSTRUMENT_PROFILES

    def test_adsr_bounds_present(self) -> None:
        profile = INSTRUMENT_PROFILES["piano"]
        assert "adsr_bounds" in profile
        assert "sustain" in profile["adsr_bounds"]

    def test_sustain_lower_bound_nonzero(self) -> None:
        lo, _hi = INSTRUMENT_PROFILES["piano"]["adsr_bounds"]["sustain"]
        assert lo > 0, (
            f"piano sustain lower bound is {lo}; sustain=0 makes the SID "
            "envelope decay to silence before release ever starts. "
            "Must be strictly positive for an audible piano tail."
        )

    def test_sustain_lower_bound_is_audibly_high(self) -> None:
        """Even sustain=1 is barely audible on the 4-bit SID envelope.

        A piano patch that loses >~20% of its envelope level immediately
        after decay will sound clipped. Floor at 10 (~67% of max) so the
        optimizer cannot sneak into an inaudible region under fitness
        pressure from onset-focused components.
        """
        lo, _hi = INSTRUMENT_PROFILES["piano"]["adsr_bounds"]["sustain"]
        assert lo >= 10, (
            f"piano sustain lower bound is {lo}; recommend >= 10 so the "
            "envelope stays clearly audible after the decay phase"
        )

    def test_sustain_upper_bound_reaches_max(self) -> None:
        """Baseline piano params use sustain=15. Profile must allow it."""
        _lo, hi = INSTRUMENT_PROFILES["piano"]["adsr_bounds"]["sustain"]
        assert hi == 15

    def test_screening_default_sustain_matches_bounds(self) -> None:
        """Phase 1 screening seed must satisfy the profile's sustain bounds.

        If the seed is outside the bound box, the optimizer starts from
        an infeasible point and Phase 1 results are meaningless.
        """
        profile = INSTRUMENT_PROFILES["piano"]
        sd_sustain = profile["screening_defaults"]["sustain"]
        lo, hi = profile["adsr_bounds"]["sustain"]
        assert lo <= sd_sustain <= hi, (
            f"screening_defaults.sustain={sd_sustain} is outside the "
            f"profile's sustain bounds [{lo}, {hi}]"
        )

    def test_bounds_propagate_to_optimizer_override_dict(self) -> None:
        """`_adsr_bounds_from_profile` must emit the sustain bound.

        This is the hook the CMA-ES / TPE backends read to constrain the
        ADSR dimensions of the search space. If the sustain entry is
        missing from the override dict, the optimizer would silently
        fall back to the global ADSR bounds (0-15) and be free to pick
        sustain=0 again.
        """
        profile = get_instrument_profile("piano")
        overrides = _adsr_bounds_from_profile(profile)
        assert overrides is not None
        # Sustain is ADSR index 2.
        assert 2 in overrides, (
            "sustain bound not present in adsr_bound_overrides; the "
            "optimizer will not see the profile's sustain constraint"
        )
        lo, hi = overrides[2]
        assert lo >= 10
        assert hi == 15


def test_unknown_profile_raises() -> None:
    with pytest.raises(ValueError, match="unknown instrument type"):
        get_instrument_profile("kazoo")


def test_none_profile_returns_none() -> None:
    assert get_instrument_profile(None) is None
