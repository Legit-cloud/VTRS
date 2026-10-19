# VTRS Design System

Version 1.1 · Vote Tracking & Recording Solution · Oyo State pilot

**One web app, role-based.** Since the October 2026 product change there is no separate agent app, party portal or admin app. Everyone uses the same Next.js app; what a person sees depends on their role and assigned scope. The app has two densities, chosen by the screen, not by a separate product:

| Area of the app | Who uses it | Device | Character |
| --- | --- | --- | --- |
| **Agent screens** | Polling unit agents, in their own phone's browser, outdoors, in a crowd | Phone first (360 px up) | Calm, one task per screen, big touch targets |
| **Oversight and admin** | Ward and LGA coordinators, party leadership and admins | Laptop first, still usable on a phone | Clear, scannable, built for monitoring |
| **Platform operator area** | The people who run VTRS for many parties | Laptop | Same language, unmistakably different chrome |

Everything below is generated from `tokens/tokens.json`. If a value here disagrees with that file, the file wins.

---

## 1. Brand foundation

### What the product does for people
VTRS turns a paper result sheet at a polling unit into a verified number on a party's screen within two hours, and keeps the proof. The interface has to earn trust from an agent standing in a crowd with 20% battery and a weak signal, and from a state coordinator reading 351 wards at 2 a.m.

### Personality
**Steady, clear, accountable.** Not flashy, not bureaucratic. The brand speaks like a trusted election clerk: plain words, exact numbers, no drama.

### Three design principles
1. **Numbers are the hero.** Counts, totals and coverage get the biggest type and the cleanest space. Chrome stays quiet.
2. **Say what's true.** Typed on the phone is not the same as received by the server, and numbers without the sheet are not complete. A leader on the dashboard is provisional, from the party's own agents, not the official INEC count. Every state is named honestly.
3. **One next step.** Each agent screen has one job and one primary action pinned at the bottom. Each oversight page has one question it answers.

### The signature: the tally mark
Four upright strokes crossed by a fifth is how people have always counted votes. It is the logo mark and the one memorable device in the system.

- **Logo:** four white strokes with an aqua slash on a teal rounded square (`assets/logo-mark.svg`).
- **TallyMeter:** reporting progress at ward level drawn as real tally groups (see §7.7).
- **Tally pattern:** a faint repeating tile for the sign-in screen and empty states (`assets/tally-pattern.svg`).

Use the tally in those three places only. Everywhere else the system stays plain on purpose, so the mark keeps its meaning.

### What we took from the eBallot reference, and what we changed

| Kept from the reference | Changed, and why |
| --- | --- |
| Teal on white as the brand base, mint tints for fills | Primary button teal is `#008575`, not `#00907F`. The original is 3.97:1 against white text, below the 4.5:1 minimum. The difference is invisible; the pass is not. |
| Rounded back button top-left, wordmark top-right | Back button gets a 48 px hit area (the original is about 24 px) |
| Round icon badge, large two-line heading, short helper text | Same |
| Primary button pinned to the bottom with a trailing arrow | Arrow only on forward steps. Final actions use a check. |
| Bottom sheet with numbered steps before a long process | Same (steps are genuinely sequential) |
| Full-screen success state with a check in a ringed circle | Split into "Numbers submitted" and "Sheet uploaded" so a result without its sheet never looks finished (see §9.5) |
| Mint-filled inputs | Border darkened to `#7C948F` (3.2:1) so fields are visible in direct sun |
| Country code chip beside the phone field | Defaults to +234 |

Not carried over: Aadhaar and voter-ID content, the lotus icon, and the "You voted for" confirmation. VTRS records results for a party; it never shows a voter's choice. Party logos appear only where they identify a row of results (§2.3, rule 8), never in the chrome.

---

## 2. Color

### 2.1 Palette

**Teal (brand)**

| Token | Hex | Use |
| --- | --- | --- |
| teal-50 | `#E6F4F4` | Input fill, selected row, soft backgrounds |
| teal-100 | `#CCEAE6` | Hover on soft fills, disabled button fill |
| teal-200 | `#A3D9D3` | Dividers on teal surfaces, progress track |
| teal-300 | `#66C0B8` | Decorative only |
| teal-400 | `#2DA79A` | Charts, illustration |
| **teal-500** | `#00907F` | **Brand color.** Logo, large icons, big fills, illustration. Not for small text on white. |
| **teal-600** | `#008575` | **Primary action.** Buttons, links, active states, any fill that carries 16 px white text. 4.55:1 on white. |
| teal-700 | `#006D61` | Pressed and hover for primary |
| teal-800 | `#0B4A43` | Text on mint fills, active nav text |
| teal-900 / 950 | `#0A332F` / `#06201D` | Dark surfaces, text on bright teal |
| glow | `#A4F7EF` | The logo slash and sign-in backdrop only |

**Ink (teal-tinted neutrals)**

| Token | Hex | Use |
| --- | --- | --- |
| ink-900 | `#0B2B27` | Body text and headings (15:1 on white) |
| ink-700 | `#2E4A46` | Nav text, strong secondary text |
| ink-600 | `#4B6561` | Secondary text |
| ink-500 | `#5B726E` | Muted text. The lightest text color allowed (5.1:1 on white) |
| ink-400 | `#7C948F` | Input borders, icon outlines (3.2:1) |
| ink-300 | `#C3D3D0` | Dividers on white |
| ink-200 | `#DCE7E5` | Default border |
| ink-100 | `#EDF3F2` | Muted fill |
| ink-50 | `#F3FAF9` | Page canvas |

