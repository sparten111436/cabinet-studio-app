# Cabinet Studio User Manual

Version 0.3.35 · Written for beginners · October 2026

> **Safety:** Cabinet Studio is a design aid. Its drawings are NOT A CERTIFIED UL 508A DRAWING. E-stop and safety functions must be hardwired or use rated safety relays (NFPA 79 / ISO 13849). The software is never the safety function. Read the [Safety page](#safety-read-this-first) before you build anything real.

## How to use this manual

This manual explains Cabinet Studio one small step at a time. You do not need to know anything about electrical cabinets or PLCs to start. Words that might be new are in the [Glossary](#glossary-words-you-will-see) at the end.

You will see four kinds of boxes:

> **What you'll see:** This box tells you what should appear on the screen after a step.

> **Tip:** This box gives a shortcut or a helpful idea.

> **Watch out:** This box warns you about a common mistake.

> **Safety:** This box is about keeping people safe. Never skip these.

Button names are written in **bold**, exactly as they appear in the program. Menus are written like **File > Save**, which means "click the File menu, then click Save".

Almost every button in Cabinet Studio has **hover help**. Rest your mouse pointer on a button for a second and a small yellow note explains what it does. If you are ever unsure, hover first.

## What is Cabinet Studio?

Factories use machines. Those machines are controlled by a metal box full of electrical parts, called a **control cabinet**. Inside the cabinet there is usually a small computer called a **PLC** that runs the machine, plus power supplies, breakers, motor starters, relays and rows of wire terminals. On the door there are buttons, lights, an emergency stop and sometimes a touch screen called an **HMI**.

Cabinet Studio helps you design all of that on your computer:

1. **Pick the parts** that go in the cabinet (or let the AI pick them for you).
2. **Make the drawings**: where each part sits on the metal backplate, how the power is wired, how the control buttons are wired, and a list of every wire.
3. **Write the PLC program** in ladder logic (a picture language that looks like a ladder).
4. **Test the program in a simulator** with a pretend machine, before you ever touch real equipment.
5. **Design the operator touch screen (HMI)** and test it with the simulator too.
6. **Export files** for the real PLC and HMI software from Allen-Bradley, Siemens or Omron.

Everything you make is saved in one project file that ends in `.cabinet.json`.

## Safety (read this first)

Please read this whole page. It is short and it matters.

1. **Design aid only.** Every sheet Cabinet Studio prints has this footer: `NOT A CERTIFIED UL 508A DRAWING. Design aid only.` That means a qualified person (a licensed electrician, a controls engineer or a UL 508A panel shop) must check the design before anyone builds it. The drawings help you think. They do not prove the cabinet is safe or legal.
2. **The software is never the safety function.** E-stop and safety functions must be hardwired or use rated safety relays (NFPA 79 / ISO 13849). An E-stop button must cut power through real wires and a safety relay, not through the PLC program and not through the HMI screen. Cabinet Studio's ladder programs and HMI screens only *show* the E-stop and light curtain status. They never control safety.
3. **The simulator is pretend.** When you click Run, nothing real moves. A program that works in the simulator can still be wrong on a real machine.
4. **Bench-test real PLC connections.** The live PLC link is a test tool (beta). Only connect to a PLC on a test bench, or to a machine you can see, that is safe, and where nobody can be hurt. Never test on a running production machine.
5. **Check part sizes with the maker.** Part outlines in the drawings are typical sizes. Before you order parts, cut holes in a door, or drill a backplate, check the exact dimensions on the maker's data sheet.
6. **Electricity can kill.** Never open a live cabinet. Only qualified people should wire or test real cabinets, following lock-out / tag-out rules.

> **Safety:** If you are a student, always work on real equipment with a teacher or qualified adult beside you.

## Installing Cabinet Studio

You need a 64-bit Windows 10 or Windows 11 computer. There are two ways to install. Pick one.

### Way 1: The installer (easiest)

1. Find the file `CabinetStudio-Setup-0.3.35.exe` (someone sent it to you, or you downloaded it).
2. Double-click it.
3. Windows may show a blue box that says **Windows protected your PC**. This happens because the program is not "code-signed" yet. It does not mean there is a virus.
   1. Click the small words **More info**.
   2. A new button appears: **Run anyway**. Click it.
4. Read the license and click **I accept the agreement**, then **Next**.
5. If you want an icon on your desktop, tick **Create a desktop shortcut**. Click **Next**, then **Install**.
6. Read the short "read me" screen, then click **Finish**. Leave **Launch Cabinet Studio** ticked if you want to start it right away.

> **What you'll see:** A new folder in your Start menu called **Cabinet Studio** with four entries: **Cabinet Studio**, **Cabinet Studio User Manual** (this manual), **Read me first**, and **Uninstall Cabinet Studio**.

> **Tip:** The installer does not need an administrator password. It installs only for you, in `%LOCALAPPDATA%\Programs\Cabinet Studio`.

### Way 2: The portable ZIP (no install)

1. Find `CabinetStudio-0.3.35-portable.zip`.
2. Right-click it and choose **Extract All...**. Pick a place you can find again, like your Documents folder.
3. Open the new `CabinetStudio` folder and double-click `CabinetStudio.exe`.
4. If you see **Windows protected your PC**, click **More info**, then **Run anyway**.

> **Watch out:** Keep the `_internal` folder next to `CabinetStudio.exe`. The program will not start without it. Do not move the .exe out of its folder; make a shortcut instead.

The ZIP also contains `README-FIRST.txt` and this manual (`Cabinet-Studio-User-Manual.html` and, when available, a PDF).

### Uninstalling

Open Windows **Settings > Apps**, find **Cabinet Studio 0.3.35** and click **Uninstall**. Your project files are **not** deleted (see [Where your files go](#where-your-files-go)).

## Opening the manual from inside the program

You can open this manual at any time:

- Click the **? Manual** button at the right end of the main toolbar (top of the main window), or
- Use the menu **Help > User manual** in the main window, or
- In the Programming page, use **Help > User manual**, or
- From the Windows Start menu, click **Cabinet Studio User Manual**.

The manual opens in your web browser. To print it, press **Ctrl+P** in the browser.

## First launch

1. Start Cabinet Studio from the Start menu, the desktop icon, or `CabinetStudio.exe`.
2. A dark welcome card (the "splash") appears with the words **CABINET STUDIO** and **click to continue**. Click it, or just wait.
3. The main window opens.

> **What you'll see:** A dark window. Across the top is a menu bar (**File, Edit, View, Tools, Help**) and a toolbar. On the left is a tall column of buttons (the library rail). In the middle is the cabinet area. On the right is the **INSPECTOR**. At the bottom is a status bar with hints like `Ctrl+S save  Ctrl+Z undo  double-click defines  Delete removes`.

> **Tip:** Want a light screen instead of dark? Click **☀ Light** at the right end of the toolbar. Click **☾ Dark** to go back. You can also use **View > Theme > Light / Dark / System**.

## The main window, piece by piece

### The menu bar

| Menu | What is inside |
|---|---|
| **File** | New project…, New from template…, New build with AI…, Open…, Save, Save As…, Program library…, Install desktop shortcut, Exit |
| **Edit** | Undo, Delete selected device, Add device… |
| **View** | Theme (Light / Dark / System), Project explorer, Compact library rail, View drawings |
| **Tools** | Generate drawings, Programming, Guide build, AI suggest devices, Apply all suggestions, UL 508A review |
| **Help** | User manual, Keyboard shortcuts, About Cabinet Studio |

### The toolbar

The row of buttons under the menu bar, from left to right:

- **New**, **Open**, **Save**: start, open or save a project.
- **Templates**: start a new cabinet from a ready-made template (see [Starting from a template](#starting-from-a-template)).
- **Undo**: take back your last change.
- **Drawings**: make (generate) the drawing sheets.
- **View drawings**: look at the sheets.
- **Programming**: open the ladder program page.
- **UL 508A review**: a checklist that helps you spot design problems (advice only).
- **Explorer**: show or hide the Project explorer tree.
- **Compact rail**: make the left rail narrower.
- **? Manual**: open this manual.
- **☀ Light / ☾ Dark**: switch the color theme.

### The project name box

At the top of the window is a long text box with your project's name. Click it, type a new name, and press **Enter**. The window title shows the name too. A star (`*`) in front of the title means you have changes that are not saved yet.

### The left rail (library rail)

The left rail is your main control panel. From top to bottom:

**OUTPUT** (always visible, it never scrolls away):

- **Drawings**: generates all the drawing sheets for this cabinet.
- **View drawings**: opens the drawing viewer so you can flip through the sheets.
- **Programming**: opens the full-screen ladder program page.
- **HMI editor**: opens the touch screen designer.

**PROJECT**:

- **New build with AI**: the guided way to build a whole cabinet by answering questions. See [New build with AI](#new-build-with-ai-step-by-step).
- **Open** / **Save**: open a saved project, or save this one.
- **Save as**: save a copy with a new name.
- **New**: start a new, empty (or template) cabinet.

**DEVICES**:

- **Guide build**: an interview about your cabinet (voltages, enclosure and more), followed by suggested parts.
- **AI suggest**: asks the AI to suggest details for the selected part.
- **Apply all AI suggestions**: accepts every suggestion at once.
- **Program stubs**: an older browser of starter PLC text (Logix, SCL, Modbus).
- **Desktop shortcut**: puts a Cabinet Studio icon on your desktop.

**REVIEW**:

- **UL 508A review**: an advisory checklist (it gives advice, it does not certify).

**LAYOUT TEMPLATES**: cards with ready-made starting layouts. Click one to use it.

**EQUIPMENT LIBRARY** (at the bottom, always visible):

- A search box: **Search name, vendor, catalog**. Type words like `contactor`, `Siemens` or a part number.
- A type filter: **All types**, or one kind of part (PLC, contactor, e-stop and so on).
- A maker filter: **All makers**, **Allen-Bradley**, **Siemens**, **Omron** and others. Pick one to see only that maker's parts.
- **Add selected**: adds the part you clicked in the list.
- **Define a device not listed**: make your own part when the library does not have it.

**STARTER DEVICES**: the list of library parts that match your search and filters. Each card shows the name, type, maker and catalog number.

At the very bottom the rail shows the version, `v0.3.35`.

> **Tip:** Is the rail too long for your screen? Scroll it with the mouse wheel. The OUTPUT buttons at the top and the EQUIPMENT LIBRARY at the bottom always stay in view.

### The cabinet area (middle)

This is where the parts of your cabinet appear as tiles. Click a tile to select it. Double-click a tile to define or edit it. Press the **Delete** key to remove the selected tile.

### The INSPECTOR (right side)

When you click a part, the Inspector shows its tag (its short name, like `PSU1`), description, maker and catalog number.

- **Continue definition** (or **Edit definition** when the part is complete): opens the **Define device** wizard to fill in details.
- **Remove from layout**: removes the part from this cabinet.

### The Project explorer

Click **Explorer** on the toolbar (or **View > Project explorer**) to show a tree of everything in the project. Click an item to jump to it.

## Projects: new, open, save

### Start a new project

1. Click **New** (toolbar or left rail), or press **Ctrl+N**.
2. The **New cabinet** box opens.
3. Type a **Project name**, for example `Conveyor 1`.
4. Choose a **Starting layout**.
5. Click **Create**.

> **Tip:** If you want the program to do most of the work for you, use [New build with AI](#new-build-with-ai-step-by-step) or [start from a template](#starting-from-a-template) instead.

## Starting from a template

A template is a finished starter cabinet. It already has the parts (real catalog numbers), wire numbers, PLC I/O addresses, a working ladder program, and for most templates an HMI screen. You pick the one closest to your machine, then change what is different. It is the fastest way to begin.

### Open the template gallery

There are three ways:

- Click **Templates** on the toolbar (next to **New**).
- Use **File > New from template…**.
- Click **New** (or press **Ctrl+N**), then click **Start from a template…** at the bottom left of the **New cabinet** box.

If your open cabinet has unsaved changes, the program first asks **Save cabinet?** — the same question you get with **New**. Your open cabinet is never replaced without that question.

> **What you'll see:** The **Start from a template** window with a card for each template. Each card has a small drawing, the name, one or two lines about it, and **Use it for:** (when to pick it).

### Use a template, step by step

1. (Optional) Type a **Project name** at the top. If you leave it empty, the template name is used.
2. On the card you want, pick the **maker** (Allen-Bradley, Siemens or Omron) from the first drop-down.
3. Pick the **supply voltage** (the power that feeds the cabinet) from the second drop-down.
4. Click **Use this template**.

The new cabinet opens right away. It is **not saved yet** (you will see the star `*` in the title), so click **Save** when you are happy with it. Everything is editable: add or remove parts, change the ladder, or run **Guide build** or **New build with AI** to answer the questions again.

> **Tip:** Open the **Notes** of the new project. They list **What to change first** for that template — usually the motor size, a timer setting and the sensor type.

> **Tip:** The maker drop-down swaps in that maker's part when the library has one (PLC, I/O cards, power supply, E-stop, safety relay, drive, contactor, buttons and more). Parts the library only has from one maker stay as they are — check them on the drawings.

> **Safety:** Every template keeps the safety note on its first rung. E-stop, light curtain and two-hand functions must be hardwired or use rated safety relays (NFPA 79 / ISO 13849). The software is never the safety function. The simulator's **Normal run** never presses the E-stop or breaks the light curtain for you.

### The templates and when to use each one

| Template | When to use it |
|---|---|
| **Simple motor starter** | One fixed-speed motor (fan, pump, blower, saw). A contactor and overload start it across the line. Start, Stop, E-stop, Reset, a run light and a fault light. |
| **Conveyor with VFD** | A belt or roller conveyor with a variable-speed drive. A photo-eye counts parts (batch of 100), a jam timer stops the belt, and a 3-color stack light and HMI show status. |
| **Pump and tank level** | Filling (or emptying) a tank. Low and high level switches start and stop the pump. High-high (overfill) and no-flow alarms. |
| **Pneumatic press station** | A press, crimper or staker loaded by hand. Two-hand start, light curtain with its own safety relay, cylinder extend / retract sensors, a dwell timer, a stroke counter and a watchdog. |
| **Mixer / batch tank** | Mixing or heating a batch. Agitator motor and heater, lid switch, temperature permissive and a timed mix. |
| **Pick-and-place indexer** | Packaging or transfer stations that move parts in steps. Three solenoids run a 6-step sequence using step bits, with a part-present eye and a motion watchdog. |
| **HVAC / exhaust fan** | A fan run by a building system. Hand-Off-Auto selector, fan drive, airflow proving pressure switch, 120 V control. |
| **Lighting control panel** | A small 120 V panel for parking-lot, building or sign lights. Photocell, Auto/Off selector, override buttons, timers and three lighting relays. |
| **PLC trainer bench** | Learning and practice. A PLC with buttons, a selector, a photo-eye, a prox, a relay, lights and a stack light on 24 VDC, with example rungs (seal-in, flasher, counter). |

> **Tip:** Want the same template with Siemens or Omron parts? Pick the maker on the card before you click **Use this template**. You can make all three and compare them.

### Save your project

1. Click **Save** or press **Ctrl+S**.
2. The first time, Windows asks where to save. The program suggests its `saves` folder. Keep that, type a name and click **Save**.

Use **Save as** (**Ctrl+Shift+S**) to save a copy under a new name.

> **Watch out:** Save often! The star (`*`) in the window title means there are unsaved changes. When you close the program with unsaved changes, it asks you first.

### Open a project

1. Click **Open** or press **Ctrl+O**.
2. Go to the saves folder and pick a file that ends in `.cabinet.json`.
3. Click **Open**.

### Where your files go

| What | Where |
|---|---|
| Projects (`.cabinet.json`) | `Documents\Cabinet Studio\saves` |
| Drawings for a project | `Documents\Cabinet Studio\saves\drawings\<project name>` |
| PLC export files | a `plc` folder with the drawings (use **Open folder** in the PLC / Device window) |
| HMI export files | an `hmi` folder with the drawings |
| AI settings and your API key | `%APPDATA%\CabinetStudio\ai_settings.json` |

> **Tip:** Uninstalling the program does not delete any of these files. Back up your `saves` folder to a USB stick or cloud drive now and then.

## New build with AI, step by step

This is the easiest way to make a complete cabinet. The program asks you simple questions, one at a time, then picks parts, makes the drawings and starts the program.

1. Click **New build with AI** at the top of the left rail (or **File > New build with AI…**).
2. A window called **New build with AI** opens. It says: *Answer one question at a time. You can change your mind with Back.*
3. Answer each question (explained below), then click **Next**.
4. Click **Back** to change an earlier answer. Click **Cancel** to stop without changing anything.

Under each question there is an **AI tip** with a suggested answer. Two helpful buttons:

- **Use AI answer**: fills in the suggested answer for this one question.
- **Accept all AI answers**: fills in the suggested answer for every question that is left. Use this when you are not sure and just want a good starting point.

> **Tip:** There is no wrong answer. You can change everything later.

### The questions, explained

1. **What does this machine do?** Type a few plain words, like `conveyor that moves boxes` or `small press with a guard`. The AI uses these words to guess the rest. Words like *press, weld, robot, saw, cut* make it suggest safety guarding.
2. **Which manufacturer do you prefer for the parts?** Pick **Allen-Bradley**, **Siemens**, **Omron**, or **Best fit (AI picks)**. Every part the AI picks comes from this maker when the library has one.
3. **What voltage feeds the cabinet?** The main power coming in, for example **480 VAC** (common in US factories) or **120 VAC** (like a wall outlet). Pick **Other / not sure** if you do not know.
4. **What voltage do the pushbuttons and sensors use?** The "control voltage". **24 VDC** is the most common and the safest choice for buttons and sensors.
5. **Does this machine run a motor?** **Yes**, **No** or **Not sure**.
6. **How should the motor be controlled? (skip if no motor)**
   - **VFD (variable speed)**: a drive that can change the motor's speed.
   - **Contactor (across-the-line)**: a big switch that turns the motor fully on or off.
   - **Both / not sure** or **No motor**.
7. **How do people start and stop it?** **Pushbuttons**, **Touchscreen (HMI)**, **Both** or **Not sure**.
8. **Which operator devices should go on the door / panel? (pick all that apply)** Tick the boxes you want: Start pushbutton, Stop pushbutton, Selector switch (HOA = Hand / Off / Auto), Reset pushbutton, Run indicator light, Fault indicator light.
9. **Do you want interposing / control relays in the cabinet?** Relays are small switches that let the PLC control bigger things. Pick **Not sure (AI will suggest)** if unsure.
10. **Is there an emergency stop (e-stop) button?** For almost every real machine the answer is **Yes**.
11. **Should we include a safety relay to monitor the e-stop?** A safety relay is a special rated part that makes the E-stop truly safe. The answer should almost always be **Yes**.
12. **Does a light curtain guard the operator opening? (beam broken = machine stops)** A light curtain is a row of invisible light beams across an opening. If a hand breaks a beam, the machine stops. Pick **Yes — add a light curtain + safety relay** or **No**.
13. **Add a 3-color stack light?** A tower of lights on top of the machine. Pick **Yes — green / amber / red stack light** or **No**. Green = ready / running, amber = light curtain broken, red = E-stop.
14. **Is there a touchscreen or HMI for the operator?** **Yes**, **No** or **Not sure**.
15. **Do you need a cabinet door drawing?** Pick **Yes — draw the door** to get a drawing of the buttons, lights, E-stop and HMI on the door.
16. **What should we call this cabinet project?** Type a name, like `Box Conveyor`. Please type this one yourself.

### Checking the recommended devices

After the last question the window changes to **Recommended devices**.

> **What you'll see:** A list of parts with tick boxes. They come from your library, from the maker you picked when it has one.

1. Look down the list. Untick any part you do not want.
2. Click **Accept all AI picks** to take every part, or click **Confirm devices** to take just the ticked ones.
3. Confirming creates a **new** cabinet. The program also picks an enclosure (box) that fits the parts.
4. The program then walks you through saving, making drawings and starting the program. Each step asks you first. You can skip any step.

> **Watch out:** Confirming makes a NEW cabinet. Save your old project first if you want to keep it.

## Adding and editing parts

### Add a part from the library

1. In the **EQUIPMENT LIBRARY** at the bottom of the left rail, type in the search box, for example `e-stop`.
2. Optional: pick a type in the type filter, and a maker in the maker filter.
3. Click a card in the **STARTER DEVICES** list to select it (it gets a blue outline).
4. Click **Add selected**.

> **Tip:** Double-click a card to add it in one step.

### Define or edit a part

1. Click the part's tile in the middle of the window.
2. In the **INSPECTOR**, click **Continue definition** (or **Edit definition**). You can also double-click the tile.
3. The **Define device** wizard opens. Walk through the steps with **Next**. On the wiring step you set terminal landings, wire numbers and wire colors.
4. Finish the wizard to save the part.
5. Click **Drawings** again so the drawings update.

> **Watch out:** You never draw wires by hand. You describe the parts and their wiring, and Cabinet Studio draws the sheets for you. Change the part, then make the drawings again.

### Make a part that is not in the library

1. Click **Define a device not listed** (left rail) or **Edit > Add device…**.
2. Pick the **Device class** (what kind of part it is).
3. Fill in the wizard. Anything the PLC supervises gets a definition.

### Remove a part

Select it, then press **Delete** or click **Remove from layout** in the Inspector. Made a mistake? Press **Ctrl+Z** (Undo).

### Let the AI help with parts

- **Guide build**: answers questions about your cabinet, then suggests parts.
- **AI suggest**: suggests details for the selected part.
- **Apply all AI suggestions**: accepts all the suggestions at once.

## Choosing the enclosure

The **enclosure** is the metal box. Inside it is a flat metal sheet called the **backplate** where parts are mounted.

- **Hoffman** is the default maker. **Saginaw** and **Hammond** are also available.
- Sizes include 36×30×12, 30×24×12 and 24×24×8 inches (height × width × depth), each with its matching backplate part number.
- When you use **New build with AI**, the program picks an enclosure automatically to fit your parts.
- To choose yourself, use **Guide build** and answer the **Enclosure brand and size** question (for example `Hoffman 30×24×12 (A302412LP + A30P24)`). Pick **Other / not decided** if you are not sure yet.

> **Tip:** Bigger is easier to wire and leaves room for future parts. UL 508A shops like some empty space.

## Drawings

Drawings are the sheets an electrician uses to build and wire the cabinet. Cabinet Studio makes them from your parts list. Sheets are 11×17 inches (tabloid).

### Make and view the drawings

1. Make sure your cabinet has parts.
2. Click **Drawings** (left rail OUTPUT, or the toolbar, or **Tools > Generate drawings**).
3. When it is done, click **View drawings**.

> **What you'll see:** The **DRAWINGS** viewer. On the left, a **SHEETS** list with every sheet's name. In the middle, the current sheet. At the bottom: **Previous**, **Next**, **Open in browser**, **Pop out view**, **HMI editor**, **Add part**, **Reset layout** and **Close**.

Move between sheets by clicking a name in the SHEETS list, clicking **Previous** / **Next**, or pressing the **Left** / **Right** arrow keys. Press **Esc** to close.

### The sheets, in order

1. **Panel layout** (`PANEL LAYOUT — <name>`). A drawing of the backplate seen from the front, to scale. Every part is drawn with its real outline shape and size, on DIN rails with wire ducts between them. You will also see where power comes in and goes out, the ground (PE) bar, and a scale bar so you can measure.
2. **Door** (`PANEL LAYOUT — <name> · DOOR`). Only the parts on the door: pushbuttons, lights, E-stops and the HMI. This appears when you asked for a door drawing.
3. **Power schematic**. How the big power flows: from the incoming supply, through the disconnect and breakers (protection), to each device, and back. Lines that run top-to-bottom are the power "rails". The green/yellow ground (PE) bar is separate.
4. **Control schematic**. The +24V and 0V control "ladder": pushbuttons, sensors, relays and PLC inputs and outputs. The PLC I/O on this sheet matches the parts in your project.
5. **Wire schedule** (`WIRE SCHEDULE — <name>`). A table of every wire: wire number, FROM, TO, color and gauge (thickness).
6. **PLC I/O list sheets**. Which button or light is connected to which PLC input or output.
7. **HMI sheets** (after you save an HMI): **HMI SCREEN LAYOUT** for each screen, **HMI DOOR CUTOUT DETAIL** (the hole to cut in the door), **HMI WIRING + TAG TABLE**, and **HMI ALARM LIST**.

The ladder program is a separate document. It is printed from the Programming page, not here.

### Hover for wire details

To keep the sheets clean, only short names and coil descriptions are printed on the sheet. To see the full details of a wire or part, **rest your mouse near it**. A pop-up shows its type, wire numbers, color, gauge, FROM–TO, I/O address and callout.

> **Tip:** **Open in browser** shows the shop-print version of the sheet (SVG) with all labels. It is also the best way to print.

### Move parts and text on the layout

On the panel layout and door sheets you can tidy things up:

- **Drag a part** to a new spot with the left mouse button.
- **Drag a text label** to move it.
- **Right-click a part** for **Copy** and **Delete**.
- **Right-click an empty spot** for **Paste here** and **Add part here** (pick a part from the list).
- **Ctrl+C** copies the clicked part.
- **Add part** (bottom bar) adds a part to the sheet.
- **Reset layout** puts every part on the sheet back in its automatic spot.

> **Watch out:** If the viewer says *Nothing to reset*, the sheet is already in its automatic layout.

### Pop out the drawing

Click **Pop out view** to put the drawing in its own window. Drag it to a second monitor if you have one. The sheet list and Previous / Next still work. Click **Dock view** to put it back.

### Printing drawings

1. In the drawing viewer, go to the sheet you want.
2. Click **Open in browser**.
3. In the browser, press **Ctrl+P**.
4. Choose your printer. Set paper size to **Tabloid (11×17)** and orientation to **Landscape** if your printer can do it. Otherwise choose "Fit to page".
5. Click **Print**.

### The footer on every sheet

Each sheet has this footer, once: `NOT A CERTIFIED UL 508A DRAWING. Design aid only.`

That means: these drawings are a helper. A qualified person must check and approve the design before anyone builds a real cabinet from it. Do not remove the footer.

## UL 508A review

Click **UL 508A review** (toolbar, left rail or **Tools** menu). It lists things to check against the UL 508A standard for industrial control panels, such as disconnect, short-circuit ratings, wire sizes and spacing. It is advice only. It does not certify anything.

## The Programming page

The Programming page is where you build the PLC program. Open it with **Programming** on the left rail or toolbar.

> **What you'll see:** A big full-screen window with its own menu bar (**File, Edit, View, Rung, Simulate, Tools, Help**), a toolbar, a SIMULATE row, the ladder drawing in the middle, and the rung editor strip along the bottom. A status bar at the bottom shows messages.

When you are finished, click **Done** (top right) or press **Esc** to go back to the cabinet.

### Ladder logic in one minute

A ladder program looks like a ladder lying on its side:

- The two side rails are the "power" lines. Power flows from the **left rail** to the **right rail**.
- Each step of the ladder is a **rung**. The PLC reads rungs from top to bottom, again and again, very fast. One trip through all the rungs is a **scan**.
- On the left of a rung are **contacts**. They are like questions: "Is the Start button pressed?"
- On the right is a **coil**. It is the answer: "Then turn the motor ON."
- If every contact on a path lets power through, the coil turns ON.

Two kinds of contact:

- **NO (normally open), called XIC**: lets power through when its tag is **ON**.
- **NC (normally closed), called XIO**: lets power through when its tag is **OFF**.

> **Tip:** A classic first rung is a "seal-in": Start (NO) OR Motor (NO), in series with Stop (NC), driving the Motor coil. Press Start and the motor keeps itself on until Stop is pressed.

### The Programming toolbar

| Button | What it does |
|---|---|
| **New…** | New Program / Routine wizard: make a new program or routine step by step |
| **Ladder** / **PLC text** / **HMI text** | Switch between the ladder picture, the PLC text version, and the HMI tag text |
| **Organizer** | Shows the Controller Organizer: a tree of routines, tags and I/O. Click a routine or tag; double-click an I/O point |
| **Properties** | Shows details of the selected item |
| **Pop out ladder** | Moves the ladder into its own window (click **Dock ladder** to bring it back) |
| **Verify** (F7) | Checks the program for problems, like a coil used twice or a tag that does not exist. "No issues found." means it is clean |
| **Explain run** | Opens *Explain run - step by step*, which tells you in plain words what the simulator is doing and which rung is waiting. **Copy all** and **Clear** buttons are at the top |
| **Tags / X-ref** (Ctrl+T) | List of all tags. Click **Used** on a tag to see WHERE USED. You can add a new tag, describe it, or make an alias |
| **Watch / Trend** | Watch tag values change over time. **Pause** / **Resume**, and **Export CSV** to save them as a spreadsheet |
| **PLC / Device** | Opens the PLC / Device window (export files, live link) |
| **HMI editor** | Opens the touch screen designer |
| **☀ Light / ☾ Dark** | Switch theme |
| **Done** | Go back to the cabinet |

### The File menu (Programming page)

- **New Program / Routine…**: the step-by-step program wizard.
- **Ask questions (in the strip)…**: answer simple questions and the program builds a starter ladder.
- **Build starter program**: makes a starter ladder from the cabinet parts.
- **Build from drawings**: makes the ladder from the I/O in your drawings.
- **Import PLCopen XML…**: loads a ladder program saved in the PLCopen XML standard format. The program is very strict: if the file has anything it does not understand, or the logic does not check out exactly, it refuses the whole file instead of guessing.
- **Export Ladder…**, **Export PLCopen XML…**, **Export .txt…**: save the program to a file.
- **Print ladder…**: print the ladder. The printout keeps the safety note.
- **Done - return to cabinet** (Esc).

### The rung editor (bottom strip)

The rung editor is the row of controls under the ladder. You choose parts in the boxes, then click an **Add** button.

| Control | What it does |
|---|---|
| **Contact** | Pick the input or bit this rung checks. NO (XIC) passes power when the tag is ON; NC (XIO) passes power when it is OFF |
| **Coil** | Pick the output or bit this rung turns ON |
| **Comment** | A note for this rung in plain words. It prints with the ladder |
| **Timer** | Timer type (TON, TOF, RTO), its name and its preset time |
| **Counter** | Counter type (CTU, CTD, RES), its name and preset |
| **Compare A op B** | Compare two values: EQU, NEQ, GRT, GEQ, LES or LEQ |
| **Math op → dest** | Math (ADD, SUB, MUL, DIV…) with the answer stored in dest |
| **One-shot** | ONS, OSR (rising edge) or OSF (falling edge) |
| **AOI** | Name of an Add-On Instruction (a reusable block) |
| **JSR→** | Name of the subroutine that Add JSR jumps to |
| **↶ Undo** / **↷ Redo** | Take back or put back a change (Ctrl+Z / Ctrl+Y) |
| **Pop out editor** | Opens the rung editor in its own window you can drag anywhere, even to another monitor. **Dock editor** puts it back. Tick **Keep on top** to keep it in front |

The **Add** buttons:

- **Add rung**: the chosen Contact driving the chosen Coil.
- **Add timer**, **Add counter**: the Contact driving a timer or counter.
- **Add nested OR**: a rung with a parallel branch (either path turns the coil on, like a seal-in).
- **Add mid coil**: an output in the middle of a rung, with more logic after it.
- **Add compare**, **Add math**, **Add LIM** (between a low and a high limit), **Add MEQ** (masked equal), **Add bitwise** (AND / OR / XOR).
- **Add AOI**, **Add OTL** (latch ON), **Add OTU** (unlatch), **Add one-shot**.
- **Add JSR** (jump to a subroutine), **Add SBR** (make a new subroutine), **Add RET** (return from it).
- **Comment…**: change the comment on the selected rung.
- **Add series contact**: adds the chosen Contact to the selected rung (one more condition).
- **Delete rung**: deletes the selected rung (Undo brings it back).

The **Edit** controls:

- **Copy rung** (Ctrl+C), **Paste rung** (Ctrl+V, pastes after the selected rung), **Duplicate** (Ctrl+D).
- **Move ↑** / **Move ↓** (Ctrl+Up / Ctrl+Down): move the selected rung.
- **Copy instr…** (Ctrl+Shift+C) and **Paste instr** (Ctrl+Shift+V): copy one instruction into another rung.
- **Delete instr**: click one contact or coil on the ladder, then click this to delete just that one. The rest of the rung re-connects.
- **Replace instr**: click one contact or coil, then click this to swap it for the Contact (or Coil) picked in the editor.

### Your first rung, step by step

1. Click a rung on the ladder (or the empty ladder) to select where the new rung goes.
2. In **Contact**, pick an input, for example `Start_PB`. Choose NO.
3. In **Coil**, pick an output, for example `Motor_Run`.
4. Click **Add rung**.
5. Type a **Comment** like `Start the motor`, then click **Comment…** to set it.
6. Press **F7** (Verify) to check the program.

> **What you'll see:** A new rung at the bottom of the ladder with a contact on the left and a coil on the right.

### Editing instructions on the ladder

- **Click** a contact or coil to select it.
- **Right-click** it for a menu: **Delete <tag>**, **Change NO / NC**, **Replace with contact…** / **Replace with coil…**, **Add contact … before**, **Add contact … after**.
- **Drag** a contact or coil with the left mouse button and drop it on another spot or another rung to move it.

### The instruction palette

The **INSTRUCTIONS** row shows buttons for each instruction (XIC, XIO, OTE, OTL, OTU, ONS, OSR, OSF, Branch, TON, TOF, RTO, CTU, CTD, RES, EQU, NEQ, LES, LEQ, GRT, GEQ, LIM, MEQ, ADD, SUB, MUL, DIV, MOV, AND, OR, XOR, NOT, JSR, SBR, RET, AOI). Hover over any of them to read what it does, with an example.

### Find, replace and undo

- **Edit > Find…** (Ctrl+F) and **Replace…**: find a tag and replace it everywhere. Tick **Match case** or **Whole tag (T1 also finds T1.DN)** as needed.
- **Undo** (Ctrl+Z) and **Redo** (Ctrl+Y) work for every ladder change.
- **Copy PLC text** and **Copy HMI text** (Edit menu) copy the text versions to paste into other software.
- **Sync text from ladder** rebuilds the PLC text from the ladder.

### Layout and windows

- **View > Layout > Studio** is the normal look. **Classic (until v0.3.24)** is the older look.
- **View > Pop out / dock ladder**, **Float / dock I/O panel**, **Pop out / dock rung editor**: move parts of the page into their own windows.

### Ask AI

Click **Ask AI** (in the SIMULATE row, or **Tools > Ask AI**) to ask questions about your program in plain words, like "What does rung 3 do?" Type your question and click **Ask**. When the AI suggests a change, you can click **Apply** or **Dismiss**. The AI can be wrong. Always check its work and run **Verify**.

## The simulator

The simulator pretends to be a PLC so you can test your program safely on your computer.

### The SIMULATE row

| Button | Key | What it does |
|---|---|---|
| **Run** | F5 | Starts scanning the program over and over like a real PLC. Click any contact to switch that input |
| **Pause** | F9 | Freezes the scan and timers where they are |
| **Step rung** | F6 | Runs ONE rung, then stops. Watch power flow left to right |
| **Step scan** | F10 | Runs every rung once (one full scan), then stops |
| **Stop** | Shift+F5 | Stops the simulation and lets go of every input you switched |
| **Reset** | | Clears all bits, timers and counters to zero, like a fresh power-up |
| **Normal run** | | Pretends the machine is running perfectly (see below) |
| Speed menu | | **0.25 s / rung**, **0.5 s / rung**, **1 s / rung** (default), **2 s / rung**, or **PLC speed (full scan)** |
| **Follow rung** | | Scrolls the ladder so the rung being scanned stays on screen |
| **Each part** | | Lights each part of a rung one at a time, left to right, so you can follow the logic |
| **Ask AI** | | Ask the AI about the program |

> **What you'll see:** When power reaches a contact or coil, it turns bright (green). Coils that are ON stay lit.

### Switching inputs yourself

While the simulator runs, **click a contact** on the ladder to switch its input ON or OFF. You can also use the I/O panel: **Force inputs (click to toggle)**. Click **Float I/O** to move the I/O panel into its own window; **Dock I/O** puts it back.

### Normal run: the pretend machine

Click **Normal run** and the simulator does the boring setup for you:

1. It makes the stops and guards safe (E-stop released, light curtain clear).
2. It presses **Reset** and **Start** for you.
3. The pretend machine answers the outputs: the motor sends "running" feedback, cylinders reach their sensors, and parts pass the photo-eyes.

Watch the ladder light up as the machine runs.

### Test the E-stop and light curtain yourself

Normal run never touches safety for you. You test it:

1. Start **Normal run** and wait until the machine is running (stack light green).
2. Click the **E-stop** contact (or its input in the I/O panel) to "press" it.
3. Check: does the motor turn off? Does the stack light go red?
4. Release the E-stop, then press Reset and Start. Does it run again?
5. Now click the **light curtain** input to "break the beam".
6. Check: does the machine stop? Does the stack light go amber?

> **What you'll see:** Stack light colors in the simulator: **green** = ready / running, **amber** = light curtain broken, **red** = E-stop pressed.

> **Safety:** This only tests the *program's* reaction. On a real machine the E-stop and light curtain must stop the machine through hardwired circuits and rated safety relays, even if the PLC is broken.

### Explain run

Click **Explain run** to open a window that writes down, step by step, what the simulator does and why. If the machine seems stuck, Explain run tells you which rung is waiting and for what. Click **Copy all** to copy the explanation.

## The HMI editor

An HMI is the touch screen an operator uses to run the machine. The HMI editor lets you design those screens.

Open it with **HMI editor** on the left rail, on the Programming page, or in the drawing viewer.

> **What you'll see:** A window called **HMI editor**. Top row: **Run interview**, **Validate**, **Undo**, **Delete object**, **Run with simulator**, the **Model:** menu, **Save** and **Close**. Second row (QUICK BUILD): **Auto-build (1 click)**, **Bind tags for me**, **Rebuild nav bar**, **Alarm list**, **Export tag CSV**, **Export for <maker>** and the **Theme:** menu. Left: SCREENS, ADD TO SCREEN, MACHINE GRAPHICS and FACEPLATES (ONE CLICK). Middle: the screen. Right: PROPERTIES.

### Fastest way: Auto-build

1. Click **Auto-build (1 click)**.
2. The program builds every screen from your cabinet parts and ladder tags: a faceplate for each motor, valve and stack light, plus alarms, trends and the go-to bar.
3. Click **Validate** to check it.
4. Click **Save**.

### The HMI interview

Click **Run interview** to answer a few questions, one at a time. Each has a suggested answer. Use **Next**, **Back**, **Cancel**, or **Accept all** (take every suggestion). On the last question the button says **Build HMI**. The questions:

1. Which maker should the HMI touch screen be?
2. How big should the screen be?
3. Which HMI model?
4. Which screens do you want?
5. How should machine parts be grouped?
6. Add a Machine picture screen (conveyors, motors, sensors, stack light)?
7. Start / Stop buttons: hardwired on the door, or on the HMI too?
8. Show alarms on the HMI?
9. Show speeds / numbers (like drive speed)?
10. How does the HMI cable reach the PLC?

### Screens

In **SCREENS** on the left, click a screen to open it. Type a name in the **Screen name** box, then click **Add screen** or **Rename**. **Delete** removes the current screen (Undo brings it back).

### Adding things to the screen

Under **ADD TO SCREEN**, click an item to drop it in the first free spot, then drag it where you want:

- **Push button (momentary)**: on only while pressed, like a doorbell (Start, Reset, Jog).
- **On/Off button (toggle)**: press once for on, again for off (Manual / Auto).
- **Indicator lamp**: shows if a PLC bit is on (Motor running, Fault).
- **Number display**: shows a number (speed, part count).
- **Number entry**: lets the operator type a number (speed setpoint).
- **Text label**: plain words like a title.
- **Alarm banner**: a strip that shows the newest alarm.
- **Go-to-screen button**: jumps to another screen.
- **E-stop status (display only)**: shows if the E-stop is pressed. The HMI can never stop or reset the machine safely.
- **Trend chart**: a line of a number over time.

### Faceplates (one click)

A faceplate is a ready-made group of lamps, buttons and numbers for one machine part.

1. In **FACEPLATES (ONE CLICK)**, pick a machine part from your cabinet.
2. Pick the faceplate type: **Motor**, **Motor with drive (VFD)**, **Valve / solenoid**, **Stack light**, or **Counter / timer readout**.
3. Click **Add faceplate**. It is already tied to the right tags. Drag any piece to move the whole group.

### Machine graphics and animation

Under **MACHINE GRAPHICS** you can add pictures: Conveyor, Motor, Pump, Fan, Tank, Valve (2-way), Air cylinder, Robot arm, Light curtain, Stack light, Part / box, Pipe (straight / elbow / tee), Photo-eye, Prox sensor, Heater, Mixer, Press, Gauge (dial), Bar graph, Push-button picture and Selector switch picture.

1. Click a graphic to drop it, then drag or resize it.
2. On the right, pick its **PLC tag**.
3. In **Animate with tag**, choose how it moves: spins / moves while ON, fills from a 0–100 number, a needle follows a number, or turns red when abnormal.

Graphics move in **Run with simulator** and print still.

### The PROPERTIES panel (right side)

Click an object on the screen (it gets a dashed outline). Then:

- **Words on the object**: the text the operator sees.
- **PLC tag**: the tag it reads or writes. Click **Suggest tag** to let the program pick the best match. Tags starting with `HMI_` are HMI memory bits you add to the PLC program.
- **Color**: Green = running / OK, Red = stop / fault, Amber = warning.
- **Button action**: Momentary or Toggle (buttons only).
- **Go to screen**: which screen a Go-to button opens.
- **Animate with tag**: for machine graphics.
- Click **Apply changes** to keep your edits.

### The tag wizard: Bind tags for me

Click **Bind tags for me** to fill in every empty PLC tag with the best match by name and type. Buttons get `HMI_` memory bits. Then click **Validate** to check for unknown tags, objects on top of each other and missing tags.

### Nav bar, alarms and themes

- **Rebuild nav bar**: adds a row of go-to buttons for every other screen along the bottom of each screen. Use it after adding or renaming screens.
- **Alarm list**: shows the alarms made from the E-stop, safety, fault and overload tags, with a priority (1 = High). They also print on the HMI ALARM LIST sheet.
- **Theme:** **ISA-101 gray (high performance)** (gray screen, color only when something is wrong, easy on the eyes), **Classic bright**, or **Dark**.
- **Model:** pick a different touch screen model. Objects keep their places and resize to fit.

### Test the HMI with the simulator

1. Click **Run with simulator**.

> **What you'll see:** A red banner: `SIMULATION - not a live PLC. Buttons write the simulator only. E-stop and safety are never written by the HMI.`

2. Click the screen buttons and watch lamps, numbers and graphics change.
3. To send a number, select a Number entry, type a value in the **Number** box and click **Send number**.
4. Click **Stop** to go back to editing.

### Save and export the HMI

- **Save**: saves the HMI into the cabinet. The HMI screen layout, door cutout and HMI wiring sheets then appear in the drawings. Save the cabinet file too.
- **Export tag CSV**: a spreadsheet of every HMI tag to import into FactoryTalk View, TIA Portal or NB-Designer.
- **Export for <maker>**: writes import-ready files into the `hmi` folder: tag list, alarm list, screen spec and a picture of every screen. You import these in the maker's HMI software and rebuild the screens there. Cabinet Studio does not download into the HMI.

## The PLC / Device window

Open it from the Programming page: click **PLC / Device** or **Tools > PLC / Device (export & connect)…**.

At the top, pick the PLC or HMI to work with from the device menu. An orange note reminds you: full program download into Allen-Bradley, Siemens and Omron PLCs is done in the maker's software (Studio 5000 / CCW, TIA Portal, Sysmac Studio / CX-Programmer). Cabinet Studio writes import-ready files and offers a live Ethernet tag link for testing.

### Files row

1. **Assign I/O**: gives every pushbutton, sensor, light and coil a PLC input or output address in this PLC's own format. Addresses you already gave are kept.
2. **I/O list CSV**: saves the I/O list (tag, device, address, module, terminal, wire #) as a spreadsheet.
3. **Export files**: writes import-ready files for the selected PLC or HMI (program, tag tables, I/O list) and a **README** with step-by-step import instructions.
4. **Open folder**: opens the folder with the exported files.
5. **Download / upload program**: explains how to put the program into the real PLC using the maker's software.

> **Tip:** After **Export files**, click **Open folder** and open the README first. It lists the exact import steps for your PLC's software.

### Live link (beta)

The live link reads and writes tags in a real PLC over Ethernet. It is for testing on a bench.

1. Pick a driver: **Allen-Bradley Logix (CompactLogix / ControlLogix)**, **Allen-Bradley Micro800**, **Siemens S7-1200 / S7-1500**, **Siemens S7-300 / S7-400**, **Omron FINS (BETA)**, or **Simulated PLC (no network)**.
2. Type the PLC's **IP** address (like `192.168.1.10`) and the **Slot** (ControlLogix: usually 0; S7-1200/1500: 1; S7-300: 2).
3. Click **Connect**. It reads the PLC's name, model and firmware.
4. **Read info** reads them again. **Compare tags** compares the PLC's tags to your project (missing, extra and type mismatches). **Disconnect** closes the link.

> **Tip:** Practice with **Simulated PLC (no network)** first. It needs no PLC and no network.

### Watching tags

1. Type or pick a tag in the **Watch** box and click **Add**. **Add all I/O** adds every I/O point. **Remove** takes one off.
2. Click **Start watch**. Values update about once a second. Click **Stop watch** to stop.

### Writing a tag (be careful)

You can write only non-safety, non-I/O tags (like an `HMI_` bit or a setpoint):

1. Type the tag (for example `HMI_Start`) and a value (1 / 0 for a bit, or a number).
2. Tick **I am at the machine and it is safe**. Only tick this when you can see the machine and nobody can be hurt.
3. Click **Write**.

> **Safety:** Safety tags and physical I/O are always refused. Writing a tag changes a running machine. Only bench-test on a test PLC, never on running production machinery.

Click **Close** to disconnect and close the window.

## AI settings

Some features use AI: the New build with AI tips, AI suggest, and Ask AI. Cabinet Studio has a free built-in helper (**Cabinet Studio AI (free, offline)**). For smarter answers you can connect an online AI with **your own key**.

To open AI settings: on the Programming page use **Tools > AI settings…**, or click **AI settings…** in the Ask AI window.

1. Pick the AI provider, for example **Groq (free key)** or **xAI (Grok)**. Others: OpenAI (ChatGPT), Anthropic (Claude), Google (Gemini), GitHub Models (Copilot), Microsoft Azure OpenAI, and Ollama (local, offline).
2. Get a key from that provider's website (sign up, then find "API keys").
3. Paste it into the **API key** box. Tick **Show** to see what you typed.
4. Click **Refresh models** and pick a **Model**.
5. Click **Test connection**, then **Save**.

> **Watch out:** Your API key is like a password. Keep it private. Never share it, post it, or put it in a screenshot. It is saved only on your computer. Click **Clear key** to remove it. No key is shipped with Cabinet Studio.

> **Tip:** The AI can make mistakes. Always check its suggestions, and run **Verify** on the program.

## Keyboard shortcuts

**Main window**

| Keys | Action |
|---|---|
| Ctrl+N | New project |
| Ctrl+O | Open |
| Ctrl+S | Save |
| Ctrl+Shift+S | Save As |
| Ctrl+Z | Undo |
| Delete | Remove the selected device |
| Double-click a tile | Define the device |

**Programming page**

| Keys | Action |
|---|---|
| F1 | Keyboard shortcuts |
| F5 / F9 / F6 / F10 / Shift+F5 | Run / Pause / Step rung / Step scan / Stop |
| F7 | Verify |
| Ctrl+Z / Ctrl+Y | Undo / Redo |
| Ctrl+C / Ctrl+V / Ctrl+D | Copy / Paste / Duplicate rung |
| Ctrl+Shift+C / Ctrl+Shift+V | Copy / Paste instruction |
| Delete | Delete rung |
| Ctrl+Up / Ctrl+Down | Move rung up / down |
| Ctrl+E | Rung comment |
| Ctrl+F | Find |
| Ctrl+T | Tags / X-ref |
| Esc | Done - return to cabinet |

**Drawing viewer**

| Keys | Action |
|---|---|
| Left / Right | Previous / Next sheet |
| Ctrl+C | Copy the clicked part |
| Esc | Close |

## Troubleshooting and FAQ

**Windows says "Windows protected your PC".**
Click **More info**, then **Run anyway**. The program is not code-signed yet.

**The app will not start.**
1. Wait 20 seconds. The first start can be slow.
2. Check Task Manager. If Cabinet Studio is already running, switch to it.
3. Portable ZIP: make sure the `_internal` folder is next to `CabinetStudio.exe` and that you extracted the ZIP (do not run it from inside the ZIP).
4. Your antivirus may have blocked it. Ask the person who manages your computer.
5. Reinstall with the installer.

**The rung editor or another window is hidden behind the main window.**
Click its button again; it comes to the front. For the rung editor, tick **Keep on top**. You can also press **Alt+Tab** to find it, or dock it with **Dock editor**.

**I can't find a button.**
1. Make the window bigger (maximize it).
2. Scroll the left rail with the mouse wheel.
3. Look in the menus. Every toolbar button is also in a menu.
4. On the Programming page, toolbars scroll sideways when the window is narrow.
5. Search this manual (Ctrl+F in the browser).

**My drawings did not change after I edited a part.**
Click **Drawings** again to regenerate them.

**The simulator does nothing.**
Click **Run** (or **Normal run**). Check that the E-stop and light curtain inputs are in their safe state. Open **Explain run** to see which rung is waiting.

**Import PLCopen XML refused my file.**
That is on purpose. The import refuses the whole file if anything is unknown, missing or does not match exactly, so you never get a wrong program. Export the file again from the source program, or rebuild the logic by hand.

**The AI says my key is rejected.**
Open **AI settings**, check the key (tick **Show**), click **Test connection**. Make a new key on the provider's website if needed.

**Where did my project go?**
Look in `Documents\Cabinet Studio\saves`. Use **Open** in the program.

**Can Cabinet Studio download the program into my PLC?**
No. It writes import-ready files. You import and download them using the maker's software (Studio 5000, CCW, TIA Portal, Sysmac Studio, CX-Programmer).

## Glossary: words you will see

**AOI (Add-On Instruction)**: a reusable block of ladder logic, like a mini program you can drop into a rung.

**Backplate**: the flat metal sheet inside the cabinet where parts are bolted.

**Branch**: a side path on a rung. Power can go through either path (OR).

**Coil**: the output at the right end of a rung. It turns ON when power reaches it. Also called OTE.

**Contact, NO (normally open, XIC)**: passes power when its tag is ON. Like a doorbell button: the circuit is open until you press it.

**Contact, NC (normally closed, XIO)**: passes power when its tag is OFF. Like a Stop button: the circuit is closed until you press it.

**Contactor**: a heavy-duty electric switch that turns a motor on and off.

**Counter**: counts events (CTU counts up, CTD counts down, RES resets).

**DIN rail**: a standard metal rail (35 mm wide) that parts clip onto.

**Disconnect**: the main power switch for the cabinet.

**Enclosure**: the metal box that holds everything (Hoffman, Saginaw, Hammond are makers).

**E-stop (emergency stop)**: the big red mushroom button that stops the machine in an emergency. It must be hardwired through a safety relay.

**Faceplate**: a ready-made group of HMI objects for one machine part.

**Gauge (wire)**: the thickness of a wire, like 14 AWG. A smaller number means a thicker wire.

**HMI (Human-Machine Interface)**: the touch screen the operator uses.

**I/O (Inputs / Outputs)**: inputs are things the PLC reads (buttons, sensors); outputs are things the PLC turns on (lights, motors, valves).

**Interposing relay**: a small relay between the PLC and a bigger load.

**Ladder logic**: a way of writing PLC programs that looks like a ladder.

**Light curtain**: a row of light beams across an opening. If a beam is broken, the machine must stop.

**NFPA 79 / ISO 13849**: safety standards for industrial machine wiring and safety controls.

**PE (protective earth) / ground bar**: a copper bar where every ground wire connects, for safety.

**PLC (Programmable Logic Controller)**: a tough little computer that runs a machine.

**PLCopen XML**: a standard file format for sharing PLC programs between software.

**Relay**: a switch turned on and off by electricity.

**Rung**: one line of a ladder program, from the left rail to the right rail.

**Safety relay**: a special rated relay that watches E-stops and light curtains and safely cuts power.

**Scan**: one trip of the PLC through every rung, from top to bottom.

**Schematic**: a drawing that shows how parts are wired together, using symbols.

**Simulator**: pretend PLC on your computer, used for safe testing.

**Stack light**: a tower of colored lights on a machine (green, amber, red).

**Tag**: the name of a piece of data in the PLC, like `Start_PB` or `Motor_Run`.

**Timer**: waits a set time. TON waits before turning ON, TOF waits before turning OFF, RTO keeps its time.

**UL 508A**: the US safety standard for building industrial control panels. Cabinet Studio drawings are NOT certified to it.

**VFD (Variable Frequency Drive)**: a box that controls a motor's speed.

**Wire duct**: plastic channel with slots that holds wires neatly between rows of parts.

**Wire number**: a label on each end of a wire so electricians know where it goes.

**Wire schedule**: a table listing every wire with its number, FROM, TO, color and gauge.

## About this manual

Cabinet Studio v0.3.35 · Warren Williams · ERMCO

`NOT A CERTIFIED UL 508A DRAWING. Design aid only.` E-stop and safety functions must be hardwired or use rated safety relays (NFPA 79 / ISO 13849). The software is never the safety function.
