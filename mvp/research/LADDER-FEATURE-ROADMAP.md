# Cabinet Studio Educational Ladder — Feature Roadmap

**Fleet:** Profundity Home One  
**Owner:** Code Cylinder (ladder UX / IR)  
**Date:** 2026-10-05 (America/Chicago) — updated for v0.3.11  
**Product:** Cabinet Studio educational PLC programming (UL 508A design-aid companion)  
**Constraints:** First-party IR + scan sim + print + PLCopen XML. No GPL editor embeds. No live PLC download. No `.RSS` / MicroLogix claims. Ideas only from commercial editors — **no proprietary code or assets**.

---

## 0. Already built (as of v0.3.11)

- **v0.3.11 correctness + safety hotfix** — seal-in RT safe; OffDelayStop/JogOrRun/TwoHandStart fixed; Audit P1-1…P1-8; Deflector gates; print P2s; TC6 XSD structural; design-aid notes.


| Feature | Status | Notes |
|---------|--------|-------|
| Ladder IR (`cabinet-studio-ladder`) | **built** | Contacts, coils, series/parallel, nested OR, mid-rung coils |
| Scan sim (`scan_once`) + Force inputs | **built** | Educational cycle; force wins over OTE |
| PLCopen XML export/import | **built** | Educational TC6-style interchange |
| Timers TON / TOF / RTO | **built** | ACC/PT/DN/TT members |
| Counters CTU / CTD / RES / LOAD | **built** | ACC/PRE/DN/CU/CD/OV/UN |
| Nested OR branches | **built** (sim/IR/PLCopen/UI) | Print SVG geometry upgraded in **v0.3.5** |
| Mid-rung coils | **built** | OTE passthrough continuity |
| Programming toolbar horizontal scroll | **built** | Top + bottom bars |
| Print (basic ladder SVG) | **built** | Nested-OR true branch geometry → **v0.3.5** |
| Pop-out Programming canvas | **built** | Keep forever |
| Interview / drawings / cabinet bind | **built** | Outside this roadmap but preserved |
| Compare / Math+MOV / OTL+OTU / nested-OR print | **built in 0.3.5** | 0.3.6 fixed the Add compare/math/OTL/OTU buttons (they crashed on a bad widget name) |
| One-shots ONS / OSR / OSF | **built in 0.3.6** | IR `oneshot` element; sim edge logic; print; PLCopen as IEC R_TRIG / F_TRIG; text `ONS[S]` / `OSR[S→O]` |
| Live power-flow highlight + Force polish | **built in 0.3.6** | Per-element `power_flow` {in,cond,out}; green live wires/contacts/coils/boxes; F0/F1 force markers; Clear forces |
| Undo / redo | **built in 0.3.6** | `services/ladder_history.py` (100 steps); ↶/↷ buttons + Ctrl+Z / Ctrl+Y / Ctrl+Shift+Z (main + pop-out + floating editor) |
| Rich rung comments + instruction notes | **built in 0.3.6** | Multi-line comments (title + body) on screen, print, text and PLCopen `<comment>`; per-instruction notes |
| Floating rung editor window | **built in 0.3.6** | Pop out editor → movable non-modal window; Keep on top (transient to the ladder pop-out + topmost); remembers size/position and floating state; edits redraw the ladder live |
| Copy / paste rungs & instructions | **built in 0.3.7** | `services/ladder_tools.py`; lossless JSON clip on the system clipboard (`cabinet-studio-ladder-clip`); paste after selection with fresh ids; Duplicate; Move ↑/↓; Copy instr… chooser → Paste instr (inputs go before the first output, outputs append); undoable |
| Verify / error-check panel | **built in 0.3.7** | Non-modal Verify (F7) window, live-refreshes after edits, click a line to jump to the rung. Errors: empty rung, no output, missing operand, timer PRE 0, DIV by 0, literal dest, duplicate one-shot storage bit (or storage written elsewhere), duplicate timer instance, timer/counter name clash, undefined T/C member. Warnings: missing tag, output device read but never driven, duplicate OTE, OTL w/o OTU, CTU/CTD PRE ≤ 0, RES/LOAD on unknown counter. Info: unconditional rung, cabinet output with no coil, numeric never written |
| Tag database + descriptions + where-used | **built in 0.3.7** | Tags / X-ref window: every device + program tag (class/type/address/uses), editable descriptions (`program["tag_descriptions"]`, undoable), declare new tags, filter, where-used list → jump. Descriptions round-trip through PLCopen variable `<documentation>` (described numeric tags export as REAL); print page gains a Tag cross-reference table |
| Find / replace tags | **built in 0.3.7** | Ctrl+F / Ctrl+H window; whole-tag or substring find, match case; Replace all / in selected rung; members follow (T1 → T2 renames T1.DN), CPT expressions too; descriptions move with a rename; tag-name validation |
| Keyboard shortcuts | **built in 0.3.7** | Ctrl+C/V/D, Ctrl+Shift+C/V, Delete, ↑/↓/Home/End, Ctrl+↑/↓, Ctrl+F/H/T/E, F7, F5/Shift+F5/F10, F1 list; bound on main, ladder pop-out, floating editor and tool windows; skipped while typing in a field |
| Floating Force / I/O strip | **built in 0.3.7** | Float I/O → movable non-modal window (remembers geometry + floating state); force toggles keep working live |
| Watch / trend window | **built in 0.3.8** | Samples during Simulate/Step; plot ACC / BOOL / numeric tags |
| JSR / SBR / RET subroutines | **built in 0.3.8** | Named routines + educational call/return; PLCopen meta stamp |
| Tag aliases | **built in 0.3.8** | `program["tag_aliases"]`; sim resolve; Tags window Set alias |
| Verify quick-fixes + instruction highlight | **built in 0.3.8** | Fix button on issues; yellow rung highlight + scroll-to |
| Tighter print page packing | **built in 0.3.8** | Reduced gaps; multi-page HTML sheets with page-break |
| LIM / MEQ compares | **built in 0.3.9** | LIM Low≤Test≤High; MEQ (Source&Mask)==(Compare&Mask); hex literals; print/PLCopen IN3 |
| Bitwise AND / OR / XOR / NOT | **built in 0.3.9** | Educational DINT bitwise via math box; Add bitwise button |
| Richer CPT precedence | **built in 0.3.9** | Safe recursive-descent: unary −, */ , +− , parentheses — no Python eval |
| Educational AOI / FB templates | **built in 0.3.9**; **expanded 0.3.10** | 0.3.9 six templates; 0.3.10 adds ForwardReverse, OffDelayStop, PulseExtend, TwoHandStart, EstopInterlock, ValveCycle, BatchReset, JogOrRun, ScaleSetpoint |
| Watch / Trend polish | **built in 0.3.10** | Pause/resume; series labels; color swatches + last-value legend; Export CSV |
| OpenPLC Runtime sidecar (research) | **documented 0.3.10** | `research/OPENPLC-RUNTIME-SIDECAR.md` — MIT Runtime as future external process only; no Editor embed; no launcher this batch |
| **UI gate test** (process) | **built in 0.3.7** | `tests/test_programming_ui_gate.py` — headless Tk: every toolbar / sim / nav button, every Add-instruction (docked + floating), rung editor open/edit/close, full button sweep; asserts no exception (direct or Tk callback). **Mandatory for every future batch.** Already caught + fixed two latent bugs (X11 wheel lambda arity; Comment… Save on a deleted rung) |

