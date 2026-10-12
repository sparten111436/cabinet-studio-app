"""Voice description capture — stub.

A later release can let an engineer describe a device out loud and
prefill the wizard. This build does not import a microphone library
and does not record audio.
"""

from __future__ import annotations


class VoiceCapture:
    enabled = False

    def capture(self) -> dict[str, str]:
        raise NotImplementedError(
            "Voice description capture is not installed. "
            "Define the device in the wizard. No microphone library is required."
        )
