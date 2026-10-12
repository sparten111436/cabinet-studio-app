"""Software compatibility watchlist — stub.

A later release can flag firmware, HMI runtime, and drive-profile
mismatches. This build returns no findings and does not query vendors.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CompatibilityNote:
    device_tag: str
    message: str


class CompatibilityWatchlist:
    enabled = False

    def evaluate(self, devices: list[dict]) -> list[CompatibilityNote]:
        del devices
        return []
