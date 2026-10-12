"""Vendor catalog update feed — stub.

A later release can refresh Allen-Bradley, Siemens, and Modbus device
records from a vendor feed. This build never opens a network request.
Edit ``cabinet_studio/library`` JSON locally to extend the starter set.
"""

from __future__ import annotations


class CatalogFeed:
    enabled = False

    def fetch_updates(self) -> list[dict]:
        raise NotImplementedError(
            "Vendor catalog feed is not connected. "
            "Edit cabinet_studio/library JSON locally. No download is performed."
        )
