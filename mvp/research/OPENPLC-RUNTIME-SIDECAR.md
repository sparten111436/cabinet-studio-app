# OpenPLC Runtime as a future **sidecar** (research note)

**Date:** 2026-10-05 (America/Chicago)  
**Fleet:** Profundity Home One · Code Cylinder  
**Status:** Research only for Cabinet Studio **v0.3.10** — **not implemented** in this batch.

## What this is (and is not)

| Piece | License (public docs) | Cabinet Studio stance |
|-------|----------------------|------------------------|
| **OpenPLC Runtime** | MIT (soft-PLC engine) | **Allowed to consider** later as an optional **external sidecar** process |
| **OpenPLC Editor** | GPL | **Do not embed.** Never ship or link the Editor inside CS. Learners may install it separately if they want. |

Standing product rules stay: first-party IR + scan sim + print + PLCopen XML inside CS; no GPL editor embeds; no live download to hardware; educational design-aid only.

## Why a sidecar (not an embed)

- Keeps Cabinet Studio’s educational ladder UI / IR / Simulate independent and free of GPL contagion.
- A sidecar would be a **separate process** Warren could start/stop (like pointing CS at a local soft-PLC), not a widget inside Programming.
- Interchange remains **PLCopen XML** (and CS’s own program JSON) — Runtime would consume exported logic, not replace our editor.

## Possible future shape (ideas only)

1. **Export** educational program → PLCopen XML (already built).
2. **Optional helper** (docs + script later): launch OpenPLC Runtime with a mapped project folder / slave config — out of process.
3. **Optional status poll** (Modbus/TCP or Runtime API if documented) for a “sidecar online” light — read-only, educational.
4. **Never:** fork Editor UI into Tk; never claim Rockwell / MicroLogix compatibility; never auto-download firmware to a panel PLC.

## Fit with Warren’s cabinets

Useful for: students who want a free soft-PLC after building a Weld Place / motor starter program in CS.  
Not useful for: UL 508A certification (CS remains design-aid), or replacing CCW side-by-side learning (CCW stays the Micro800 peer).

## Decision for 0.3.10

- Documented here.
- **No Runtime stub, no process launcher, no dependency added** in this batch.
- Revisit when nested OR / FB templates / watch polish are stable on PC and Warren asks for soft-PLC try.

*End of note.*
