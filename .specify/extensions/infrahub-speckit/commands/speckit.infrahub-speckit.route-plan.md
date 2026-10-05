---
description: "Hook command — runs before /speckit.plan in Infrahub projects. Invokes the matching infrahub-managing-* skill so Phase 0 research and data-model design are grounded in authoritative Infrahub reference material."
---

# Infrahub Routing — pre-plan hook

This command is fired as a `before_plan` hook by the `infrahub-speckit` extension. It runs every time the `speckit-plan` skill is invoked. If `.infrahub.yml` is not present, this command is a no-op.

**MANDATORY — do NOT skip, defer, or rationalize around this.**

Before the core `speckit-plan` skill generates any design artifacts (`research.md`, `data-model.md`, `contracts/`), the matching Infrahub skill must be loaded. The skill loads authoritative reference material that design decisions MUST be consistent with. Skill content is NOT persisted across commands; each command starts fresh, so the skill MUST be re-loaded here even if it was loaded during `/speckit.specify`.

## Hook return semantics

Throughout this file, **"return"** means: stop emitting hook-command output and let control flow back to the calling core skill. Do NOT terminate the session, abort the parent slash command, or skip the core skill body. The spec-kit hook contract requires this hook to either:

- emit a no-routing line and return (no-op case), OR
- emit the Step 5 directive block and return (routing case), OR
- emit a user-facing error message and halt the entire command sequence (preflight failure case — the calling skill should NOT proceed in this case).

The third case is the only one where the calling skill should not resume.

## Step 1 — Detect Infrahub project

If the repository has no `.infrahub.yml`, emit:

```
[infrahub-speckit] No .infrahub.yml detected. No routing applied.
```

Then return. The core plan skill runs unchanged.

## Step 2 — Verify required Infrahub skills are installed

Confirm these skills appear in your available-skills inventory:

- `infrahub-managing-schemas`
- `infrahub-managing-transforms`
- `infrahub-managing-checks`
- `infrahub-managing-generators`
- `infrahub-managing-menus`
- `infrahub-managing-objects`

**If ANY are missing**, halt and tell the user:

```
The infrahub-speckit extension requires the opsmill/infrahub Claude Code skills.

Install (recommended):
  npx skills add opsmill/infrahub-skills

Or via the Claude Code plugin marketplace:
  /plugin marketplace add opsmill/claude-marketplace
  /plugin install infrahub@opsmill

Docs: https://docs.infrahub.app/skills/installation-setup

After installing, restart this session and re-run /speckit.plan.
```

Do NOT proceed further until the skills are installed. Do NOT continue to later steps or emit any routing directive — exit the hook with the user-facing error message only.

## Step 3 — Classify the artifact type from `spec.md`

1. Read `spec.md` from the current feature directory (resolve via `.specify/feature.json` or by inspecting the current working branch, however the core skill resolves it).
2. Classify the Infrahub artifact type from the spec content:

   | Artifact Type | Signals in Spec | Skill to Invoke |
   |---------------|-----------------|-----------------|
   | **Schema**    | schema, data model, nodes, attributes, relationships, generics, namespace, kind, CoreFileObject, inherit_from | `infrahub-managing-schemas` |
   | **Transform** | transform, render, config, artifact, jinja, device config | `infrahub-managing-transforms` |
   | **Check**     | check, validate, validation, enforce, rule, constraint | `infrahub-managing-checks` |
   | **Generator** | generator, auto-create, design-driven, topology, provision | `infrahub-managing-generators` |
   | **Menu**      | menu, navigation, sidebar, UI | `infrahub-managing-menus` |

3. If the spec involves multiple artifact types, invoke the skill for the PRIMARY type (the one being designed in this cycle).

## Step 4 — Invoke the matched skill

Invoke the matched skill using the Skill tool BEFORE returning. Use the skill's reference material when:

- Writing `data-model.md` (entity definitions, attribute kinds, relationship types)
- Making research decisions (SDK patterns, API conventions, naming rules)
- Validating the design against Infrahub capabilities

**Anti-rationalization check** — if you think "I already researched this via WebFetch" or "I know Infrahub well enough" or "the spec already has everything I need", invoke the skill anyway. The skill has curated reference material that general knowledge and web fetches do not provide.

## Step 5 — Emit the routing record and return

Emit a single status line:

```
[infrahub-speckit routing — applies to this /speckit.plan run only]

Skill loaded: <SKILL-NAME>
```

Then return. The core `speckit-plan` skill runs next.