---

## 1. Research sources (ideas only)

Public feature vocabularies studied (documentation / marketing / standards summaries — **not** copied implementations):

| Editor | Inspiration taken |
|--------|-------------------|
| **Studio 5000 Logix Designer** | EQU/NEQ/GRT/…, ADD/SUB/MUL/DIV, MOV, CPT, OTL/OTU, ONS/OSR/OSF, JSR/SBR, tag DB, cross-ref, online force + power-flow, watch |
| **CCW (Connected Components Workbench)** | Micro800-style timer/counter members, compare/math boxes, educational side-by-side for Warren |
| **TIA Portal** | LAD contacts/coils, IEC timers, verify/error list, watch tables, online monitoring look-and-feel |
| **CODESYS** | IEC LD + FBD peers, PLCopen XML, soft PLC sim concepts, variable declaration view |
| **OpenPLC Editor** | Educational IEC blocks, free toolchain peer (Editor stays **external**; we do not embed GPL) |
| **Do-more Designer** | Mnemonic clarity, rung comments, stage/program organization ideas |
| **CLICK** | Simple instruction palette, beginner-friendly dialogs |
| **AutomationDirect Productivity** | Tag-name programming, cross-reference, easy math/compare UX |

IEC 61131-3 maps (educational aliases we expose): EQ↔EQU, NE↔NEQ, GT↔GRT, LT↔LES, GE↔GEQ, LE↔LEQ, MOVE↔MOV, SR/RS↔OTL/OTU, R_TRIG/F_TRIG↔OSR/OSF.