**Signals** (each has a 50 fill, a 500 mark color and a 700 text color)

| Family | 50 | 500 | 600/700 | Meaning |
| --- | --- | --- | --- | --- |
| Amber | `#FDF1DC` | `#E8A317` | `#8A5A00` | Needs a look, waiting, provisional context, narrow margin |
| Red | `#FBEAEA` | `#D64545` | `#B42F2F` / `#8F2323` | Failed, high-severity anomaly, destructive |
| Blue | `#E6EEFB` | `#3D6FDB` | `#2457C5` / `#1B438F` | Information, sending, low-severity |

**There is no separate success green.** Teal is the brand and also the "good" state: received, complete, verified, reported. Two greens on one screen would blur the two meanings.

**Contestant series** (charts, result bars, the leader colour in war-room lists):
`#00907F` (our party) · `#3D4FD6` · `#C2408A` · `#E0701A` · `#7A5AC8` · `#5B6B7A`, then repeat with a dashed pattern.

Rule: the organisation's own party is always series-1 teal; the others take the next colours in the admin's ballot order for that election. The series colour is not the party's real colour and never claims to be. Always pair a series colour with the party abbreviation (and logo, when there is one), never colour alone.

### 2.2 Themes

| Theme | Where | Look |
| --- | --- | --- |
| **Light** (default) | Every screen | White cards on `#F3FAF9` canvas |
| **War Room** (`.war-room` / `.dark`) | Optional for command-centre wall screens and night shifts | Deep teal-ink `#071A18`, cards `#0E2A27`, primary brightens to `#2FD1BC` |
| **Platform chrome** (`data-surface="admin"`) | Platform operator area | Light content; distinct sidebar and a slim top strip reading "Platform admin" |

Dark mode is a purpose-built theme, not an inversion. Every pair is checked in `build-tokens.mjs`.

### 2.3 Color rules
1. One primary-filled button per screen.
2. Teal text on a mint fill uses **teal-800**, never teal-600 (4.0:1 fails).
3. Muted text is never lighter than ink-500.
4. Status is never color alone: every status has an icon and a word.
5. Red is reserved for failure and danger. A "reported late" row is amber, not red.
6. Large tinted areas stay at 50 level. Saturated teal is for small, important things.
7. Gradients: none, except the `glow` wash behind the sign-in screen.
8. Party logos are content, not decoration: shown at 24 to 32 px beside the party abbreviation in result rows, contestant lists and the war room. Never in the navigation, header or page chrome, never tinted, never as a background.

### 2.4 Status vocabularies (use exactly these)

**Submission status** (agent screens and oversight, from PRD §6.6 revised)

| Status | Icon (Lucide) | Colors | Label |
| --- | --- | --- | --- |
| Draft | `pencil` | ink-100 / ink-700 | Draft on this phone |
| Sending | `refresh-cw` (rotating) | blue-50 / blue-700 | Sending |
| Numbers submitted | `file-clock` | amber-50 / amber-700 | Sheet missing |
| Complete | `check-circle-2` | teal-50 / teal-800 | Sheet uploaded |
| Not sent | `alert-circle` | red-50 / red-700 | Not sent |

**Review status:** Unverified (ink) · Needs review (amber, `flag`) · Verified (teal) · Rejected (red) · Corrected (amber, shows "Version 2").

