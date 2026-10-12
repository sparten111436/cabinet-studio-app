# Lesson (v0.3.14) — continuous learning

## What bit us
1. **REG-3:** Fixing REG-2 by deriving series from `program_rung_to_elements` then writing `edit_rung(series=…)` left classic `parallel[[A]]` in place. Set-based “nothing lost” tests stayed green while IR/print showed `A·A·GUARD`. A follow-on `normally_closed` edit then made the rung never true.
2. **REG-4:** Putting design-aid `#` rows *above* the CSV header satisfied a substring search and broke every generic `DictReader` / `Sniffer`.
3. **Weak nested-OR test:** A fixture comment containing `"nested"` made the warn-fallback branch always succeed, so a mutant that disabled reconstruction still passed.

## Rules to keep
- Assert **contact multisets** (and one follow-on edit) for every storage form, including classic legacy rungs with no `elements`.
- Prefer **elements rebuild** (`elements_to_program_rung`) for structural UI ops — same path as parallel — instead of layering legacy fields.
- Export format checks must use a **consumer** (DictReader, XSD, PDF page text), not only needles.
- Warn/fallback tests must use **neutral fixture comments** and always assert the educational truth table.
