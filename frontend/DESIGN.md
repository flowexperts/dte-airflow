# Design rules

How anything user-facing in `frontend/` gets laid out. Read before changing a
layout, adding a panel, or deciding where something goes on a page.

Two halves. **Part 1** is what to do when building something new. **Part 2** is
the precedents — rules already paid for in rework, each with the specific bug
behind it named so you can check whether a new case actually rhymes rather
than applying them by vibes.

Referenced from `CLAUDE.md`. Design *tokens* and the component list live there;
this file is about placement and behaviour.

---

## Part 1 — Guidelines for new work

### Start from the question, not the data

Before adding a surface, write down the question the user arrives with. Every
panel on the page should be answering one, and you should be able to say which.
A panel that answers no question the user actually has is chrome, however
correct its contents.

Then rank the questions by how often they are asked. That ranking is the
vertical order of the page. It is not the order the data happens to arrive in,
and it is not the order the backend model declares its fields.

### The three tenses

Most product surfaces mix three kinds of information, and they do not belong
together:

| Tense | Example | Where it goes |
|---|---|---|
| **Present** — live, changes as you work | preview, active run | Beside the thing being edited |
| **Past** — consulted deliberately | run history, revisions | A tab or its own view, full width |
| **Definitional** — the spec itself | sources, steps, schedule | The main column, ordered by causality |

Mixing tenses in one column is the most common way a page becomes hard to
read. When in doubt, ask "would someone look at these two things in the same
moment?" If no, they do not go next to each other.

### Budget the first screenful

Whatever is visible without scrolling is the page's real answer. Decide
explicitly what earns that space. Everything else is below the fold or behind
a disclosure — and a disclosure is a promise that the content is genuinely
rare, not a place to put things you couldn't rank.

### Count the clicks *and* the distance

Two separate costs, both real:

- **Clicks** — how many actions to complete the task.
- **Distance** — how far the eye and the pointer travel, and how much scroll.

A change that removes a click but doubles the scroll distance is usually a
loss. Measure both before claiming an improvement.

### Design for the pathological size, not the demo size

Ask what the page does at 300 steps, 10,000 runs, 50 sources. Layouts that
only work at demo size fail silently: nothing errors, the page just becomes
unusable. Specifically:

- Anything anchored to document end becomes unreachable → make it
  viewport-anchored or a tab.
- Unbounded lists need paging with a **total**, so the user knows the scale.
- Always-expanded editors need a collapse threshold and virtualization.
- Scroll stops being navigation → provide search, an outline, or deep links.

### Make state addressable

If a user can be looking at two different things at the same URL, they cannot
share, bookmark, or link to what they see, and Back does the wrong thing. Tabs,
filters, and selected items belong in the query string. Use
`history.replaceState` for client-side view switches; reserve `router.replace`
for changes that must re-run the server component.

### Every affordance is visible, and every link goes somewhere

No hover-only primary controls. No breadcrumb crumbs without an href. No
disabled buttons whose enabling condition isn't stated somewhere on screen.

### Feedback beats validation

When an input encodes behaviour — a cron string, an expression, a glob —
render what it *means* as the user types, next to it. Server-side validation
tells you an input is legal; it cannot tell you it is wrong. Never silently
rewrite what the user typed.

### Say why, not just what

Empty states, errors, and hidden controls should name the reason in terms of
the data. "Never run. Trigger it from the header" beats "No results". "Preview
compiles the saved pipeline" beats hiding the preview with no explanation.

### Reuse the rendering path

If the same object appears in two places, render it with the same components.
A step that reads one way in the editor and another way in history is two
sources of truth about the same thing, and they will drift.

### Comment the placement decision, not the markup

When a layout choice is deliberate — a container query threshold, a sticky
offset, an order that looks arbitrary — put the reasoning in a comment at the
site. `sticky top-[52px]` means nothing without "the Topbar is 52px".

---

## Part 2 — Precedents

These were paid for in rework. Each one has a specific bug behind it — the
precedent is named so you can check whether a new case actually rhymes.

**1. Order by causality, not by convenience.** The pipeline spec column reads
Pipeline → Sources → Destination → Inputs → Schedule → Steps. Inputs sit above
Schedule because a schedule supplies one value per declared input; you cannot
schedule what you have not declared. When two panels have a real dependency,
the dependency reads first.

**2. Endpoints before body.** Source and destination are the contract — read
together, changed together — so they go above the steps. The destination used
to sit *below* the steps, which meant scrolling the entire body to answer
"where does this land?"

**3. Never anchor anything to the end of an unbounded document.** Runs and
History used to be a section below the canvas. With every step editor open, a
300-step pipeline is ~120,000px tall and that section is effectively deleted.
Anything that must stay reachable is either a page-level tab, sticky to the
viewport, or both. The tab strip is `sticky top-[52px]` under the 52px
`Topbar` for exactly this reason.

**4. Tabs are for alternatives, not for stages.** Runs and History share a tab
strip because they are the same subject on the same time axis — you consult
one *or* the other. Preview does not join them: it is present tense, re-runs
as you type, and belongs beside the editor in the rail. Tabbing it with them
would imply you swap between them in the same moment, which is not how any of
the three get used. `Tabs` vs `Segmented`: Tabs pick *which thing*, Segmented
picks a *mode* for one thing (Basic vs Advanced filter editing).

