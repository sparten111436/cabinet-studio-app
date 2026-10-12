# Lesson — v0.3.16: verify-and-refuse beats patching heuristics (H-DEEP)

**What happened.** v0.3.13 → v0.3.15 each patched the hint-less PLCopen importer's
breadth-first walk for one more nesting shape (nested OR, outer join, REG-5). Each
patch passed my fuzz (one nesting level), and each one broke a deeper shape somewhere
else. Audit found the v0.3.15 cluster path silently dropped the innermost OR at 3+ OR
levels — in the UNSAFE direction (Remote+Perm energized M with no key switch).

**What fixed it.**
1. **A principled rebuild** (`services/plcopen_graph.py`): dominator-based
   series-parallel decomposition with virtual join nodes for fan-in sets. Any depth;
   linear for Cabinet Studio exports; contacts may repeat for odd third-party wiring,
   coils/blocks never do.
2. **An independent guard on the RESULT, not the algorithm**: a bit-parallel truth table
   of the LD wiring vs the rebuilt elements, node-to-node (power into every coil and
   block, block outputs as free inputs). Any mismatch → `ValueError`, nothing imported,
   clear UI message. The guard also re-checks Cabinet Studio's own hint, so a file edited
   elsewhere with a stale hint follows the wiring instead of the hint.
3. **Tests built to break it**: Audit's fresh-seed generator at depth 1–4 with
   new seeds, the exact per-case regressions from Audit's diff, mutation proofs
   (guard disabled / rebuild disabled / stale hint trusted all fail tests).

**Rules I keep.**
- When a heuristic keeps regressing per case, stop patching. Add a check that
  verifies the output against the source, and refuse whenever the check fails.
- Run a fuzz at a higher depth than the bug report. Use seeds you have never seen,
  and diff per case against the previous builds.
- Prefer a refusal over a silently wrong import, and say so in the UI.
- Source-grep tests are not proofs. Render the real print or drive the real viewer instead.
