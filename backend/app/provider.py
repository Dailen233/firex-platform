"""Processing provider interface and the fixture provider.

The provider turns a stored capture (record + normalized metadata + original
bytes + observation time) into a structured result. The service configuration
selects which provider (if any) runs; ``unconfigured`` means no provider, so
queued captures stay queued and no results are produced.
"""
from __future__ import annotations

from dataclasses import dataclass

from .capture_metadata import CaptureMetadata


@dataclass
class ProcessingResult:
    result_origin: str
    provider_version: str
    patch_id: str
    geometry: list[list[float]]


class ProcessingProvider:
    name: str = ""
    version: str = ""

    def process(
        self,
        capture_id: str,
        meta: CaptureMetadata,
        original_bytes: bytes,
        observation_time_s: float,
    ) -> ProcessingResult:
        raise NotImplementedError


class FixtureProvider(ProcessingProvider):
    """Fixed, clearly-labeled fixture data — NOT an image reconstruction.

    Produces one stable ``patch_id`` whose geometry varies deterministically
    with the observation time, so two captures at different times yield two
    different contours for the same patch. ``result_origin="fixture"`` marks
    every result as interface test data (see also contracts/README.md).
    """

    name = "fixture"
    version = "1.0"
    PATCH_ID = "fixture-patch-1"

    def process(
        self,
        capture_id: str,
        meta: CaptureMetadata,
        original_bytes: bytes,
        observation_time_s: float,
    ) -> ProcessingResult:
        return ProcessingResult(
            result_origin="fixture",
            provider_version=self.version,
            patch_id=self.PATCH_ID,
            geometry=_fixture_geometry(observation_time_s),
        )


def _fixture_geometry(observation_time_s: float) -> list[list[float]]:
    """Preset square centered at a fixed local point; the half-extent grows with
    the observation time so distinct times produce distinct (closed) contours."""
    half = 5.0 + (observation_time_s % 20.0)
    x0, z0 = 100.0, 200.0
    return [
        [x0 - half, z0 - half],
        [x0 + half, z0 - half],
        [x0 + half, z0 + half],
        [x0 - half, z0 + half],
        [x0 - half, z0 - half],
    ]


def make_provider(mode: str) -> ProcessingProvider | None:
    if mode == "fixture":
        return FixtureProvider()
    return None
