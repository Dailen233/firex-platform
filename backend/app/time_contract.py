"""Observation time contract for Fire-X runs (B1).

Two machine-readable ``time_basis`` values, one per ``input_source``:

- ``simulation`` -> ``simulation_relative``
  - ``simulation_time_origin_s`` is the simulator's global clock value (seconds)
    at run start, provided by the client at creation.
  - An observation carrying a simulator clock value ``simulation_time_s`` maps to
    ``observation_time_s = simulation_time_s - simulation_time_origin_s``.
  - Does not depend on UTC wall clock; the origin is the simulator's own clock.

- ``real`` -> ``utc_anchored``
  - ``time_origin_utc`` is a timezone-aware UTC instant, provided by the client at
    creation (the anchor of the capture timeline).
  - An observation carrying a capture timestamp ``captured_at_utc`` maps to
    ``observation_time_s = (captured_at_utc - time_origin_utc).total_seconds()``.

Neither basis is derived from the server ``created_at``; ``created_at`` only
records when the run row was created server-side.
"""
from __future__ import annotations

from datetime import datetime

TIME_BASIS_SIMULATION = "simulation_relative"
TIME_BASIS_REAL = "utc_anchored"

TIME_BASIS = {
    "simulation": TIME_BASIS_SIMULATION,
    "real": TIME_BASIS_REAL,
}


def observation_time_s_for_simulation(simulation_time_s: float, origin_s: float) -> float:
    """Run-relative observation seconds from a simulator global-clock value."""
    return simulation_time_s - origin_s


def observation_time_s_for_real(captured_at_utc: datetime, origin_utc: datetime) -> float:
    """Observation seconds from a captured UTC timestamp relative to the origin."""
    return (captured_at_utc - origin_utc).total_seconds()
