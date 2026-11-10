# Infrahub Workflow Routing Extension

Hooks the core `/speckit.specify`, `/speckit.plan`, and `/speckit.implement` commands with Infrahub-aware artifact routing and mandatory skill invocation when `.infrahub.yml` is detected in the repository. Also checks each finished implementation cycle for gaps in the Infrahub skills' own guidance.

## What it does

The `infrahub-speckit` extension registers three `before_*` hooks and one `after_*` hook against the core speckit skills. All four fire whether the skill was invoked by the slash command, by another skill (e.g. `opsmill-speckit/auto`), or by an autonomous agent.

The **three `before_*` hooks** fire *before* the skill body runs, and each one:

- detects `.infrahub.yml` (no-op if absent),
- verifies the `infrahub-managing-*` Claude Code skills are installed, halting with install guidance if they are not,
- gates on Infrahub connectivity via `infrahubctl info` (for `before_specify` only),
- classifies the requested artifact type (schema / transform / check / generator / menu),
- invokes the matching `infrahub-managing-*` skill,
- (for `before_specify`) emits a template-override directive so the core specify skill writes from the Infrahub spec template.

The hook returns; the core skill runs.

The **one `after_*` hook** is different in kind, and none of the bullets above apply to it. It fires at the other end of the cycle, *after* `/speckit.implement` has finished, and it never halts, never gates on connectivity, and never invokes an `infrahub-managing-*` skill. It checks whether an Infrahub skill's guidance had a gap during the work and offers to report it. Detection is automatic. Drafting and filing are not (see [`after_implement` hook](#after_implement-hook) below).

### Why "extension" not "preset" (v3.0 vs v2.x)

