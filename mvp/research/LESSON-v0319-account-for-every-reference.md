# Lesson (v0.3.19): account for every reference — and never guess the rail

**Context.** v0.3.18 made every LD *object* end up in a verified rung, a refusal or a warning.
Deflector still found two P1s, both present since 0.3.17, and Raddus's deleted-object fuzz
then found 358 more accepted-but-changed variants in 0.3.18 (0 in 0.3.19). None of them beat
the truth-table check. Each one was a *reference* the importer quietly explained away:

- **no left rail (N4f):** the single "missing" source id was assumed to be the rail. When the
  deleted object was the first series Stop / E-stop contact, the rung imported without it and
  was labelled verified;
- **wire to a missing localId (DANGLE):** the connection was skipped, so a reset coil lost its
  E-stop branch and no warning was given;
- **dead-end contact:** a contact that drives nothing was pruned with a warning. But a deleted
  wire looks exactly like that: an OR branch into a reset coil, or a coil rewired around its
  Stop. The rung imported without the branch or the Stop;
- **one-shot output from a note:** with the output coil deleted, the `output=` note rebuilt it;
- **wire out of a right rail:** the rebuild crashed (KeyError), when it should have refused.

**Lesson.** Inventory the edges as well as the nodes. Every `<connection refLocalId>` must
point to exactly one object that exists in the same body and can legally drive it. Every
powered object must lead to an output. When the file leaves two readings open, such as "this
id was the rail" versus "this id was the Stop", the importer cannot know which is true. The
only safe answer is to refuse and name what it saw. Being exact about the part you understood
does not excuse a guess about the part you did not.

**Practice adopted in v0.3.19**
1. Refuse the whole file, naming the rung and object, for: no left rail; a wire to a missing
   localId (including a reference into another body); a duplicate localId; a wire that starts
   at a right rail; a powered contact, or a powered condition block (compare, ONS), that
   drives no coil or block; a one-shot whose noted output coil is not wired to its Q.
2. Give supporting evidence in the refusal. A declared BOOL input that no contact uses is
   named as "a deleted contact (e.g. a Stop or E-stop) is likely".
3. When a hint or metadata copy disagrees with the wiring, the wiring still wins. The warning
   now names what the copy has and the wiring lacks (for example "The hint has <contact> M1
   that the wiring does NOT have").
4. Fuzz by deletion as well as by generation. Delete every object and every link in turn,
   with and without the hint. Each variant must either refuse or import with logic identical
   to the source. Run the same fuzz against the previous release to show it finds real bugs
   (on the same 37 sources: 0.3.18 had 392 accepted-changed, 0.3.19 has 0).
5. The limit is stated, not hidden. Deleting an object together with every wire to it leaves
   a well-formed *different* program. Without the hint, nothing can tell it apart from an
   authored one. With the hint, it imports with a warning that names the object.
6. Account for every attribute as well as every object (Raddus attribute-mutation fuzz). The
   importer now reads the TC6 vocabulary through a strict allowlist (`check_tc6_vocabulary`).
   Every attribute, element, block typeName, pin and pin flag is either modelled exactly,
   whitelisted as cosmetic (localId, width/height, position, executionOrderId, globalId,
   documentation, addData, a pin name on a wire from a single-output contact, coil or rail,
   and the legacy 0.3.9/0.3.10 `variable` attribute when it equals the `<variable>` element),
   or refused by name. Examples: edge="rising", a negated block pin, a TP or CTUD block, a
   jump, a second POU, retain lists, two variables on one address, or a wire taking ET/ACC.
   Something both the guard and the rebuilder ignore cannot be caught by comparing the two.
   The fuzz injects each unmodelled item into every source, with and without the hint
   (15,178 variants). 0.3.18 accepted 8,446 of the semantic ones, 146 of them with changed
   logic. 0.3.19 accepts 0, and none of the equivalent variants is refused. When widening
   the allowlist, whitelist only what cannot change logic. Never loosen it for real semantics.