---

## 2. Ranked roadmap (highest value first for Warren)

Value = helps cabinet builders learn real shop PLC habits while staying educational. Difficulty: S / M / L / XL.

| Rank | Feature | Inspired by | Value to Warren | Diff | Status |
|------|---------|-------------|-----------------|------|--------|
| 1 | **Nested-OR printable SVG** (true branch geometry) | CCW / Studio / OpenPLC print views | Shop print matches on-screen nested logic | M | **built in 0.3.5** |
| 2 | **Compare** EQU/NEQ/GRT/LES/GEQ/LEQ | Studio / CCW / TIA / CODESYS | Numeric interlocks (levels, counts vs setpoints) | M | **built in 0.3.5** |
| 3 | **Math + MOV** ADD/SUB/MUL/DIV + MOV (+ CPT if fits) | Studio / CCW / Productivity | Scale, accumulate, copy setpoints | M | **built in 0.3.5** |
| 4 | **Latches OTL/OTU** (set/reset coils) | Studio / CCW / IEC SR-RS | Seal-less memory bits; already in sim forms | S | **built in 0.3.5** |
| 5 | **One-shots ONS/OSR/OSF** | Studio / Siemens P/N / IEC R_TRIG | Edge-triggered starts; counters of events | M | **built in 0.3.6** |
| 6 | **Live power-flow highlight + Force polish** | Studio online / TIA monitor | See why a coil is off during Simulate | M | **built in 0.3.6** |
| 7 | **Undo / redo** | All modern editors | Safe experimentation | M | **built in 0.3.6** |
| 8 | **Rung comments (richer) + instruction comments** | Do-more / Studio / CLICK | Document design-aid intent on prints | S | **built in 0.3.6** |
| 9 | **Copy / paste rungs & instructions** | All | Fast pattern reuse across cabinets | M | **built in 0.3.7** |
| 10 | **Verify / error panel** | TIA / Studio / CODESYS | Catch missing tags, open coils, bad PRE | M | **built in 0.3.7** |
| 11 | **Tag database** (descriptions, types) | Studio / Productivity / CODESYS | Matches cabinet device tags + numeric tags | L | **built in 0.3.7** (descriptions/types/declare); **aliases → 0.3.8** |
| 12 | **Cross-reference view** | Studio / Productivity | Where is this tag used? | L | **built in 0.3.7** (window + print table) |
| 13 | **Search / replace tags** | All | Rename after interview changes | M | **built in 0.3.7** |
| 14 | **Keyboard shortcuts** | All | Power-user speed | S | **built in 0.3.7** |
| 14a | **Floating Force / I/O strip** | Studio / TIA watch panes | Force inputs from a second monitor | S | **built in 0.3.7** |
| 15 | **Watch / trend window** | Studio / TIA / CODESYS | Plot ACC / numeric tags while sim runs | L | **built in 0.3.8** |
| 16 | **JSR / SBR / RET subroutines** | Studio / CCW / CODESYS | Modular programs for multi-station cells | L | **built in 0.3.8** |
| 17 | **CPT compute expression** | Studio | Compact math expressions | M | **built in 0.3.5**; **full precedence in 0.3.9** |
| 17a | **Tag aliases** (alias → device tag) | Studio alias tags / Productivity | Friendly names over cabinet I/O | M | **built in 0.3.8** |
| 17b | **Verify: jump-to-instruction highlight + quick fixes** (e.g. "make storage bit unique") | TIA error list / Studio | Fix issues in one click | M | **built in 0.3.8** |
| 18 | **LIM / MEQ / bitwise AND OR XOR** | Studio / CCW | Advanced compares / masks | M | **built in 0.3.9** |
| 19 | **AOI / FB templates (educational)** | Studio AOI / CODESYS FB | Reusable motor starter FB | L | **built in 0.3.9**; **+9 cabinet patterns in 0.3.10** |
| 19a | **Watch / Trend polish** | Studio / TIA watch | Pause, labels, CSV export | S | **built in 0.3.10** |
| 20 | **Optional OpenPLC Runtime sidecar** | OpenPLC (MIT runtime only) | Soft-PLC run — **no Editor embed** | XL | **research note 0.3.10**; implement later |

