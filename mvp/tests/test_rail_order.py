"""Left-rail button labels follow ops order (source contract)."""

from pathlib import Path


def test_library_rail_ops_order_in_source():
    path = Path(__file__).resolve().parents[1] / "cabinet_studio" / "ui" / "library_rail.py"
    text = path.read_text(encoding="utf-8")
    # Build method labels in ops order.
    markers = [
        '"New build with AI"',
        '"Open"',
        '"Save"',
        '"Save as"',
        '"New"',
        '"Guide build"',
        '"AI suggest"',
        '"Apply all AI suggestions"',
        '"Drawings"',
        '"View drawings"',
        '"Programming"',
        '"Program stubs"',
        '"Desktop shortcut"',
        '"UL 508A review"',
    ]
    positions = [text.index(marker) for marker in markers]
    assert positions == sorted(positions)
