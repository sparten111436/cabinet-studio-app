# Lesson (v0.3.18): the guard only protects what it can see — account for every object

**Context.** v0.3.17 checked every imported rung against its LD wiring exactly (truth table/BDD).
Audit still found unsafe imports, and none of them beat that check. They went around it:

- a rung whose left rail was deleted was never built, so nothing checked it (NEW-8);
- routine bodies came only from metadata JSON, which nothing checked (Audit routine repro);
- PT/PV values that the importer did not understand became 0 or the doc-note value (NEW-9);
- a coil carrying a forged `ONESHOT-OUTPUT` note was treated as "absorbed" and dropped
  (found while building the v0.3.18 mutation tests);
- a contact with an erased tag was dropped, which made its coil unconditional (found while
  probing the NEW-8 accounting backstop);
- force, clear-forces and scan tick ran scans without going through `sim_blockers` (NEW-10).

**Lesson.** A verifier is only as good as its inventory. Every input object has to end up
in one of three places: an imported rung that has been **verified**, an explicit **refusal**,
or a **warning** that names it. Anything that drops out silently (skipped, defaulted, "absorbed",
taken from metadata) is a hole in the guard, however exact the guard is.

**Practice adopted in v0.3.18**
1. Count objects before and after: unreachable LD objects refuse the file; every rail must
   yield a rung, or a warning saying why it did not (an empty or contact-only network).
2. Metadata may *describe* but never *decide*. Routines are exported as real LD networks and
   verified, and the wiring wins. A routine that exists only in metadata gets a loud warning
   (older files) or refuses (files that should carry wiring). Aliases are flagged as unverified.
3. Never default a number you could not parse. Use the full IEC grammar, keep a tag as a tag,
   and refuse anything else. The simulator reads the tag's value, or refuses to run.
4. A note (`ONESHOT-OUTPUT`, doc `pt_ms=`) is only a hint. Structure decides whether a coil is
   absorbed. The note never does.
5. Gate every entry point, not only the obvious ones (Run/Step **and** force/clear/tick), and
   make the gate fail **closed**.
6. For each fix, write a mutation that reverts it and confirm a test catches it. Keep a
   backstop with no reachable input as defence in depth, and say so in the report: an
   uncaught mutation on a backstop is a documented gap, not a test pass.
