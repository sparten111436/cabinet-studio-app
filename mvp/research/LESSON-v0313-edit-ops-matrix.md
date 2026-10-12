# Lesson (v0.3.13) — continuous learning

**When a fix wires legacy fields into stored `elements`, also test every edit op on every rung shape.**

REG-1 fixed MotorStarter (OR/seal) by syncing `series` → `elements`. That same sync treated compare/math/OTL/oneshot as "outputs", so UI "Add series contact" (built from empty legacy `series`) **replaced** the enable contact (REG-2). A MotorStarter-only test greenlighted a regression on 14/36 rungs.

**Gate:** one parameterized matrix — each edit op × all template/UI rungs — asserting original contacts survive and sim still runs with the new contact TRUE. That would have caught REG-1 and REG-2 before Audit.