v2.x was a `wrap` preset — it composed at the slash-command layer by substituting `{CORE_TEMPLATE}` at install time. That worked when the user typed `/speckit.specify`, but was bypassed when another skill (such as `opsmill-speckit/auto`'s `prep` step) invoked the `speckit-specify` skill directly. The hook model in v3.0 composes at the skill-runtime layer instead: the core skill's `## Pre-Execution Checks` block reads `.specify/extensions.yml` and fires the registered hook regardless of how the skill was entered.

### `before_specify` hook

1. Checks for `.infrahub.yml` — no-op if absent.
2. Verifies the six `infrahub-managing-*` skills are installed.
3. Gates on Infrahub connectivity via `infrahubctl info`.
4. Classifies the user prompt into artifact types.
5. For multi-artifact prompts, presents the dependency chain and starts with Schema.
6. Invokes the matching `infrahub-managing-*` skill.
7. Emits a template-override directive ("use `.specify/extensions/infrahub/templates/spec-schema-template.md` instead of the core template") that the core specify skill applies when reaching its template-loading step.

### `before_plan` hook

Re-invokes the artifact-matched skill before Phase 0 research begins, then returns.

### `before_implement` hook

Identifies every artifact type touched by `tasks.md`, invokes each matching skill once per session, then returns.

### `after_implement` hook

Infrahub skills fail quietly. A missing or unclear rule does not crash the run; it produces extra round trips and repeated nudges until the model works the answer out anyway. By the time a cycle ends, that friction is invisible. This hook looks for it while the session still holds the evidence.

It runs automatically after every `/speckit.implement`, and does a cheap in-session scan only:

1. Checks for `.infrahub.yml` (no-op if absent).
2. Checks whether **both** `infrahub-reporting-skill-gaps` and `infrahub-reporting-issues` are installed. The accept path is a two-skill chain (the first is forbidden from filing and hands off to the second), so offering a report the chain cannot complete would waste a tracker search and a full draft on a dead end. If either is absent it skips quietly. It does **not** halt, unlike the three `before_*` hooks: implementation is already done, and nothing this hook finds may fail or roll back a finished run.
3. Applies an evidence gate, which opens on either of two probes: a **verifier verdict** (a verifier rejected an artifact and later accepted it, red to green on the same target) or a **correction delta** (you rewrote something the agent authored, in a way a rule could have prevented).
4. If the gate opened, lists and greps the implicated skill's `rules/` directory to name the file that should have covered it, then prints a one-line offer and stops. The grep matters: a filename alone cannot establish whether a rule covers a topic, so a name-only read would put a wrong claim in front of you.

That coverage read resolves the skill's location by its invariant rather than a fixed path: `rules/` always sits beside the skill's own `SKILL.md`. It searches `.agents/skills/` (the assistant-neutral layout `npx skills add` uses, and the most common one), a plain `skills/` directory, `.claude/skills/`, their global equivalents, and the Claude Code plugin cache, then falls back to globbing for `<skill>/SKILL.md`. No assistant-specific path is hard-coded, since spec-kit is not Claude-specific and any assistant can fire this hook. If the lookup finds nothing the offer is still printed, with `Rule coverage: unresolved`.

The **coverage read in step 4 is attribution, not a trigger.** A topic with no matching rule file is simply an undocumented topic, true of plenty of topics on a healthy cycle, so on its own it never earns an offer. `evidence-detection-ladder.md` puts it as "probe A without probe B is incomplete. A tells you something broke; B tells you which file owns it."

Three further exclusions keep the gate honest:

- **The skill must have guided the authoring, not just been loaded at some point.** The bound is on when the artifact was written, so a red-to-green on something authored in an earlier session does not qualify, however the verifier behaved today. Only `route-implement`'s load is visible inside a single implement run, since skill content does not persist across commands. If the hook cannot see the authoring in-session, it stays quiet.
- **Not every failure is a skill gap.** Authentication, connectivity, an unstarted container, and product-side 5xx errors do not open it. A red-to-green on `infrahubctl schema load` because you started your instance mid-cycle is the most likely red-to-green in a dev session and says nothing about any skill's rules.
- **Session-shape counters never open it.** Retry counts, edit churn, repeated asks, and docs escapes rise for reasons unrelated to a skill's guidance, such as an unclear request or a user changing their mind. A hook that fired on a retry count would offer a report on most cycles and train you to ignore it.

Most cycles end at step 3 with a single no-op line.

The hook does **not** carry its own list of verifier commands. `evidence-detection-ladder.md` in the `infrahub-reporting-skill-gaps` skill owns that list, and the hook defers to it rather than keeping a copy that drifts.

**Detection is automatic; drafting and filing are not.** The hook never invokes the reporting skill itself. The offer it prints is the trigger `infrahub-reporting-skill-gaps` already declares, so replying to it routes into that skill with no further wiring. Only then does anything expensive happen: the tracker search against `opsmill/infrahub-skills`, triage of skill defect vs. product defect, and a redacted draft. That skill is forbidden from filing. It hands the draft to `infrahub-reporting-issues`, which owns the last two gates:

| Gate | What you see | Can you stop here? |
|------|--------------|--------------------|
| Content review (mandatory) | Target repo, final title, full body, and whether it is a new issue or a comment on an existing one | Yes |
| Submission method | `gh` CLI, a GitHub MCP server, or manual copy-paste markdown plus the `issues/new` URL | Yes |

Nothing is submitted without passing both. The manual path sends nothing from your machine.

**To make it opt-in instead**, set `optional: true` on the hook's entry in `.specify/extensions.yml`. You will then be offered the friction *check* rather than having it run, and the `prompt` already shipped in the entry is used verbatim. **To turn it off**, set `enabled: false` on the same entry.

## Dependency chain

When a feature spans multiple artifact types:

```
Schema → [Check / Generator / Transform / Menu]
```

Schema is always first — everything else depends on the data model being loaded.

## Requires

- **`spec-kit >= 0.8.0`** — for the hook execution contract (extensions register `before_*` and `after_*` hooks read from `.specify/extensions.yml`)
- **`opsmill/infrahub` Claude Code skills** (REQUIRED) — provides the `infrahub-managing-schemas`, `infrahub-managing-transforms`, `infrahub-managing-checks`, `infrahub-managing-generators`, `infrahub-managing-menus`, and `infrahub-managing-objects` skills. Each hook command halts with install guidance if the skills are not present.
- **`infrahub-reporting-skill-gaps` + `infrahub-reporting-issues` skills** (OPTIONAL) — ship in the same `opsmill/infrahub` skills package as the `infrahub-managing-*` skills, so installing that package covers them. Only the `after_implement` friction hook uses them, and it skips quietly when they are absent rather than halting.
- **`infrahub` spec-kit extension** (OPTIONAL) — provides the Infrahub-specific spec templates (`spec-schema-template`, `spec-transform-template`, `spec-check-template`, `spec-generator-template`, `spec-menu-template`). If absent, the specify command falls back to the core `spec-template.md` and warns.
- **`infrahubctl` CLI** — for the connectivity check against a running Infrahub instance.

## Installation

Install the spec-kit extension directly from this repository (latest `main`):

```bash
specify extension add infrahub-speckit --from https://github.com/opsmill/infrahub-speckit/archive/refs/heads/main.zip
```

Pin to a released version for stability:

```bash
specify extension add infrahub-speckit --from https://github.com/opsmill/infrahub-speckit/archive/refs/tags/v3.0.0.zip
```

Or, once it's published to the public spec-kit catalog:

```bash
specify extension add infrahub-speckit
```

Install the Infrahub skills (required — these provide the `infrahub-managing-*` skills the hooks invoke):

```bash
npx skills add opsmill/infrahub-skills
```

Or via the Claude Code plugin marketplace:

```
/plugin marketplace add opsmill/claude-marketplace
/plugin install infrahub@opsmill
```

Skills documentation: https://docs.infrahub.app/skills/installation-setup

Optionally install the spec-kit `infrahub` extension once it's in the public catalog — this is the package that ships the Infrahub-specific spec templates (`spec-schema-template`, etc.) referenced in the route-specify hook's template-override directive:

```bash
specify extension add infrahub
```

### Upgrading from v2.x

v2.x installed via `specify preset add infrahub` and overrode `/speckit.specify`, `/speckit.plan`, and `/speckit.implement` via wrap composition. v3.0 installs via `specify extension add infrahub-speckit` and instead registers `before_*` hooks. Upgrade path:

```bash
specify preset remove infrahub
specify extension add infrahub-speckit --from https://github.com/opsmill/infrahub-speckit/archive/refs/tags/v3.0.0.zip
```

After upgrading, your `.specify/extensions.yml` will gain three new `before_*` hook entries and one `after_implement` entry under `hooks:`. The slash commands themselves are no longer customized — they run the core skill, which then fires the hook.

### Coexistence with the standalone `infrahub` extension

There is a separate, narrowly-scoped `infrahub` extension (id: `infrahub`) that validates Jira/JPD ticket references on feature branch creation. It also hooks `before_specify`. Both extensions can be installed in the same project and will coexist — `specify extension add` appends hook entries in install order. We recommend installing the JPD validator first (it owns branch creation; no point routing artifacts for a feature branch you can't create), then this extension:

```bash
specify extension add infrahub                                        # JPD/Jira branch validator
specify extension add infrahub-speckit --from <infrahub-speckit URL>  # artifact routing
```

The `before_specify` event will then fire in that order at runtime.

`after_implement` is a busier event: the `git`, `review`, and `opsmill` extensions commonly register there too, for auto-commit, PR review, and knowledge extraction. Those are all `optional: true`, so they announce themselves and wait. This extension's friction hook is `optional: false` and runs, but its own evidence gate keeps it to one line on cycles with nothing to report, so it does not add to the pile-up in practice. If it still does for you, the two escape hatches in the [`after_implement` hook](#after_implement-hook) section apply.

## Usage

### Quick start

From a fresh directory:

```bash
# 1. Initialize a spec-kit project with Claude integration
specify init --here --integration claude

# 2. Install this extension (direct from repo — catalog publishing is pending)
specify extension add infrahub-speckit --from https://github.com/opsmill/infrahub-speckit/archive/refs/heads/main.zip

# 3. Install the required Infrahub skills
npx skills add opsmill/infrahub-skills

# 4. Mark the project as an Infrahub project
cat > .infrahub.yml <<'YAML'
---
schemas: []
jinja2_transforms: []
artifact_definitions: []
queries: []
YAML

# 5. Start your Infrahub instance (so the connectivity gate passes)
invoke start   # or however you start your local Infrahub

# 6. Drive the workflow from Claude Code
```

Then from Claude Code:

```
/speckit.specify Create a schema for Devices, Interfaces, and VLANs with a transform that renders interface config
/speckit.plan
/speckit.tasks
/speckit.implement
```

### What each command does (concretely)

**`/speckit.specify <prompt>`**

The core `speckit-specify` skill fires the `before_specify` hook from this extension before its body runs. The hook:

1. Verifies `.infrahub.yml` exists (else returns; core specify runs unchanged).
2. Verifies the six `infrahub-managing-*` skills are installed (else halts with install guidance).
3. Runs `infrahubctl info` (else halts with "start your Infrahub instance").
4. Matches your prompt against artifact-type keywords — `schema`, `transform`, `check`, `generator`, `menu`.
5. If multiple types match, presents the dependency chain and starts with Schema:
   ```
   Your feature involves multiple Infrahub artifact types:
     1. Schema — Define the data model (must be done first)
     2. Transform — depends on schema

   Starting with: Schema
   After completing this cycle, run /speckit.specify again for the next artifact.
   ```
6. Invokes the matching Infrahub skill (e.g. `infrahub-managing-schemas`) — pulls in curated attribute-kind, relationship-kind, cardinality, and naming-convention reference material that the spec must be consistent with.
7. Selects the Infrahub-specific template (`spec-schema-template`, `spec-transform-template`, etc.) from the `infrahub` spec-kit extension if installed, or falls back to the core `spec-template` with a warning.
8. Emits a template-override directive and returns. The core `speckit-specify` skill body runs next — it picks up the directive and writes `spec.md` from the Infrahub-specific template, then creates the feature directory, produces the quality checklist, and fires `after_specify` hooks.

**`/speckit.plan`**

Re-invokes the artifact-matched skill before Phase 0 research begins, then runs the core planning workflow (produces `plan.md`, `research.md`, `data-model.md`, `contracts/`, `quickstart.md`). The skill's reference material feeds directly into the data model and contract decisions.

**`/speckit.implement`**

Re-invokes the relevant skill before the first task of each artifact type in each phase — `infrahub-managing-schemas` before schema YAML tasks, `infrahub-managing-transforms` before transform tasks, and so on. Each command invocation starts fresh so skills must be re-invoked per command, not just per feature.

When implementation completes, the `after_implement` hook fires and checks the cycle for skill-guidance friction. On most cycles this is a single line:

```
[infrahub-speckit] No skill-guidance friction detected this cycle.
```

When it does find something, you get an offer and nothing else:

```
[infrahub-speckit — friction offer, /speckit.implement]

Skill:        infrahub-managing-schemas
Evidence:     schema load failed on relationship cardinality, passed after correction
Rule coverage: no rule file covers this topic

An Infrahub skill's guidance may have a gap here. Reply "report it" to draft a
skill-friction report for review. Nothing is filed without your approval.
```

Ignoring it costs nothing. Replying hands the session to `infrahub-reporting-skill-gaps`, which drafts a redacted report and passes it to `infrahub-reporting-issues` for the content-review and submission gates.

### Multi-artifact features: the chain

A single feature request that touches multiple artifact types (like the quick-start example: "schema + transform") is split into separate `/speckit.specify` → `/speckit.plan` → `/speckit.tasks` → `/speckit.implement` cycles, one per artifact, in dependency order.

```
Cycle 1 (Schema):    /speckit.specify Schema for Devices, Interfaces, VLANs
                     /speckit.plan
                     /speckit.tasks
                     /speckit.implement
                     → produces schemas/network.yml

Cycle 2 (Transform): /speckit.specify Render interface config from the schema
                     /speckit.plan
                     /speckit.tasks
                     /speckit.implement
                     → produces templates/interface_config.j2 + queries/interface_config.gql
```

Schema is always cycle 1 because checks, generators, transforms, and menus all depend on the data model being loaded first.

### What ends up in the repository

After a full schema + transform cycle:

```
.infrahub.yml                           # referenced schema + transform + query + artifact_def
schemas/
  network.yml                           # DcimDevice, DcimInterface, IpamVlan
queries/
  interface_config.gql                  # GraphQL query for the transform
templates/
  interface_config.j2                   # Jinja2 rendering the device config
specs/
  001-network-schema/
    spec.md, plan.md, research.md, data-model.md, tasks.md,
    checklists/requirements.md, contracts/
  002-interface-config-transform/
    (same set)
```

## Troubleshooting

**"The infrahub-speckit extension requires the opsmill/infrahub Claude Code skills"** — the preflight check in Step 2 of the hook is telling you the `infrahub-managing-*` skills aren't installed. Run `npx skills add opsmill/infrahub-skills`, restart the session, and retry.

**"Infrahub is not reachable. Please start your Infrahub instance first"** — the `infrahubctl info` connectivity gate in Step 3 of `before_specify` failed. Start your local Infrahub and retry.

**Spec falls back to the core `spec-template.md` and warns** — the separate optional `infrahub` spec-kit extension (the one that ships templates) isn't installed. The fallback produces a valid spec; the only thing you lose is the Infrahub-specific section scaffolding. Install the templates extension if and when available.

**I don't want the friction check running after every implement** — set `optional: true` on the `after_implement` entry for this extension in `.specify/extensions.yml` and you will be offered the check instead of having it run. Set `enabled: false` on the same entry to disable it outright. Both are per-project.

**The friction hook offered a report and I don't want to file anything** — ignore it. The offer is the hook's entire output; it does not invoke the reporting skill or search any tracker on its own. Even if you do accept, `infrahub-reporting-skill-gaps` cannot file: it hands a draft to `infrahub-reporting-issues`, which stops at a mandatory content review and then asks how you want to submit. Choosing the manual method sends nothing from your machine.

**The friction hook never offers anything** — expected on most cycles. The gate opens only on a verifier red-to-green on the same target, or an in-session correction to an agent-authored artifact. A missing rule file on its own does not qualify (it is the attribution read, not the trigger), and neither do retry counts, edit churn, or failures caused by auth, connectivity, or an unstarted container. If you believe a real gap went unreported, invoke `infrahub-reporting-skill-gaps` directly.

**`specify extension list` doesn't show `infrahub-speckit` after install** — confirm the install command succeeded and that `.specify/extensions/infrahub-speckit/extension.yml` exists in the target project. If it does, also confirm `.specify/extensions.yml` has four new entries under `hooks.before_specify`, `hooks.before_plan`, `hooks.before_implement`, and `hooks.after_implement` referencing this extension. Note: in spec-kit 0.8.x the top-level `installed:` list in `extensions.yml` may stay empty even on a healthy install — the install registry moved to `.specify/extensions/.registry`, which is what `specify extension list` reads. The presence of the `hooks.*` entries is the canonical signal. If those entries are missing, re-run `specify extension add` — install was incomplete.

**Skills exist but the agent didn't invoke them** — the hook command instructs the agent to invoke the skills as a hard requirement, but agents with weak instruction-following may skip. Look for the "anti-rationalization check" in the route-* command files and paste it verbatim to the agent if it tries to proceed without invoking.

**Two `before_specify` hooks fire and only one is wanted** — the standalone `infrahub` (JPD validator) extension and this `infrahub-speckit` extension both hook `before_specify`. This is intentional (see the Coexistence section). If you only want one, remove the other with `specify extension remove <id>`.
