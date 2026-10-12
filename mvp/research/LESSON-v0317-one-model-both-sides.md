# Lesson v0.3.17: a guard's two models must share one semantics, and must compare settings, not only power

**What went wrong in v0.3.16.** The verify-or-refuse guard evaluated the LD graph with "block output = free input"
but evaluated Cabinet Studio elements with "OR result clamped by its input power". For a compare inside an OR
branch after a series contact, those two models disagree. The guard refused 615 of 1,000 of our own hinted exports.
Separately, it compared only *power into* each coil or block. A stale or tampered hint could still change a coil
to set, or change a timer preset, and pass.

**Rule from now on.**
1. Write the block semantics once (`out = in AND f`, gated) and use that same definition on both sides of the
   equivalence check. The definition matches the scan simulator: compare = power AND condition, timer, counter and
   math pass power through, and ONS = power AND not-previous. It also matches IEC ENO and TON.Q.
2. An equivalence guard compares **behaviour-bearing settings** node to node: coil form, compare op and operands,
   timer type and PT, counter preset, math op and CPT expression, and one-shot type. Power alone is not enough.
3. Never sample and then accept. Below 20 inputs, use an exhaustive table. Above that, use an exact BDD. Past the
   BDD limits, refuse with a clear message.
4. Fuzz the guard on the **hinted** (lossless) path and on mixed block placements, not only on the hint-less
   plain-contact path the fix targeted. A run with "0 refused" is a sign the guard went unexercised.
5. Wiring is truth. The hint carries a hash of the rung body. Any edit to the body, or any mismatch between hint
   and wiring field by field, means the hint is ignored for that rung, and a warning names the rung.
