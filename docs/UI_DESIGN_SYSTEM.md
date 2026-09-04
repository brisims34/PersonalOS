# PersonalOS — UI Design System

The concrete patterns behind the Key Principles in `PersonalOS_Spec.md` §2. Read before any UI work.

**Constraint that shapes everything here:** no build step. Bootstrap 5.3 vendored locally, CSS custom properties, vanilla JavaScript. Every pattern below is achievable without a bundler.

---

## 1. Theme

Dark-first, using Bootstrap 5.3's native `data-bs-theme` attribute. Light mode is a toggle, not a second stylesheet — supporting both costs almost nothing once tokens are variables.

```html
<html lang="en" data-bs-theme="dark">
```

Toggle persists to `app_settings.theme` and applies before first paint via a tiny inline script in `<head>`, so there is no flash of the wrong theme.

### Token set

Defined once in `static/css/personalos.css`:

```css
:root[data-bs-theme="dark"] {
  --pos-surface-0:    #0f1216;   /* page background */
  --pos-surface-1:    #161b22;   /* card, sidebar */
  --pos-surface-2:    #1c232c;   /* raised, hover */
  --pos-surface-3:    #232c37;   /* active, selected */
  --pos-border:       #2d3742;
  --pos-border-strong:#3d4a58;
  --pos-text:         #e6edf3;
  --pos-text-muted:   #8b98a5;
  --pos-text-subtle:  #6b7684;
  --pos-accent:       #4a9eff;
  --pos-accent-2:     #a970ff;   /* coverage gradient end */
  --pos-focus-ring:   #4a9eff;
}

:root[data-bs-theme="light"] {
  --pos-surface-0:    #ffffff;
  --pos-surface-1:    #f6f8fa;
  --pos-surface-2:    #eef1f4;
  --pos-surface-3:    #e3e8ed;
  --pos-border:       #d0d7de;
  --pos-border-strong:#afb8c1;
  --pos-text:         #1f2328;
  --pos-text-muted:   #59636e;
  --pos-text-subtle:  #818b98;
  --pos-accent:       #0969da;
  --pos-accent-2:     #8250df;
  --pos-focus-ring:   #0969da;
}
```

### Semantic colours

Never used alone to convey state — see §7.

| Token | Dark | Light | Meaning |
|---|---|---|---|
| `--pos-ok` | `#3fb950` | `#1a7f37` | green / on track / good capacity |
| `--pos-warn` | `#d29922` | `#9a6700` | amber / at risk / near full |
| `--pos-danger` | `#f85149` | `#cf222e` | red / off track / over capacity |
| `--pos-bench` | `#58a6ff` | `#0969da` | blue — under-utilised, available |
| `--pos-neutral` | `#8b98a5` | `#59636e` | not applicable / not started |

---

## 2. The Object Grammar

**Every entity page has the same five-part shape.** Learn one, know all. A module that needs a bespoke layout is a signal to reshape the module, not to grant an exception.

```
┌─────────────────────────────────────────────────────────┐
│ ① IDENTITY HEADER                                       │
│    Breadcrumb › path                                    │
│    Name                        [status] [priority] [RAG]│
│    Subtitle: client · code · dates                      │
├─────────────────────────────────────────────────────────┤
│ ② ACTION BAR                                            │
│    [Primary Action] [Secondary] [⋯ More]      [⌘K hint] │
├─────────────────────────────────────────────────────────┤
│ ③ TABBED BODY                                           │
│    Overview │ Workstreams │ Budget │ Team │ RAID │ Notes│
│    ─────────                                            │
│    (tab content — the dense part)                       │
├─────────────────────────────────────────────────────────┤
│ ④ LINKS & BACKLINKS                                     │
│    Linked records · Notes mentioning this               │
├─────────────────────────────────────────────────────────┤
│ ⑤ ACTIVITY TRAIL                                        │
│    Who changed what, when                               │
└─────────────────────────────────────────────────────────┘
```

Implemented as `templates/partials/_object_page.html`, which every entity template extends. The primary action is a **required** block — a page that cannot name one has a design problem (P1).

---

## 3. Components

### 3.1 Badges

Consistent vocabulary across every module. Pill-shaped, uppercase, letter-spaced, always with text.

| Family | Values |
|---|---|
| Status | Pipeline · Active · On Hold · Completed · Cancelled |
| Priority | High · Medium · Low |
| RAG | Green · Amber · Red |
| Boundary | Local · External:Anthropic · External:Google |
| Sync | Synced · Pending · Error · Unsynced |
| Source | Manual · Import · Smartsheet · Template · AI |

