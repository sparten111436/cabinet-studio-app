"""UL 508A design review flags an incomplete cabinet without claiming a listing."""

from pathlib import Path

from cabinet_studio.models.project import PlacedItem
from cabinet_studio.services.layouts import new_blank_project
from cabinet_studio.services.library_loader import load_library
from cabinet_studio.services.standards import default_profile
from cabinet_studio.services.suggestions import suggest_device
from cabinet_studio.services.ul508a import DESIGN_AID_DISCLAIMER, REVIEW_TITLE, review_ul508a


def test_incomplete_project_produces_missing_checks():
    library = load_library()
    findings = review_ul508a(new_blank_project(), library, default_profile())
    by_id = {item.check_id: item for item in findings}
    assert set(by_id) >= {
        "UL508A-DISC-01",
        "UL508A-BCP-01",
        "UL508A-SEP-01",
        "UL508A-WCLR-01",
        "UL508A-GND-01",
        "UL508A-ENC-01",
        "UL508A-SCCR-01",
        "UL508A-OVL-01",
        "UL508A-FLD-01",
    }
    assert by_id["UL508A-DISC-01"].status == "missing"
    assert by_id["UL508A-ENC-01"].status == "missing"
    assert by_id["UL508A-SCCR-01"].status == "missing"
    assert by_id["UL508A-OVL-01"].status == "pass"
    assert all(item.check_id.startswith("UL508A-") for item in findings)
    assert "UL 508A" in REVIEW_TITLE
    assert "formal UL evaluation" in DESIGN_AID_DISCLAIMER


def test_motor_without_fla_is_a_missing_overload_check():
    library = load_library()
    project = new_blank_project()
    suggestion = suggest_device(library, default_profile(), project, "motor", {"supply_voltage": "480 VAC"})
    project.items.append(
        PlacedItem(
            id="m1",
            library_id=suggestion.catalog_id,
            type_id="motor",
            x=80,
            y=80,
            fields=dict(suggestion.fields),
        )
    )
    findings = {item.check_id: item for item in review_ul508a(project, library, default_profile())}
    assert findings["UL508A-OVL-01"].status == "missing"
    assert "FLA" in findings["UL508A-OVL-01"].title


def test_color_mismatch_warns_and_a_special_device_is_skipped():
    library = load_library()
    profile = default_profile()
    project = new_blank_project()
    project.interview = {"control_voltage": "24 VDC"}
    suggestion = suggest_device(library, profile, project, "sensor", project.interview)
    fields = dict(suggestion.fields)
    fields["wire_color"] = "White"
    project.items.append(
        PlacedItem(id="s1", library_id=suggestion.catalog_id, type_id="sensor", x=80, y=80, fields=fields)
    )
    warned = review_ul508a(project, library, profile)
    color = next(item for item in warned if item.check_id == "UL508A-WCLR-01")
    assert color.status == "warn"

    fields["nonstandard"] = "Yes"
    project.items[0].fields = fields
    skipped = next(
        item for item in review_ul508a(project, library, profile) if item.check_id == "UL508A-WCLR-01"
    )
    assert skipped.status == "pass"
    assert "special" in skipped.detail.lower()


def test_filled_interview_can_pass_the_advisory_checks():
    library = load_library()
    project = new_blank_project()
    project.interview = {
        "duty": "Spare panel",
        "supply_voltage": "480 VAC",
        "control_voltage": "24 VDC",
        "environment": "Indoor dry",
        "enclosure_type": "NEMA 12",
        "grounding": "Ground bar bonded to the enclosure stud.",
        "sccr": "5 kA placeholder, confirm with the utility.",
        "disconnect": "Yes",
        "branch_protection": "Yes",
        "power_control_separation": "Separated in the enclosure",
        "field_wiring": "Identified on a terminal block",
    }
    findings = {item.check_id: item for item in review_ul508a(project, library, default_profile())}
    assert findings["UL508A-DISC-01"].status == "pass"
    assert findings["UL508A-BCP-01"].status == "pass"
    assert findings["UL508A-SEP-01"].status == "pass"
    assert findings["UL508A-GND-01"].status == "pass"
    assert findings["UL508A-ENC-01"].status == "pass"
    assert findings["UL508A-SCCR-01"].status == "pass"
    assert findings["UL508A-FLD-01"].status == "pass"
    assert findings["UL508A-SCCR-01"].advisory is True


def test_module_does_not_name_the_old_ul_508_standard():
    text = Path("cabinet_studio/services/ul508a.py").read_text(encoding="utf-8")
    text = text.replace("UL 508A", "").replace("UL508A", "")
    assert "UL 508" not in text
    assert "UL508" not in text
    assert "certified" not in text.lower()
