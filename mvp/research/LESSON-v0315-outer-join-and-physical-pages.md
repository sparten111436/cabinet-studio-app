# Lesson v0.3.15 — "visited" is not "mine"; HTML pages are not paper pages

**Date:** 2026-10-05 (CT) · **Batch:** 0.3.15 (REG-5 P1 safety + N-2 + N-4)

## 1. REG-5: graph walks must test ownership, not visitation
The 0.3.14 hint-less importer continued a nested-OR branch past its join and
treated any *already visited* predecessor as harmless. The sibling top-level
branch (`PB_Start`) was visited first, so the OUTER join (`/PB_Stop`) looked like
"our" series contact and was pulled into the last OR branch — Start bypassed Stop.

**Rule:** only consume a join when **every** predecessor is one of this subgraph's
own ends (and afterwards, exactly the node just consumed). "Visited" says nothing
about *whose* node it is.

## 2. Test the safety invariant, not the shapes you thought of
Shape tests passed; per-case fuzz diff against the last PASS build exposed 15
ok→MISMATCH cases. 0.3.15 adds an invariant test (Raddus): random seal-in rungs
with /Stop at a random **top-level** position, nested ORs anywhere, hint stripped —
with Stop held the coil must **never** energize, Stop must stay top-level exactly
once, and native == imported over random sequences. Same invariant on every
template rung that has a top-level NC *stop* contact.

## 3. Pagination must be checked on rendered paper
Chunking PLC text by 45 *source* lines looked right in HTML (one footer per
`.page`) but wrapped lines overflowed onto footer-less physical pages. Now:
hard-wrap at a printable column budget, chunk by *visual* rows, and a test
renders the stress print with headless Chrome and asserts PDF pages == `.page`
blocks and UL exactly once per physical page.

## 4. Mutation-prove every new test
Each fix was reverted (0.3.14 file restored) and the new tests had to fail; the
Audit V4 (no pagination) and V5 (footer twice) mutants are caught too.
