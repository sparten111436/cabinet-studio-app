"""Nested-OR printable SVG geometry (v0.3.5)."""

from __future__ import annotations

from cabinet_studio.services.ladder_print import (
    ladder_program_to_svg,
    nested_or_geometry_metrics,
    or_branch_rows,
    svg_rung_from_elements,
)
from cabinet_studio.services.programming import add_nested_or_rung, empty_program


def _nested_elements():
    return [
        {"kind": "contact", "var": "A", "form": "NO"},
        {
            "kind": "or",
            "branches": [
                [{"kind": "contact", "var": "B", "form": "NO"}],
                [
                    {"kind": "contact", "var": "C", "form": "NO"},
                    {
                        "kind": "or",
                        "branches": [
                            [{"kind": "contact", "var": "D", "form": "NO"}],
                            [{"kind": "contact", "var": "E", "form": "NO"}],
                        ],
                    },
                ],
            ],
        },
        {"kind": "coil", "var": "OUT", "form": "normal"},
    ]


def test_or_branch_rows_counts_nested():
    assert or_branch_rows(_nested_elements()) >= 3


def test_nested_or_print_has_vertical_join_rails():
    metrics = nested_or_geometry_metrics(_nested_elements())
    assert metrics["rows"] >= 3
    assert metrics["vertical_rails"] >= 2
    assert metrics["has_nested_marker"] is True
    assert "D" in metrics["svg"] and "E" in metrics["svg"]


def test_program_print_svg_includes_nested_tags():
    prog = add_nested_or_rung(
        empty_program(),
        lead_tag="A",
        or_branches=[
            [{"tag": "B", "normally_closed": False}],
            [
                {"tag": "C", "normally_closed": False},
                {
                    "kind": "or",
                    "branches": [
                        [{"kind": "contact", "var": "D", "form": "NO"}],
                        [{"kind": "contact", "var": "E", "form": "NO"}],
                    ],
                },
            ],
        ],
        coil_tag="OUT",
    )
    svg, w, h = ladder_program_to_svg(prog["rungs"])
    assert w == 1000
    assert h > 200
    for tag in ("A", "B", "C", "D", "E", "OUT", "nested-OR"):
        assert tag in svg


def test_flat_rung_still_prints():
    parts, block_h = svg_rung_from_elements(
        [
            {"kind": "contact", "var": "PB", "form": "NO"},
            {"kind": "coil", "var": "CR1", "form": "set"},
        ]
    )
    svg = "\n".join(parts)
    assert "PB" in svg and "CR1" in svg and "S" in svg
    assert block_h > 50