**5. Put the glanceable signal on the control, not on a second surface.** The
Runs tab carries last-run health as its badge, so the Spec view answers "is
this healthy?" with no click and no separate header strip. One element, two
jobs, beats two elements.

**6. Defaults should open on the readable form.** Filter and check editors
parse their SQL on mount and open in Basic whenever it round-trips; Advanced
is reserved for expressions the rules UI genuinely cannot represent.
Previously `step.expr ? "advanced" : "basic"` meant every *saved* filter
opened as raw SQL and the rules builder was only ever seen on a new step.

**7. A text field that encodes behaviour needs a live readback.** Cron is the
case: `0 5 * * *` and `0 * 5 * *` differ by one character and by 24× in run
frequency, and both pass server validation. `CronExplainer` renders plain
English *plus* the next three fire times, because the sentence is the part
the user already believed — the times are what catch the mistake. Show the
readback, never silently rewrite the input.

**8. Link to the thing that produced the artifact, not to its current
version.** A run records `revision_id`; its links open
`/pipelines/{id}/revisions/{revId}`, not the live pipeline. Once anyone edits,
the live pipeline is precisely the spec that did *not* produce that run. The
revision view reuses the same canvas so a step cannot read one way live and
another way in history.

**9. Breadcrumbs walk real containment, and every crumb is a link.** The run
page said `Workspace / Runs / 8e1a4a91` — a dead label, and the pipeline (the
only thing a run belongs to) was missing. Now
`Workspace / Pipelines / <name> / Runs / <id>`, with Runs → `?tab=runs`. If a
crumb has no destination, the trail is wrong.

**10. Tab and view state belongs in the URL.** `?tab=runs|history` (Spec drops
the param), written with `history.replaceState`, not `router.replace` — a
client-side view switch should not re-run the server component. This is what
makes a crumb able to link to a tab, and makes Back behave.

**11. Show scale, not just a way forward.** Pagination is numbered ("1–20 of
1,284"), not "Load more". The count tells you whether to dig at all; an append
button lets you click forever without learning how far you are from the end.
`Pagination` renders nothing when everything fits on one page, so short lists
carry no chrome.

**12. Creation lives next to the list it adds to.** "+ New pipeline" was
removed from the sidebar, where it read as a third *kind* of pipeline beside
Transform and Quality Check. `NewResourceButton` on `/pipelines` is the one
entry point — and it renders while permissions are in flight, because gating
on `can()` alone hides the primary action on first paint and permanently if
`/api/auth/me` fails.

**13. A control that only exists on hover does not exist.** The add-step
control was `text-transparent group-hover:text-accent`; the step-type menu was
unreachable. Primary affordances are always visible.

**14. Size editors to the width they actually get, with `@container`.** Step
editors get ~534px in the builder and ~536px in the canvas at 1440 — the
layout was never the problem. `FilterEditor`'s rules row wants ~620px and its
fixed grid crushed the value input to ~119px; `InputsPanel`'s 6-column grid
wanted ~820px, got 567px, and silently overflowed a `Panel` that is
`overflow-hidden` — clipped, no scrollbar. Editor breakpoints are **container**
queries, never viewport: the width depends on which layout hosts the editor.

**15. Remove controls cost no layout row.** The inputs `×` took a full 30px
grid row and left an empty band above the first field. It is
`absolute right-2 top-2` while stacked and `@[720px]:static @[720px]:order-last`
once the row unstacks. Same principle for any per-row affordance.

**16. Don't wrap a component that already brings its own chrome.** `InputsPanel`
renders its own `Panel` + `PanelHead`; wrapping it produced two nested INPUTS
headers. Check before adding a `Panel`.

**17. Read-only means read-only, and say why.** The revision canvas drops
Save, Trigger, the tabs, the preview rail, and the Schedule panel. Preview
compiles the *saved* pipeline and schedules are not versioned, so either one
beside a historical spec would report something that spec never did. When you
hide something in a restricted mode, the reason should be a property of the
data, not a shrug.

**18. Deep links must reach the specific thing.** `/runs/{id}` links to
`/pipelines/{id}#step-N`; `StepsColumn` reads `location.hash` on mount and on
`hashchange`. At 300 steps this stops being a convenience and becomes the only
way to reach a failing step.

---

## Checklist for a new surface

Run through this before opening a PR that adds or reorders a page.

- [ ] Every panel answers a question the user actually arrives with.
- [ ] Vertical order matches question frequency, and dependencies read first.
- [ ] Present / past / definitional information is not mixed in one column.
- [ ] The first screenful earns its space; nothing important is only reachable
      by scrolling past unbounded content.
- [ ] Works at 100× the demo size — or the degradation is deliberate and noted.
- [ ] Lists are paged and report a total.
- [ ] View state that can differ at the same URL is in the query string.
- [ ] Every control is visible without hover; every crumb and link resolves.
- [ ] Behaviour-encoding inputs render a live readback.
- [ ] Empty and restricted states name the reason in terms of the data.
- [ ] Editor widths use `@container`, sized to the width the host actually gives.
- [ ] The same object renders through the same components everywhere.
- [ ] Non-obvious placement decisions carry a comment with the reasoning.