---

## 3. Batch plan

| Version | Scope |
|---------|--------|
| **0.3.5** | Nested-OR print SVG + compares + math/MOV + OTL/OTU UI; pytest; try-build only (no promote) |
| **0.3.6** (built, box source only) | One-shots ONS/OSR/OSF; power-flow highlight; undo/redo; rich rung comments + instruction notes; floating rung editor; compare/math/OTL/OTU button fix. Windows exe build deferred until Warren returns |
| **0.3.7** (built, box source only) | Copy/paste rungs & instructions (+ duplicate, move); verify panel; tag DB + descriptions + cross-ref (window, print, PLCopen); find/replace; keyboard shortcuts; floating Force/I-O strip; mandatory headless UI gate test. Windows exe build deferred until Warren returns |
| **0.3.8** (built, box source only) | Watch/trend window; JSR/SBR/RET; tag aliases; verify quick-fixes + instruction highlight; tighter print page packing. Windows exe build deferred until Warren returns |
| **0.3.9** (built, box source only) | LIM/MEQ; bitwise AND/OR/XOR/NOT; CPT precedence parser; educational AOI/FB templates. Windows exe deferred until Warren returns |
| **0.3.10** (built, box source only) | +9 AOI/FB cabinet templates; Watch pause/labels/CSV; OpenPLC Runtime sidecar research note. Windows exe deferred until Warren returns |
| **0.3.11** (built, box source only — **correctness + safety hotfix**) | Audit/Deflector P1s: lossless IR; seal-in PLCopen RT (no STOP\|STOP collapse); OR-branch actuators; address/initialValue; LIM inverted; DINT typed math; TC6 XSD gate; OffDelayStop (no self-seal); JogOrRun RunMode (momentary jog + Stop dominance); TwoHandStart ~0.5s skew lockout; design-aid NFPA 79/ISO 13849 notes; print P2s (continuous #, packing, footer, routines, ladder-logic.txt); per-template native+RT safety tests; fixture paths repo-relative. **No new features.** No PC promote until Audit+Deflector PASS |

---

## 4. Non-goals (standing)

- No Rockwell `.RSS` / MicroLogix / RSLogix compatibility claims  
- No live download to hardware  
- No embedding GPL editors (OpenPLC Editor, Beremiz IDE, MatIEC, LDmicro)  
- No copying proprietary UI assets or instruction artwork  
- Preserve PC `main_window.py`, sticky `library_rail.py`, outermost `paths.py`

---

## 5. Acceptance per instruction family

Every new instruction must ship with:

1. IR normalize + program dict round-trip  
2. `scan_once` semantics (CCW/Micro800-style educational)  
3. Print SVG symbol  
4. PLCopen XML export/import (educational extension where TC6 is loose)  
5. pytest coverage; keep prior ladder tests green  
6. **UI gate** (`tests/test_programming_ui_gate.py`, from 0.3.7): any new toolbar / Add button must be added to the gate's expected sets and invoke without exception  

---

*End of roadmap — update Status column as batches land.*