**Leader status** (war room, every level): Leading (no chip, the leader's abbreviation in its series colour) · **Narrow** (amber, `scale`, "Narrow margin") · **Tied** (amber, `equal`, "Tied") · No results (ink, "No results yet").

**Anomaly severity:** Low (blue) · Medium (amber) · High (red). Types: Duplicate submission, Over-voting, Location mismatch, Timestamp, Evidence mismatch, Totals variance.

**Provisional:** a dashed 1.5 px ink-700 outline on ink-50 with a `hourglass` icon and the word "Provisional". The dashed border means "not final" and is used for nothing else. Shown beside every leader, margin and total on the war room. See §7.4.

---

## 3. Typography

**Family: Onest** (SIL Open Font License; weights 400, 500, 600, 700, 800). A geometric sans with open apertures that stays legible at small sizes, and it has tabular figures. It has no ₦ glyph; the system font supplies it. If ₦ ever appears prominently, pair with a font that has it.

Monospace (`ui-monospace`) is permitted for exactly three things: SHA-256 hashes, submission IDs, and PU codes.

### 3.1 Scales

**Agent screens (phone)**

| Role | Size / line | Weight | Use |
| --- | --- | --- | --- |
| display | 34 / 38 | 800 | Screen headline ("Enter the votes") |
| title | 26 / 32 | 700 | Sheet titles, status headings |
| heading | 20 / 26 | 700 | Card headings, section titles |
| body-lg | 17 / 26 | 400 | Helper text under headlines |
| body | 16 / 24 | 400 | Default. Never smaller for anything the agent must read |
| label | 15 / 20 | 600 | Field labels, chips, party abbreviations |
| caption | 13 / 18 | 500 | Timestamps, secondary detail |
| numeral | 44 / 48 | 800 | Vote counts, totals, tabular |

**Oversight and admin**

| Role | Size / line | Weight | Use |
| --- | --- | --- | --- |
| display | 40 / 44 | 800 | Hero numbers on the war room |
| h1 | 28 / 34 | 700 | Page title |
| h2 | 22 / 28 | 700 | Section title |
| h3 | 17 / 24 | 650 | Card title |
| body | 15 / 22 | 400 | Default |
| body-sm | 14 / 20 | 400 | Tables, dense lists |
| label | 13 / 18 | 600 | Form labels, chips, column heads |
| caption | 12 / 16 | 500 | Metadata. Minimum size on web |
| numeral | 40 / 44 | 800 | Stat tiles |

### 3.2 Rules
- **Sentence case everywhere.** No all-caps labels, including table headers and chips. Party abbreviations (APC, PDP, LP, ADC) keep their own capitals.
- **Tabular numerals on every number that can change or be compared** (`font-variant-numeric: tabular-nums`).
- Line length under 70 characters in prose.
- Headlines are one weight and one color. Do not highlight a single word.
- Format numbers with thousands separators: `6,390`. Percentages with one decimal when under 100: `94.3%`.
- Dates: `12 Oct 2026, 14:05` (24-hour, Africa/Lagos). Always show the time zone once per screen if more than one is possible.

---

## 4. Space, shape, depth, motion, icons

**Spacing:** 4 px base. Allowed values: 4, 8, 12, 16, 20, 24, 32, 40, 48, 64, 80. Agent screen padding 16 to 24. Oversight page padding 32 (24 under 1024 px, 16 under 640 px). Gap between cards 16 (oversight), 12 (agent).

**Radius follows density**

| | Controls | Cards | Sheets / dialogs | Chips |
| --- | --- | --- | --- | --- |
| Agent screens | 16 | 24 | 28 (top) | full |
| Oversight and admin | 10 | 14 | 20 | full |

**Touch and control sizes:** agent controls 56 high, minimum hit area 48 × 48 anywhere. Oversight controls 40 high (32 in dense tables), rows 48 (40 dense).

**Depth:** borders first, shadows second. Cards on white use a 1 px `border` plus `shadow-card`. Floating things (menus, toasts) use `shadow-float`. Bottom sheets use `shadow-sheet`. Nothing else casts a shadow.

**Motion** (140 / 220 / 360 ms, standard easing `cubic-bezier(0.2, 0.8, 0.2, 1)`)
- Motion answers an action: a sheet rising, a row expanding, a status changing.
- One signature moment: when the sheet is uploaded and the submission is complete, the check draws itself (360 ms).
- No entrance animations on page load, no hover lifts on cards.
- Honor reduced motion: replace movement with an instant change.

**Icons:** Lucide (`lucide-react`). 24 px on agent screens, 20 px elsewhere, 1.75 stroke, round caps. Icons inside a 48 px round badge use teal-50 fill with a teal-600 icon (as in the reference screens).

---

## 5. Voice and copy

Plain, short, sentence case. Name things the way an agent would. Say what happened and what to do next. Errors do not apologize.

| Situation | Write | Don't write |
| --- | --- | --- |
| Numbers received | "Votes received. Now add a photo or PDF of the result sheet." | "Success!" |
| Sheet uploaded | "Result sheet uploaded. Your result is complete." | "Submission complete" |
| Sending failed | "Not sent yet. We'll keep trying. Your numbers are kept on this phone." | "Error 500" |
| Upload failed | "Upload didn't finish. Trying again (attempt 2 of 5)." | "Upload error" |
| Blank party field | "Enter APC's votes. Use 0 if they got none." | "Required" |
| Totals too high | "Party votes plus rejected (415) are more than total votes cast (412). Check the result sheet." | "Invalid input" |
| Party not on the form | "Is a party or candidate missing? Tell an admin. Don't add it to another party's votes." | "Contact support" |
| Wrong location | "You're 1.4 km from Ward 5, PU 012." | "Geofence violation" |
| Provisional | "Provisional. Collected by our agents so far. Not the official INEC count." | "Winner" |
| Tied | "Tied: APC and PDP have 1,204 each." | "Leader: APC" |
| Empty anomalies | "No anomalies in your area. New flags appear here as results come in." | "Nothing to see" |
| Destructive confirm | "Remove Adaeze Bello from Ward 5? She will lose access to Polling Unit 012." | "Are you sure?" |

Action names stay constant through a flow: the button says **Send votes**, the toast says "Votes received", the history says "Received". Then **Upload sheet**, "Sheet uploaded", "Complete".

Buttons: verb first, specific. Continue, Send votes, Upload sheet, Invite agent, Verify result, Download evidence pack. Never "Submit" or "OK".

Never use the words "winner", "won" or "declared" without "provisional" next to them. Never show the word "official" except to say a number is not.

---

## 6. Layout patterns

### 6.1 Agent screen anatomy (phone browser)

```
┌──────────────────────────┐
│ [‹]                 VTRS │  back button 48×48 · wordmark right
│ Ward 5 · PU 012          │  where you are, caption
│                          │
│  Enter the votes         │  display, ink-900
│  helper text, body-lg,   │  ink-600, max 2–3 lines
│  ink-600                 │
│                          │
│  [logo] APC              │  one row per configured party
│  Adebayo Musa  [   412 ] │  candidate name, numeric field 56 high
│  ...                     │
│          (space)         │  content scrolls, CTA does not
│                          │
│  [ Send votes        → ] │  pinned primary, 56 high, 16-24 side margin
└──────────────────────────┘
```

Rules: left-aligned content (centered only for status screens such as "Sheet uploaded"); the CTA sits 16 px above the bottom edge and above the on-screen keyboard; background is white for entry screens and `#F3FAF9` for list screens with white cards. No horizontal scrolling at 360 px.

### 6.2 App shell (oversight and admin)

```
┌─────────┬──────────────────────────────────────────────┐
│ VTRS    │ Election ▾   Scope: Oyo State › Ibadan North │  64 px top bar
│         ├──────────────────────────────────────────────┤
│ War room│  Page title                    [actions]     │
│ Results │                                              │
│ Verify  │  content, max width 1440, 32 px padding      │
│ Anomal. │                                              │
│ Agents  │                                              │
│ Parties │                                              │
│ Team    │                                              │
└─────────┴──────────────────────────────────────────────┘
 264 px sidebar (72 collapsed, drawer under 1024 px), white, ink-700 text
```

The navigation shows only what the role may use. Agents get a simple top bar and their assignment list instead of the sidebar.

The **scope bar** is always visible to coordinators and admins. It shows the user's geographic limit as a breadcrumb (Oyo State › Ibadan North LGA › Ward 5). Users with a narrower scope see a lock icon and cannot step above it. This makes the server-side permission rule visible to the user.

### 6.3 Platform operator area
Same grid with three differences so nobody mistakes it for a party's view:
1. A distinct sidebar.
2. A 32 px strip across the very top always reads "Platform admin" with the environment name (Production or Staging).
3. The scope bar is replaced by an **Organisation switcher** that shows which party you are acting on, if any.

---

## 7. Components

Every component has the same states: default, hover (pointer devices), pressed, focus-visible, disabled, loading, error. Focus is a 2 px ring in teal-500 with 2 px offset, on every surface.

### 7.1 Button

| Variant | Fill | Label | Use |
| --- | --- | --- | --- |
| Primary | teal-600, pressed teal-700 | white | The one main action |
| Secondary | teal-50, pressed teal-100 | teal-800 | Alternatives |
| Outline | transparent, 1.5 px ink-400 border | ink-900 | Tertiary |
| Ghost | transparent | teal-700 | Inline actions in tables |
| Danger | red-600 | white | Destructive confirms only |

Sizes: agent 56 (radius 16); oversight 40 and 32 (radius 10). Trailing arrow icon (`arrow-right`, 20 px) only on forward-moving primary buttons in a flow. Final actions use a leading `check`. Disabled: teal-100 fill, ink-500 label, no shadow. Loading: label replaced by a 20 px spinner, width locked.

### 7.2 Inputs
Mint fill (`teal-50`), 1.5 px `ink-400` border, radius 16 agent / 10 oversight, label above (label style, ink-700), helper below (caption, ink-600). Focus: 2 px teal-600 border plus `shadow-focus`. Error: red-600 border, red-700 message with `alert-circle`, message says how to fix it.

- **Phone field:** a separate chip for the country code (`+234`, same fill and height) plus the number field, with a clear (✕) button. Auto-format as `0803 123 4567`.
- **OTP:** six boxes, 48 × 56, auto-advance, paste support, "Resend in 0:30" countdown as a ghost button.
- **Numeric vote field:** 56 high, `numeral` size, right-aligned, `inputmode="numeric"`, tabular figures, selects all on focus. Empty is an error on send ("Use 0 if they got none"), never silently zero.
- **Result sheet file input:** a large secondary button "Take photo or choose file" over a native `<input type="file" accept="image/*,application/pdf" capture="environment">`. The phone offers the camera and its files; there is no custom in-page camera. After choosing, show a thumbnail (or a PDF icon with the file name and size), the compressed size, and "Use this file" / "Choose again".
- **Consent checkbox:** 24 px box (48 px row hit area), label in body, key phrase in ink-900 semibold.

### 7.3 Bottom sheet with steps
White, top radius 28, grabber, dimmed scrim at 50%. Title (title style), then a vertical list of numbered steps (32 px rounded squares, teal-600 outline, number inside; completed steps fill teal-600 with a check; current step has a 3 px teal-200 ring). One primary button at the bottom. Use whenever an action starts a process with 2 to 4 known stages (the agent flow: Votes · Totals · Result sheet).

### 7.4 Provisional badge
`hourglass` icon + "Provisional", 13/18 semibold ink-700, dashed 1.5 px ink-700 outline, ink-50 fill, radius full. On first use per screen add the caption "Collected by our agents so far. Not the official INEC count." Mandatory beside any leader, margin or total on the war room. Never hide it on small screens; shorten the caption instead.

### 7.5 Status chip
Height 24 (agent 28), radius full, 13 px label semibold, leading 14 px icon. Fill = signal 50, text = signal 700, per §2.4. Never a bare colored dot.

### 7.6 Stat tile
White card, radius 14, padding 20. Value in `numeral`, label below in body-sm ink-600, optional delta chip. Max one tile in a row is emphasized (teal-950 fill, white value): the reporting-coverage tile.

```
┌──────────────────────┐
│ 5,214 of 6,390       │  numeral, tabular
│ Polling units reported│  body-sm ink-600
│ ▓▓▓▓▓▓▓▓▓▓▓▓▓░░ 81.6%│  progress bar teal-600 on teal-100
└──────────────────────┘
```

### 7.7 TallyMeter
Reporting progress where the count is small enough to see: ward (typically under 40 PUs). Each reported PU is a stroke; each group of five is four vertical strokes plus a slash. Reported strokes are teal-600, not yet reported are 1.5 px ink-400 outlines. Below it: "17 of 24 reported". Above 60 units, switch to the plain progress bar. Stroke 4 × 22 px, 8 px gap, slash 2 px longer.

### 7.8 Contestant result bar
Row: party logo (24 px, if any) and abbreviation (label, 600), candidate name (body-sm ink-600) when the area is one constituency, vote count (numeral, right), horizontal bar in the party's series color on ink-100, percentage after the bar. The leader row gets the Provisional badge; tied rows each get the "Tied" chip; a narrow lead gets "Narrow margin". Minimum bar height 12; label always visible, not only on hover.

### 7.9 Party row (agent form)
Card row, 72 high minimum: logo (32 px) or a 32 px ink-100 square with the abbreviation's first letter, abbreviation (label 600) and full name (caption), candidate name (body), and the numeric vote field on the right (or below at very narrow widths). The row is read-only apart from the number: no remove, no rename, no reorder.

### 7.10 Evidence card
Thumbnail 72 × 96 (photo, tap to zoom; PDF shows a document icon), title "EC8A · Ward 5, PU 012", status chip (Uploaded / Verified hash / Hash mismatch), line 2: captured time and agent, line 3: `SHA-256 3f9a…c21e` in mono with a copy button. A "Chain of custody" ghost button opens the timeline (§7.13).

### 7.11 Anomaly card
Left 4 px severity bar, severity chip, type name (heading 17), one-line reason ("Votes recorded 3 minutes after another submission from the same unit"), location with scope breadcrumb, time, primary action "Review" and ghost "Assign". Resolved cards drop to ink-100 with a `check` icon.

### 7.12 Data table
Row 48 (dense 40), header row ink-50 with label-style text, sticky header, sort chevrons, 1 px ink-200 row dividers, no zebra. Numeric columns right-aligned and tabular. Selected row teal-50. A drill-down row shows a chevron; the first column is the link. Empty state inside the table, never a blank body. Tables scroll inside their container on phones, never the page.

### 7.13 Timeline (audit and chain of custody)
Vertical line ink-300, 12 px nodes (teal-600 filled for system events, ink-700 outline for human actions), each entry: action in body 600, who and when in caption, expandable detail. Append-only: no edit or delete affordances.

### 7.14 Banners and toasts
- **Connection banner** (agent screens, pinned under the top bar): amber-50, `wifi-off`, "No connection. Your numbers are kept on this phone; we'll send them when you're back." Turns teal-50 "Back online. Sending…" when it returns.
- **Upload progress:** a bar with the percentage and the attempt number; on success the "Sheet uploaded" check.
- **Toast:** bottom-center, ink-900, white text, 4 s, one line, repeats the button's verb ("Result verified").
- **Inline alert:** 4 px left bar in the signal color, signal-50 fill, icon, title, one sentence, optional action.

### 7.15 Dialog
Radius 20, max width 480 (full width minus 32 on phones), title, one or two sentences, two buttons (cancel left or ghost, confirm right). Destructive dialogs name the thing and the consequence, and high-impact actions (suspend organisation, delete election) require typing the object's name.

### 7.16 Empty state
Tally pattern at 60% behind a 64 px icon badge, heading (h3), one sentence saying what will appear and how to fill it, one action. Never just "No data".

---

## 8. Data visualization

- Contestant comparisons use the series palette in ballot order, with direct labels (abbreviation) at the bar ends, not a detached legend.
- **Leader colouring (list and map):** each area or polling unit row carries a 6 px left bar and a chip in the leading party's series colour with its abbreviation. Tied and narrow areas use the amber "Tied" / "Narrow margin" chip instead of a single colour. Areas with no results are ink-100 with a dashed outline.
- Sequential scale for coverage choropleths: ink-50 → teal-200 → teal-400 → teal-600 → teal-800. Unreported units are ink-100 with a dashed outline.
- Anomaly markers on a map: red-500 (high), amber-500 (medium), blue-500 (low), 12 px with a white 2 px ring, plus a different shape per severity (circle, diamond, square) so color-blind users can tell them apart.
- Map style (when coordinates exist): light version uses a desaturated ink-50 base with ink-300 boundaries; War Room uses `#071A18` land and `#1F4741` boundaries. The list view is always available and is the default.
- Reporting-over-time chart: one teal-600 line, a dashed ink-400 "target" line (95% by 2 hours), axis labels 12 px ink-600, tabular numbers.
- Never use red and green together to mean bad and good. Teal and amber and red are distinguishable by lightness and by icon.

---

## 9. Agent screens (web, phone first)

### 9.1 Principles
- **One task per screen**, one pinned primary action.
- **Works in sun and in a crowd:** text 16 px minimum, contrast above 4.5:1, 48 px touch targets, no gestures that have no button equivalent.
- **A weak signal is normal, not an error:** typed numbers are kept as a draft on the phone; sends and uploads retry automatically and say so.
- **Always show where the result is:** draft on this phone, sending, numbers received, sheet uploaded (complete).
- Low-end Android first: no blur, no large animated assets, photos compressed before upload, small JavaScript bundle for these screens.
- Nothing about the party list is editable by the agent.

### 9.2 Navigation
No sidebar. A slim top bar (wordmark, the agent's name, Sign out) and a single list: **My polling units**. The capture flow replaces the list with a step bar (Votes · Totals · Result sheet).

### 9.3 Screens

| Screen | Composition | Primary action |
| --- | --- | --- |
| Sign in | Logo on the tally backdrop, phone number (or email) and password | Sign in → |
| Accept invite | Opened from the SMS link: code, OTP to the invited phone, set password | Continue → |
| My polling units | One card per assignment: election, PU name and code, ward, LGA, and the submission status chip (§2.4) | Enter result → (or Upload sheet → when the sheet is missing) |
| Votes | Step 1. One party row per configured party (§7.9), in the admin's order, every row required. Link at the bottom: "Party or candidate missing?" | Next → |
| Totals | Step 2. Accredited voters, total votes cast, rejected votes, with a live check: "Party votes 400 + rejected 12 = 412 of 412 cast ✓" in teal, or the mismatch message in red with the numbers | Review → |
| Review | Read-only summary of every number; "Edit" returns to the step. Location is asked for here, with the one-sentence reason | ✓ Send votes |
| Numbers received | Status screen: amber "Sheet missing" chip, one sentence, the file input (§7.2) | Upload sheet → |
| Upload | Thumbnail or PDF card, compressed size, progress bar with attempt count | Use this file → |
| Complete | Centered status screen (§9.5) | Back to my polling units |
| Party or candidate missing | Choice (party missing / candidate missing) and a note (required) | Send to admin |

### 9.4 Result entry rules
- `inputmode="numeric"`, one field focused at a time, "Next" on the keyboard moves down.
- Every party row needs a number; zero is fine, blank is not.
- The Totals step checks live: party votes + rejected must not exceed total votes cast; total votes cast must not exceed accredited voters. The send button stays enabled; on send, the first failing rule is shown in words with the numbers.
- The Review screen shows each number again with no editing in place; "Edit" returns to the step.
- The form keeps a draft on the phone after every field, with the submission id created when the form opened, so a reload, a double tap or a retry never creates a second result.
- Corrections: from "My polling units", "Correct the result" opens the form prefilled from the current version and sends a new version. Nothing is overwritten.
- Warn before leaving with unsent numbers: "Leave this page? Your numbers stay saved on this phone."

### 9.5 Confirmation states (the reference's "Vote submitted" screen, made honest)

| State | Icon | Headline | Body | Button |
| --- | --- | --- | --- | --- |
| Numbers received | Amber-50 circle, `file-clock` | Votes received | Now add a photo or PDF of the result sheet. Your result isn't complete without it. | Upload sheet |
| Complete | Teal circle, white check, two concentric rings; the check draws in 360 ms | Result sheet uploaded | Your party can now see Ward 5, PU 012, with its sheet. | Back to my polling units |
| Needs review | Amber-50 circle, `flag` | Received, needs review | A coordinator will check one thing: location didn't match. You don't need to do anything. | Upload sheet (if missing) |
| Not sent | Red-50 circle, `alert-circle` | Not sent yet | Your numbers are kept on this phone. We're trying again; check your network. | Try again now |

Do not auto-dismiss any of these. A result confirmation stays until the agent leaves it.

### 9.6 Permission prompts
Ask for location only at the moment of sending, with a one-sentence reason first ("We record your location once, when you send the result, to confirm you're at your polling unit. We don't track you."), then the browser prompt. If the agent declines, the result still sends (and is flagged for a coordinator). The camera is opened by the phone's own file picker; no camera permission prompt from the page.

---

## 10. Oversight and admin screens

### 10.1 Navigation (sidebar, in order)
War room · Results · Verify results (count badge) · Anomalies (count badge) · Agents · Elections · Parties · Configuration issues (count badge) · Evidence · Reports · Team and permissions · Audit log · Settings. Items are shown only if the role permits them; the scope bar limits the data inside. Coordinators see War room, Results, Verify results, Anomalies and Evidence for their area.

### 10.2 War room (the signature page)
Light by default; the War Room theme is optional for wall screens. Layout on a 1440 px screen (stacks to one column on a phone):

```
┌──────────────────────────────────────────────────────────────┐
│ Oyo · Governorship 2027 · Live          Provisional · 14:32  │ header strip
│ Our agents' collection, not the official INEC count.         │
│ [ All results | Verified only ]                              │ filter
├───────────────┬───────────────┬───────────────┬──────────────┤
│ Reporting     │ Leading       │ Margin        │ Open         │ 4 stat tiles
│ 5,214 of 6,390│ APC           │ 12,480 votes  │ anomalies 23 │
│ 81.6%         │ [Provisional] │ [Provisional] │              │
├───────────────┴───────────────┴───────────────┴──────────────┤
│ Every contestant, side by side (bars, ballot order kept       │
│ in the legend, sorted by votes in the chart)                  │
├──────────────────────────────────────────────────────────────┤
│ Areas (list, default) | Map                                   │
│ LGA          Reported   APC    PDP    LP    Leader            │
│ Ibadan N.    41 of 52   9,120  8,960  402   [Narrow] ›        │
│ Ogbomosho S. 30 of 30   5,004  5,004  210   [Tied] ›          │
└──────────────────────────────────────────────────────────────┘
```

Rules:
- Every contestant in the election is shown side by side; within one constituency the row names the candidate, across constituencies (for example a senatorial election state-wide) the column is the party.
- "X of Y polling units reported" sits beside every total, at every level, so a partial count is never read as final.
- The verified filter switches every figure on the page between all results and verified only; the active filter is named in the header.
- Ties and narrow margins are named as such ("Tied", "Narrow margin") instead of a single leader. The Leading tile then reads "Tied: APC, PDP".
- The numeric hero is reporting coverage, because the pilot's goal is 95% visibility in two hours.
- A live indicator ("Live" with a 6 px pulsing dot, motion reduced when requested) shows the WebSocket state; if it drops, a banner reads "Live updates paused. Reconnecting…" and numbers are marked with their "as of" time.

### 10.3 Drill-down
State → LGA → Ward → Polling unit uses the same page template at each level: breadcrumb (stopping at the user's scope), summary tiles, the contestant bars, and a table of children (name, X of Y reported, each party's votes, leader chip, open anomalies), each row coloured by its leader (§8). Row click goes down one level. At polling-unit level each row is one unit with its leader, verification chip and sheet status; opening a unit shows the result, the evidence card, the version history and the verification actions.

### 10.4 Verify results (coordinators and admins)
Queue of unverified results in the user's area, oldest first. Two panes: the numbers (party rows in ballot order and totals) on the left, the uploaded sheet on the right (zoomable photo or PDF). Actions: **Verify result** (only when a sheet is attached; acknowledging any open flags), **Reject** (reason required; the agent sends a corrected version). Results without a sheet show "Waiting for the sheet" and cannot be verified.

### 10.5 Anomalies queue
Two panes: filterable list (severity, type, LGA, status) on the left, selected anomaly detail on the right with the evidence, the numbers involved, location and the reason text. Actions: Verify result, Reject result, Assign, Mark resolved (requires a note).

### 10.6 Agents
Table of agents (name, phone, assigned PU, status: Invited, Active, Deactivated; last submission). "Invite agent" opens a side panel: name, phone, select Polling Unit(s) from a searchable Ward › PU picker, send invite by SMS. Bulk invite by CSV with a validation preview that flags rows with errors before sending.

### 10.7 Parties (admins only)
The party master list: logo, abbreviation, full name, "Our party" marker (one per organisation). Add, edit, upload or remove a logo (PNG, JPEG or WebP, small square), remove a party that no election uses.

### 10.8 Elections (admins only)
A workflow, not a form: (1) name, state, date and **election type** (which sets the constituency kind); (2) **contesting parties**: pick from the party list and drag (or use up/down buttons) into the order the result sheet uses; (3) **contestants**: per constituency, one candidate name per contesting party; a progress list shows constituencies with and without contestants; (4) lock and open. Changes stop at lock.

### 10.9 Configuration issues (admins only)
Tasks raised by agents ("party missing", "contestant missing"): polling unit, agent, note, time. Resolve with a note after fixing the configuration (before lock) or explaining why not. Resolving never adds a party or contestant by itself.

### 10.10 Evidence
Grid and list toggle of result sheets (photos and PDFs) with hash status; filters by ward and verification state; multi-select → "Download evidence pack". The pack dialog states what is included and that access is logged.

### 10.11 Team and permissions
Roles table and a scope picker. Show the permission as a sentence: "Ward coordinator · Ibadan North · Ward 5 only". Changing a role or scope writes to the audit log and says so in the confirm dialog.

### 10.12 Settings
Organisation profile, notification channels, evidence retention and export policy (read-only text from platform policy), MFA.

---

## 11. Platform operator area

For the people who run VTRS across all parties. It shares tokens and components; only chrome, density and safety patterns differ. Operators see no party results.

### 11.1 Navigation
Overview · Organisations · Verification queue · Elections · Master data · System health · Messaging providers · Audit log.

### 11.2 Pages

| Page | What it answers | Key components |
| --- | --- | --- |
| Overview | Is the platform healthy and who needs attention? | Tiles: active organisations, submissions per hour vs the 10,000 target, p95 dashboard load vs 3 s, open incidents; a "needs attention" list |
| Organisations | Who is on the platform and in what state? | Table: name, status (Pending, Verified, Suspended), elections, agents, created; detail page with owner, documents, activity |
| Verification queue | Which new organisations and admins need identity review? | Split view: submitted details, Approve / Request more info / Reject with reason. Face data is shown only if the biometric requirement was approved |
| Elections | What elections exist and are locked? | Timeline per election, config-lock status |
| Master data | Is the LGA, ward, PU and constituency dataset correct? | Import summaries, constituency coverage per kind, PU search |
| System health | Is it up right now? | API latency, queue depth, WebSocket connections, submission failures per minute, storage, provider status |
| Messaging providers | Do OTPs and alerts get delivered? | Provider cards with delivery rate, failover order, test-send action |
| Audit log | Who did what? | Filterable timeline, export |

### 11.3 Safety patterns
- **Typed confirmation** for suspending an organisation, locking or unlocking an election, or deleting data.
- **Environment label** in the top strip is amber when Staging, ink when Production.
- **Dense by default:** 40 px table rows, 14 px body, side-by-side detail panes.

---

## 12. Accessibility and performance floor

- Text contrast 4.5:1 (7:1 for body copy); UI boundary contrast 3:1. Enforced by `scripts/build-tokens.mjs`, which fails the build if a declared pair drops.
- Visible focus on every interactive element; logical tab order; Esc closes overlays; dialogs trap focus.
- Every icon-only button has a text label for screen readers; every chart has a text summary or table alternative.
- Never convey status by color alone; every party colour comes with its abbreviation.
- Respect reduced motion and OS text size. Agent screens support up to 130% font scale without clipping.
- Touch targets 48 × 48 minimum.
- Responsive down to 360 px; tables scroll horizontally inside their container, never the page. Core Web Vitals targets: LCP under 2.5 s on a mid-range laptop, dashboard under 3 s (PRD §7.3), agent result form interactive within 3 s on a low-end Android phone over 3G after the first visit.
- Photos are compressed on the phone before upload (about 1-2 MB, sheet still legible).

---

## 13. Implementation

### 13.1 Folder map

```
frontend/
├── design-system/
│   ├── README.md               how to use
│   ├── DESIGN_SYSTEM.md        this file
│   ├── tokens/
│   │   ├── tokens.json         source of truth
│   │   ├── globals.css         GENERATED: CSS variables, themes, base styles
│   │   ├── tailwind.preset.ts  GENERATED: Tailwind v3 preset
│   │   └── tailwind-v4.css     GENERATED: Tailwind v4 @theme mapping
│   ├── assets/                 logos, tally pattern
│   └── scripts/build-tokens.mjs
├── packages/core/              API types and client, canonical hashing, arithmetic, copy
├── apps/portal/                the one web app (Next.js)
└── e2e/                        Playwright suites, including phone-sized agent runs
```

### 13.2 Web (Next.js)
1. Import `tokens/globals.css` in the root layout. Replace shadcn's default `:root` variables with it.
2. Tailwind v3: `presets: [require("./design-system/tokens/tailwind.preset")]`. Tailwind v4: import `tailwind-v4.css` after `globals.css`.
3. Fonts with `next/font/google`: `Onest({ subsets: ["latin"], weight: ["400","500","600","700","800"], variable: "--font-sans" })`, applied on `<html>`.
4. `<html>` has no class (light); the war room can wrap its page in `className="war-room"` when the dark theme is chosen. Platform shell: `data-surface="admin"` on the shell element.
5. shadcn/ui components work unchanged because `--primary`, `--border`, `--ring`, `--radius` and friends are all defined.
6. Build the VTRS-specific components (ProvisionalBadge, StatusChip, TallyMeter, ScopeBar, ContestantBar, PartyRow, EvidenceCard, AnomalyCard) once in `components/vtrs/` and reuse them everywhere.
7. Agent screens live under their own route group with a light layout (no sidebar, no charting libraries) to keep the phone bundle small. Drafts use `localStorage` inside try/catch and hold only the numbers being typed and the submission id.
8. An installable web app (PWA manifest, home-screen icon) is an optional later improvement, not part of this version.

### 13.3 Changing a token
Edit `tokens/tokens.json`, then `node scripts/build-tokens.mjs`. The script prints every contrast check and refuses to write files if any fail. Commit the regenerated files.

---

## 14. Do and don't

**Do**
- Keep one primary button per screen and pin it on agent screens.
- Show numbers large, tabular, with "X of Y reported" and their "as of" time when live.
- Put the Provisional badge next to every leader, margin and total.
- Name the real state: draft on this phone, sending, numbers received, sheet uploaded.
- Name ties and narrow margins instead of picking a leader.
- Use teal-600 for actions, teal-500 for brand moments.
- Use the tally mark only for the logo, TallyMeter and the pattern.

**Don't**
- Don't use all-caps labels (party abbreviations excepted), gradients, glass effects, or decorative illustration.
- Don't invent new greens, or use red and green together.
- Don't use teal-500 for small text on white.
- Don't ask the agent to retype what the app already knows (polling unit, election, parties, candidates, time).
- Don't let the agent add, rename, remove or reorder a party.
- Don't show the word "winner" without "provisional".
- Don't use party colours or imagery in the app chrome; logos only identify result rows.
- Don't build a custom in-page camera; use the phone's file picker with the camera option.
- Don't add entrance animations to pages or hover lifts to cards.

---

## 15. Open decisions

1. **Platform operator vs party admin.** The design keeps them as separate roles in one app; the operator sees no party results. Confirm.
2. **Organisation theming.** Parties can upload a logo for their party record; the app chrome stays VTRS. Decide if organisations get any accent beyond that.
3. **Hausa, Yoruba and Pidgin.** Agent copy in Yoruba would likely help in Oyo. Strings are short and in a central file; Yoruba exists for the agent screens and needs a native-speaker review.
4. **Face verification UI** is not designed; it is subject to the privacy and legal review in the PRD (§6.1, §10).
5. **Map view.** The war room's list view is complete; a map needs boundary or PU coordinate data that the interim directories do not have.
6. **Installable web app (PWA).** Optional later improvement.
7. **₦ glyph.** Onest has none. If money ever appears (billing, for example), choose a companion font.
