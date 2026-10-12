"""Hover help for every rung-editor control: plain words a beginner can follow."""

from __future__ import annotations

RUNG_HELP: dict[str, str] = {
    "Pop out editor": "Opens the rung editor in its own window you can drag anywhere, even to another monitor.",
    "Dock editor": "Puts the rung editor back into the strip under the ladder.",
    "Keep on top": "Keeps this editor window in front of the main window while you work.",
    "↶ Undo": "Takes back your last change to the ladder (Ctrl+Z).",
    "↷ Redo": "Puts back the change you just undid (Ctrl+Y).",
    "Contact": "Pick the input or bit this rung checks. NO (normally open, XIC) passes power when the tag is ON; "
               "NC (normally closed, XIO) passes power when it is OFF.",
    "Coil": "Pick the output or bit this rung turns ON when power reaches the end of the rung.",
    "Comment": "A note for this rung - what it does in plain words. It prints with the ladder.",
    "Timer": "Timer type and its name and preset time. TON waits before turning ON, TOF waits before turning OFF, "
             "RTO keeps its time when the rung goes false.",
    "Counter": "Counter type with its name and preset. CTU counts up, CTD counts down, RES resets it to zero.",
    "Compare A op B [C]": "Compares two values: op is EQU, NEQ, GRT, GEQ, LES or LEQ. A and B are tags or numbers.",
    "Math op → dest": "Math on values (ADD, SUB, MUL, DIV...) with the answer stored in dest.",
    "One-shot": "ONS passes power for one scan only. OSR fires on the rising edge, OSF on the falling edge.",
    "AOI": "Name of an Add-On Instruction (a reusable block of logic) to drop into a rung.",
    "JSR→": "Name of the subroutine that Add JSR jumps to.",
    "Add rung": "Adds a new rung: the chosen Contact in series driving the chosen Coil.",
    "Add timer": "Adds a rung with the Contact driving a timer (type, name and preset from the Timer boxes).",
    "Add counter": "Adds a rung with the Contact driving a counter (type, name and preset from the Counter boxes).",
    "Add nested OR": "Adds a rung with a parallel branch, so either path can turn the Coil ON (like a seal-in).",
    "Add mid coil": "Adds a rung with an output in the middle, so logic continues after it to a second output.",
    "Add compare": "Adds a rung that turns the Coil ON when the compare (A op B) is true.",
    "Add math": "Adds a rung that does the math in the Math boxes and stores the answer in dest.",
    "Add LIM": "Adds a limit test: true when a value is between a low and a high limit.",
    "Add MEQ": "Adds a masked-equal test: compares only the bits picked by a mask.",
    "Add bitwise": "Adds a bitwise AND / OR / XOR of two values.",
    "Add AOI": "Adds a rung that calls the Add-On Instruction named in the AOI box.",
    "Add OTL": "Adds a latch: the Coil turns ON and stays ON until an OTU unlatches it.",
    "Add OTU": "Adds an unlatch: turns OFF a coil that an OTL latched ON.",
    "Add one-shot": "Adds a rung with the chosen one-shot so the Coil only fires for one scan per press.",
    "Add JSR": "Adds a Jump to Subroutine to the routine named in the JSR box.",
    "Add SBR": "Creates a new subroutine (a separate list of rungs you can jump to).",
    "Add RET": "Adds a Return - ends the subroutine and goes back to where it was called.",
    "Comment…": "Write or change the comment on the selected rung.",
    "Add series contact": "Adds the chosen Contact in series to the selected rung (one more condition).",
    "Delete rung": "Deletes the selected rung. Undo brings it back.",
    "Edit": "Copy, paste and reorder rungs or single instructions.",
    "Copy rung": "Copies the selected rung (Ctrl+C).",
    "Paste rung": "Pastes the copied rung after the selected one (Ctrl+V).",
    "Duplicate": "Makes a copy of the selected rung right below it.",
    "Move ↑": "Moves the selected rung up one place.",
    "Move ↓": "Moves the selected rung down one place.",
    "Copy instr…": "Copies one instruction from the selected rung so you can paste it into another rung.",
    "Paste instr": "Pastes the copied instruction into the selected rung (Ctrl+Shift+V).",
    "Delete instr": "Click one contact or coil on the ladder, then this deletes just that one - the rest of "
                    "the rung stays and re-connects. Right-click an instruction for more choices.",
    "Replace instr": "Click one contact or coil on the ladder, then this swaps it for the Contact (or Coil) "
                     "picked above, in the same spot on the same rung.",
}


def rung_help(text: str) -> str:
    return RUNG_HELP.get(text, "")