The **boundary badge** is deliberately in the same visual family as the others: it should feel like a normal property of a request, visible without hunting, on every AI action and every queue row.

### 3.2 Capacity bars

Four bands. The fourth exists because someone at 30% is a *bench* problem — actionable, and precisely the person you are looking for when staffing. Collapsing that into "green, good capacity" would hide it.

| Utilization | Band | Colour | Label |
|---|---|---|---|
| `< 60%` | Bench | `--pos-bench` blue | "Available" |
| `60–95%` | Good | `--pos-ok` green | "Good" |
| `95–110%` | Full | `--pos-warn` amber | "Full" |
| `> 110%` | Over | `--pos-danger` red | "Over" |

Every bar renders the numeral inside or beside it. Thresholds live in `app_settings.utilization_bands`.

### 3.3 Coverage bar

Staffing coverage uses a gradient from `--pos-accent` to `--pos-accent-2`, filled to `coverage%`, capped visually at 100% with overflow shown as a separate marker. Below the understaffed threshold the tile gains a dashed border and a warning label — never colour alone.

### 3.4 Project tile

```
┌────────────────────────────┐
│ [header image / fallback]  │  ← deterministic colour from project id
├────────────────────────────┤
│ Acme Corp            ●High │  ← client, priority
│ Sell Side Diligence        │  ← project name
│ [In Progress]              │  ← status badge
│ ├──────●───────┤ Mar–Aug   │  ← timeline strip, today marker
│ #FDD #Valuation #TechAcct  │  ← skill tags
│ Coverage ▓▓▓▓▓▓▓░░ 78%     │  ← gradient bar + numeral
│ (JS 50%) (KP 75%) +2       │  ← avatars with allocation
│ Burn 62% · On budget       │  ← budget chip
│ [Assign Team]              │  ← primary action
└────────────────────────────┘
```

**Header image fallback:** when `cover_image` is null, generate a deterministic gradient from `hash(project.id)` so a project without an image still looks intentional rather than broken.

### 3.5 Tables

Data-dense by default. Sortable, filterable and exportable — every table view, no exceptions (P3 depends on it).

**Paginated tables sort and filter on the server.** A client-side sort reorders
only the rendered page while appearing to have sorted everything, which on a
four-hundred-row roster is a lie the user cannot see. Mark such a table
`data-pos-server-sort` and `tables.js` will leave its rows alone.

The handles live in the header cell, as the contacts roster shows:

- **Sort** — the `<th>` holds a link setting `?sort=<key>&dir=asc|desc` and
  preserving every other parameter, with `aria-sort` on the active column.
  Each sort key is an ordering expression, a default direction and a fixed
  tie-breaker, so equal rows never swap places between pages.
- **Filter** — columns with a fixed set of values carry a `<details>` menu of
  those values with counts. A column's own filter is excluded from its own
  counts, so choosing one value still shows what else you could switch to,
  while every other menu narrows. Values come from a developer-defined dict of
  permitted columns; the request never reaches the SQL text.
- **Page size** — a selector of 25/50/100/250/500/1000, defaulting to 100 and
  clamped server-side to that set.
- **Export** — a link to a server route sharing the page's query parser, so the
  file holds every filtered row rather than the rendered page, and the label
  says which.

All of it is links and form controls: the table works with JavaScript off, needs
no inline script (the CSP forbids them), and every control is keyboard-reachable
(P10).

- Numerics right-aligned, tabular figures (`font-variant-numeric: tabular-nums`)
- Negatives in parentheses, not with a minus sign — accounting convention (P9)
- Thousands separators always; consistent decimal places within a column
- Money formatted `$1,234.56`; negatives in parentheses `($1,234.56)`. **All amounts are USD** — never render a currency code or offer a currency selector
- Sticky header on scroll; zebra striping via `--pos-surface-1`
- Row click opens the record; a distinct affordance for row actions so clicking a menu never navigates

### 3.6 Traceable numbers

Every computed figure is a `<button class="pos-trace">` rather than plain text. Clicking opens a drawer showing the rows behind it, the formula applied, and a link to the full underlying list.

```
Burn 62%  ⓘ
   ↓
┌─ How this was calculated ────────────────┐
│ Actual cost      $184,200                │
│ ÷ Budget cost    $297,000                │
│ = Burn           62.0%                   │
│                                          │
│ From 412 time entries across 3 charge    │
│ codes, priced at rates effective on each │
│ work date.            [View all entries] │
└──────────────────────────────────────────┘
```

