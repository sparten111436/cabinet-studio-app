"""Shared gate for driver stubs. No protocol bytes are implemented."""

from __future__ import annotations


class LiveDriverDisabled(RuntimeError):
    """Raised when a stub driver is asked to talk to hardware."""


class DriverStub:
    """Base class for a controller driver that cannot go online yet."""

    protocol = "driver"
    default_port = 0
    allow_live = False

    def connect(self, host: str, port: int | None = None) -> None:
        del host, port
        if not self.allow_live:
            raise LiveDriverDisabled(
                f"{self.protocol} live access is disabled (allow_live=False). "
                "Cabinet Studio does not open a session to the controller."
            )
        raise NotImplementedError(
            f"{self.protocol} has no live session implementation in this build."
        )

    def read(self, address: str):
        del address
        self.connect("")

    def write(self, address: str, value: object) -> None:
        del address, value
        self.connect("")
