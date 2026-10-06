# Docs outline: business impact

Working file for the docs gate. Not committed.

## Kind of work

Reorganizing existing docs. The business impact content exists today, but it is spread over four pages, and the main one is written for a presenter, not for a reader.

## Repository facts (Step 0.5)

Docs in `docs/docs/`, Docusaurus, sidebar in `docs/sidebars.ts`, no redirects mechanism, default branch `main`. The Infrahub navigation map does not apply to this repo, so placement follows this repo's sidebar and the sibling demo repo `infrahub-demo-dc`.

## What exists today (Step 2)

| Page | Business impact content | Problem |
|---|---|---|
| `docs/docs/business-impact-demo.mdx` | Full run of both views and the check, labels, assumptions, claims | Presenter script: "Say this out loud", "Read it once at the start", "Claims the demo supports". Mixes three kinds of content: tutorial steps, concepts (how "affected" is decided, labels, SLA assumption, how the guard decides, how reuse is counted) and sales guidance |
| `docs/docs/getting-started/installation.mdx` Step 6 | `invoke seed` | Fits here; keep |
| `docs/docs/getting-started/user-walkthrough.mdx` Step 5 | Short run of the page and the blocked merge | Repeats the tutorial content in a second place |
| `docs/docs/getting-started/developer-walkthrough.mdx` "The business impact layer" | Schema, query, page modules, check, seed | Fits the developer guide; can link to the concept page instead of re-explaining |

## Precedent (Step 2.7)

- `infrahub-demo-dc` (`docs/sidebars.ts`): sidebar categories Getting started, Tutorials, Guides, Topics. Each use case is its own scenario tutorial (`security-management`, `virtualization`, `service-catalog`); concepts sit in one Topics page.
- Writing-infrahub-docs patterns: concept content goes on a page that answers what, why, what you need to understand, paths, next ([overview-page-content]). Tutorials only when scenario-shaped ([tutorial-shape-test]). How-to steps numbered only when they depend on each other ([steps-vs-sections]).

## Decisions for the gate

### 0. Scope

Recommended: one page set for business impact, replacing `business-impact-demo.mdx`, plus small edits to three existing pages. No other page changes.

### 1. Placement

Recommended: a new sidebar category **Business impact**, after Getting Started, with three pages under `docs/docs/business-impact/`. Existing URLs stay as they are; `business-impact-demo` was never published, so it needs no redirect.

Alternative considered: restructure the whole sidebar into Tutorials / Guides / Topics like `infrahub-demo-dc`. Rejected for now, because it moves the published walkthrough URLs and there is no redirects mechanism.

### 2. Pattern

Hub + spokes, small: one concept page that opens the category, one tutorial, one how-to.

| File | Title | Kind | Opens with |
|---|---|---|---|
| `business-impact/overview.mdx` | Business impact | Concept (hub) | The capability: each service carries a customer, a tier and a monthly charge in the same graph as its devices, so a proposed change shows which customers it affects and a check can stop it |
| `business-impact/plan-maintenance.mdx` | Plan device maintenance without breaking a Gold commitment | Tutorial | The scenario: you need to take Paris edge router 1 down for maintenance |
| `business-impact/adapt-context-reuse.mdx` | Adapt the context reuse view to your systems | How-to | What the discovery file holds and when you edit it |

### 3. Page content

**Business impact (hub, concept, about 120 lines)**

