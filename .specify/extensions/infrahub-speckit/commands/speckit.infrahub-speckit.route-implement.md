---
description: "Hook command — runs before /speckit.implement in Infrahub projects. Invokes the matching infrahub-managing-* skill for each artifact type that tasks.md touches, so implementation code follows authoritative Infrahub patterns and conventions."
---

# Infrahub Routing — pre-implement hook

This command is fired as a `before_implement` hook by the `infrahub-speckit` extension. It runs every time the `speckit-implement` skill is invoked. If `.infrahub.yml` is not present, this command is a no-op.

**MANDATORY — do NOT skip, defer, or rationalize around this.**

Before any task that touches Infrahub artifacts is implemented, the corresponding Infrahub skill must be loaded. The skill loads authoritative reference material, validation rules, and implementation patterns that the code MUST follow.

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

Then return. The core implement skill runs unchanged.

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

After installing, restart this session and re-run /speckit.implement.
```

Do NOT proceed further until the skills are installed. Do NOT continue to later steps or emit any routing directive — exit the hook with the user-facing error message only.

## Step 3 — Identify artifact types touched by `tasks.md`

1. Read `tasks.md` and `plan.md` from the current feature directory.
2. Identify every artifact type any task in any phase touches:

   | Task Involves | Skill to Invoke | When to Invoke |
   |---------------|-----------------|----------------|
   | Schema YAML files (`schemas/`)          | `infrahub-managing-schemas`    | Before the first schema task |
   | Python transforms (`transforms/`)       | `infrahub-managing-transforms` | Before writing transform code |
   | Python checks                           | `infrahub-managing-checks`     | Before writing check code |
   | Generator Python files (`generators/`)  | `infrahub-managing-generators` | Before writing generator code |
   | Menu YAML files (`menus/`)              | `infrahub-managing-menus`      | Before writing menu definitions |
   | Object data files (`objects/`)          | `infrahub-managing-objects`    | Before writing seed data |

3. Build the list of skills to load — one per artifact type touched, deduplicated.

## Step 4 — Invoke each matched skill

Invoke each skill on the deduplicated list using the Skill tool, BEFORE returning. Each skill loads once per implementation session — no need to re-invoke per task within the same session.

**Anti-rationalization check** — if you think "I already loaded the skill during /speckit.specify" or "I already loaded it during /speckit.plan" or "the plan has all the details I need", invoke the skill anyway. Skill content is NOT persisted across commands; each command session starts fresh.

## Step 5 — Emit the routing record and return

Emit a single status line listing the skills loaded:

```
[infrahub-speckit routing — applies to this /speckit.implement run only]

Skills loaded: <comma-separated list>
```

Then return. The core `speckit-implement` skill runs next.