This pattern is non-negotiable for burn, coverage, utilization, EAC, margin, variance and availability dates. It is the difference between a number you cite and a number you re-derive in Excel first.

---

## 4. Global Chrome

```
┌──────────────────────────────────────────────────────────────┐
│ ☰  Work › Projects › Acme Sell Side    [ Search…  ⌘K ]  🔔³ 👤│
└──────────────────────────────────────────────────────────────┘
```

- **Breadcrumbs** reflect the IA group → module → record path and are always clickable
- **Search** is prominent and opens the command palette; the `⌘K` hint is always visible
- **Notification bell** shows an aggregate count from live queries (overdue, cliffs, stakeholder contact due, failed syncs, failed AI jobs). Dismissal writes to `alert_dismissals` keyed by deterministic alert identity. The alerts themselves are never stored — a second copy of truth would drift from the queries that generate it.
- **Profile menu** holds theme toggle, settings, help, and the backup-age chip

---

## 5. Command Palette

`Ctrl-K` / `Cmd-K` anywhere. Roughly 200 lines of vanilla JS over a JSON index endpoint.

**Three modes, inferred from input:**

| Input | Mode |
|---|---|
| plain text | Search across projects, people, notes, tasks, charge codes |
| `>` prefix | Commands — "New task", "Import timesheet", "Sync Smartsheet" |
| `#` prefix | Jump to tag |
| `@` prefix | Jump to person |

Results are grouped by type, ranked with recent items first, and navigable entirely by keyboard. Enter opens; `Ctrl-Enter` opens in a new tab.

### Hotkey map

Documented in a `?` overlay generated from the same registry that binds them, so the two cannot drift apart.

| Key | Action |
|---|---|
| `Ctrl-K` | Command palette |
| `?` | Hotkey reference |
| `/` | Focus search on current list |
| `n` | New record in current context |
| `e` | Edit current record |
| `s` | Save (in a form) |
| `Esc` | Close drawer / cancel |
| `g` then `c` | Go to Command Center |
| `g` then `p` | Go to Projects |
| `g` then `s` | Go to Staffing Board |
| `g` then `t` | Go to Tasks |
| `g` then `n` | Go to Notes |
| `j` / `k` | Move down / up a list |
| `x` | Toggle select on a list row |
| `Enter` | Open focused row |

**No action is reachable only by mouse** (P10). Verified per-phase in the `CLAUDE.md` checklist.

---

## 6. Drag and Drop

Native HTML5 drag-and-drop. No library.

| Surface | Drag | Drop | Effect |
|---|---|---|---|
| Staffing Board | Person card | Project tile | Open Assign Team, pre-filled |
| Staffing Board | Assigned avatar | Another tile | Reallocate, with utilization preview |
| Portfolio Timeline | Milestone diamond | New date | Update `forecast_date` |
| Task board | Task card | Status column | Change status |
| Notes Vault | File | Folder | Move file, rewrite links |
| Template picker | Pack | Project | Start import wizard |

**Every drag has a keyboard and menu equivalent.** Drag-only interactions are unusable with assistive technology and awkward on a trackpad. The equivalent path is listed in the row action menu and bound in the hotkey registry.

Drop targets show a visible ring (`--pos-focus-ring`) on drag-over; invalid targets show no affordance rather than a rejection cursor. Every drop that changes data shows the standard confirmation (§8) and is undoable from the activity trail.

---

## 7. Accessibility

**No state is ever encoded by colour alone.** This is not a formality here — the application is unusually dense in red/amber/green: RAG chips, capacity bars, coverage bars, budget flags, sync status, RAID severity. That encoding is unreadable for roughly one in twelve men, and it is the most likely accessibility failure in a product like this.

Every such indicator carries **at least one non-colour channel**:

| Indicator | Colour + |
|---|---|
| RAG chip | the word "Green" / "Amber" / "Red" |
| Capacity bar | the percentage numeral and band label |
| Coverage bar | the percentage numeral |
| Understaffed tile | dashed border *and* warning text |
| Budget chip | "On budget" / "Over budget" text |
| Sync status | icon + word |
| RAID severity | numeric score |

Additional requirements:

- Contrast ≥ 4.5:1 for body text, ≥ 3:1 for large text and UI boundaries, in **both** themes
- Visible focus ring on every interactive element; never `outline: none` without a replacement
- All form inputs have associated `<label>`; icon-only buttons have `aria-label`
- Tables use `<th scope>`; sortable headers expose `aria-sort`
- Drawers and modals trap focus and restore it on close
- Live regions (`aria-live="polite"`) announce async completions such as an import finishing
- Respect `prefers-reduced-motion` — disable transitions, keep state changes instant

---

## 8. Interaction Patterns

### 8.1 The wizard pattern

Every multi-step process uses it: template import, timesheet reconciliation, Smartsheet mapping, model install, Assign Team, bulk edit.

```
┌─ Import Timesheet ─────────────── Step 2 of 4 ─┐
│ ●───────●───────○───────○                      │
│ Select  Map   Preview  Commit                  │
├────────────────────────────────────────────────┤
│                                                │
│  This will create:                             │
│    412 time entries across 3 charge codes      │
│    2 charge codes need matching  ⚠             │
│    1 person not recognised       ⚠             │
│                                                │
│  Nothing is written until you press Commit.    │
│                                                │
├────────────────────────────────────────────────┤
│              [Back]  [Commit 412 entries]      │
└────────────────────────────────────────────────┘
```

Required elements: stage indicator with position, an explicit **statement of what will be created or changed**, a dry-run preview, and warnings surfaced before rather than after. The commit button names the actual effect — never just "Finish."

### 8.2 Confirmation copy

The test: **a confirmation that could be pasted onto a different feature and still read correctly is wrong.**

| ✗ Wrong | ✓ Right |
|---|---|
| "Saved." | "Acme Sell Side updated — forecast end moved to 14 Nov. [View timeline →]" |
| "Import complete." | "Imported 412 time entries across 3 charge codes. 2 unmatched codes need review. [Reconcile →]" |
| "Assignment created." | "Kim Park assigned to Acme Sell Side at 75% through 30 Jan. Coverage now 92%. [View board →]" |
| "Sync finished." | "Pipeline sync: 47 rows read, 3 updated, 1 diverged from a local edit. [Review →]" |

Every confirmation states the specific effect and offers the next step (P2).

### 8.3 Empty states

Never a blank panel. Every empty state names what belongs there and offers the action that creates it.

```
┌────────────────────────────────────┐
│           No workstreams yet       │
│                                    │
│  Workstreams break a project into  │
│  parallel tracks, each with its    │
│  own budget, team and notes folder.│
│                                    │
│  [+ Add workstream]  [Import from  │
│                       template]    │
└────────────────────────────────────┘
```

### 8.4 Destructive actions

Archive, never delete. The confirmation names the record and what becomes of dependents, and the activity trail makes it reversible.

### 8.5 Async work

Anything over ~200ms goes async with visible progress. **No spinner without a cancel.** Long jobs (imports, syncs, AI generation, GAL chain walks) post to a queue and show live progress, so a slow operation looks like it is working rather than hung.

---

## 9. Layout & Density

- Sidebar 240px, collapsible to icon rail at 64px; state persists
- Content max-width 1600px for reading views; full-bleed for boards and timelines
- Base font 14px; 13px in dense tables; 12px for metadata
- Spacing scale 4 / 8 / 12 / 16 / 24 / 32
- Card radius 8px, border 1px `--pos-border`
- **Progressive disclosure** (P6): dense where you are working, summarised elsewhere. Detail panels open in drawers rather than navigating away, preserving context.

## 10. Print

The Portfolio Timeline and status reports must print cleanly — these get pasted into decks and emailed to partners.

- `@media print`: force light tokens, drop chrome and navigation, expand collapsed sections
- Timeline prints landscape with the visible horizon; page-break avoidance inside a project row
- Status reports print as a clean document with project identity in the header

---

## 11. JavaScript Boundaries

Vanilla only, no build step. Permitted:

- Command palette and hotkey registry
- HTML5 drag-and-drop handlers
- Debounced live preview in the markdown editor (posts to a server render endpoint — one renderer, server-side, so preview and saved output cannot diverge)
- SSE consumers for streaming AI output and job progress
- Table sort, filter and column visibility
- Theme toggle, drawer and modal control

Not permitted: client-side routing, client-side templating of business data, state management libraries, anything requiring a bundler.

Files: `static/js/palette.js`, `dnd.js`, `editor.js`, `tables.js`, `stream.js`, `app.js`. Each standalone, each loaded only where used.