1. Capability lead (above).
2. When it matters: a change that takes a device out of service affects every service behind it. Without business context, the reviewer sees a device; with it, the reviewer sees which customers and which commitments are involved. Source: spec 004 Context and User Story 1. **Reasoned framing, for you to confirm.**
3. The data that carries business context: tiers (Gold, Silver, Bronze, with SLA credit percentage), customers, monthly charge, and that all three are demo business inputs. Source: spec FR-001 to FR-004.
4. How Infrahub decides a service is affected: any device behind its interfaces with a status other than active; interface status ignored; no second path in this demo. Source: spec Figure definitions, FR-021.
5. The two labels, Counted and Your input, and what the page does not calculate. Source: FR-030, FR-031.
6. The SLA assumption: Gold only; announced maintenance excluded from Silver and Bronze; many real SLAs exclude maintenance at every tier. Source: spec Assumptions.
7. The Gold outage guard: when it fails, warns, passes; no override. Source: FR-049 to FR-055.
8. Context reuse: what the two counts mean, that sources are illustrative, and that counts are not prices. Source: User Story 2, Figure definitions.
9. Limits: no outage cost, ROI or savings figure; no cost to deliver; no dual path, so a hidden single point of failure is not detected; no connection to CRM, billing or monitoring. Replaces "Claims the demo does not support". Source: spec Out of Scope.
10. `## In this section` catalog of the two child pages.

**Plan device maintenance without breaking a Gold commitment (tutorial, numbered steps, one running example)**

Prerequisite: installation Steps 1 to 6.

1. Open the Paris maintenance change on the Business Impact page and read the headline and tiles.
2. Find the customers and services behind the figures (chart, affected services, router ranking).
3. Compare with the Brussels change and the current network.
4. Open the same proposed change in Infrahub and read the failed Gold outage guard.
5. Try to merge and see it refused.
6. See a change that passes: New York router 1 maintenance.
7. Optional: change a device status in a proposed change and watch the page update.

Closes with what you saw and a link back to the hub. Passes the tutorial shape test: one scenario a network team recognizes (scheduled maintenance), a running example, an end state.

**Adapt the context reuse view to your systems (how-to, sections, not steps)**

- What the discovery file holds (elements, workflows, declared reads, rules).
- Map an element to a different source system, with the Device status example (25 vs 6 becomes 21 vs 5).
- Add a planned workflow.
- Add or change a business rule.
- Where the built workflows come from (stored queries in Infrahub), and that editing the file does not change them.

The parts are independent, so they are sections.

### 4. Changes to existing pages

- `installation.mdx` Step 6: keep; link to the new hub instead of `business-impact-demo`.
- `user-walkthrough.mdx` Step 5: replace with three lines and a link to the tutorial, so the run lives in one place.
- `developer-walkthrough.mdx` "The business impact layer": keep the code-level content; link to the hub for the concepts.
- `sidebars.ts`: replace `business-impact-demo` with the new category.
- Delete `business-impact-demo.mdx`.

### 5. Voice changes

- Write to the reader who runs the demo, in second person. Remove presenter cues ("Say this out loud", "Read it once", "Point at").
- Remove the "Claims the demo supports" list; its facts move to the hub (capability, limits).
- Page titles: noun phrase for the concept page, imperative for the tutorial and the how-to.
- No "economic buyer" anywhere in `docs/` (your correction, 2026-10-05).

### 6. Questions only you can answer

1. **Audience.** Recommended: the public docs address a reader who runs the demo, not a presenter. The presenter talk track, if you still want one, lives outside `docs/` (for example next to the spec). Keep it, or drop it?
2. **Context reuse in public docs.** Its figures are illustrative and the view is closer to a sales argument than the blast radius. Recommended: keep it, with the hub's limits section and the how-to. Or leave it out of the public docs?
3. **Why-layer wording.** Item 2 of the hub is reasoned from the spec, not from a messaging brief. Confirm or reword.

### 7. Pull request scope

One change set on this branch covering items 2 to 5. Deferred: the Tutorials / Guides / Topics restructure of the whole sidebar.

## Corrections ledger

- 2026-10-05: no "economic buyer" in public docs; use "business impact" or "business intent".

## Source mapping

- Spec: `specs/004-economic-buyer-slice-a/spec.md` (Context and Intent; User Stories 1 to 3; FR-001 to FR-057; Figure definitions; Assumptions; Out of Scope)
- Contracts: `specs/004-economic-buyer-slice-a/contracts/page-ui.md`, `contracts/context_reuse.schema.md`, `contracts/seed-task.md`
- Current page: `docs/docs/business-impact-demo.mdx`
- Precedent: `/Users/iddo/dev/infrahub-demo-dc/docs/sidebars.ts`
