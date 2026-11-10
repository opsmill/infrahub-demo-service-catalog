---
description: "Hook command — runs before /speckit.specify in Infrahub projects. Detects .infrahub.yml, classifies artifact type, gates skill invocation, and emits the template-override directive that the core specify skill consumes."
---

# Infrahub Routing — pre-specify hook

This command is fired as a `before_specify` hook by the `infrahub-speckit` extension. It runs every time the `speckit-specify` skill is invoked — whether by `/speckit.specify`, by `opsmill-speckit/prep`, or by any other harness. If `.infrahub.yml` is not present in the repository root, this command is a no-op (exit cleanly without emitting any directives).

The core `speckit-specify` skill body runs after this hook returns. Anything you write to the hook's output that the agent treats as part of its context will be applied when the skill reaches the matching step.

## Hook return semantics

Throughout this file, **"return"** means: stop emitting hook-command output and let control flow back to the calling core skill. Do NOT terminate the session, abort the parent slash command, or skip the core skill body. The spec-kit hook contract requires this hook to either:

- emit a no-routing line and return (no-op case), OR
- emit the Step 8 directive block and return (routing case), OR
- emit a user-facing error message and halt the entire command sequence (preflight failure case — the calling skill should NOT proceed in this case).

The third case is the only one where the calling skill should not resume.

## Step 1 — Detect Infrahub project

Check if `.infrahub.yml` exists in the repository root.

- **If it does NOT exist**: Skip the rest of this command. Emit a single line of output:

  ```
  [infrahub-speckit] No .infrahub.yml detected. No routing applied.
  ```

  Then return. The core specify skill continues unchanged.

- **If it exists**: Continue to Step 2.

## Step 2 — Verify required Infrahub skills are installed

This extension MANDATES invoking the `infrahub-managing-*` skills during specification. Before continuing, confirm these skills appear in your available-skills inventory:

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

After installing, restart this session and re-run /speckit.specify.
```

Do NOT proceed further until the skills are installed. The "MUST invoke" rules in Step 5 are meaningless without them. Returning from this hook with skills missing means the core specify skill will run without the Infrahub skill context — that's the silent-failure mode v2.0.0 closed and we are not reopening it. Do NOT continue to later steps or emit any routing directive — exit the hook with the user-facing error message only.

## Step 3 — Verify Infrahub connectivity

Run `infrahubctl info` to verify that the Infrahub instance is reachable.

- **If the command fails or Infrahub is not reachable**, stop and warn the user:
  ```
  Infrahub is not reachable. Please start your Infrahub instance first:
    invoke start
  Then re-run /speckit.specify
  ```
  Do NOT proceed further. Do NOT continue to later steps or emit any routing directive — exit the hook with the user-facing error message only.
- **If it succeeds**: Continue to Step 4.

## Step 4 — Classify artifact types from the user's input

The user's original input to `/speckit.specify` is available as `$ARGUMENTS` (the same string passed to the core skill). Match it case-insensitively against this table. A prompt can match multiple rows.

| Artifact Type | Keywords / Signals | Extension Template |
|---------------|-------------------|-------------------|
| **Schema**    | schema, data model, nodes, attributes, relationships, hierarchy, generics, namespace, kind, store information, model | `spec-schema-template` |
| **Transform** | transform, render, config, artifact, output, template, jinja, generate config, device config, configuration | `spec-transform-template` |
| **Check**     | check, validate, validation, enforce, rule, constraint, verify | `spec-check-template` |
| **Generator** | generator, auto-create, design-driven, topology, provision, generate objects | `spec-generator-template` |
| **Menu**      | menu, navigation, sidebar, UI, organize | `spec-menu-template` |

If nothing matches, default to `spec-schema-template` (schema-first principle — everything downstream depends on the data model).

## Step 5 — Handle single vs. multiple artifact types

**Single match** — proceed with that template.

**Multiple matches** — present the dependency chain to the user and start with the first:

```markdown
## Infrahub Artifact Routing

Your feature involves multiple Infrahub artifact types:

1. **Schema** — Define the data model (must be done first)
2. **<Second artifact>** — depends on schema

The spec-driven workflow handles one artifact type per cycle:
`/speckit.specify` → `/speckit.plan` → `/speckit.tasks` → `/speckit.implement`

**Starting with: Schema**
After completing this cycle, run `/speckit.specify` again for the next artifact.
```

Dependency order (earlier must complete first):

1. Schema (always first — everything depends on the data model)
2. Check, Generator, Transform, Menu (all depend on schema; independent of each other)

## Step 6 — Invoke the corresponding Infrahub skill

**MANDATORY — do NOT skip, defer, or rationalize around this.** (Availability was already verified in Step 2.)

Invoke the skill using the Skill tool BEFORE returning. The skill provides curated reference material (schema properties, validation rules, naming conventions, API patterns) that the spec MUST be consistent with. Skill content is NOT persisted across commands, so it MUST be re-loaded here even if the same skill was loaded earlier in the session.

| Artifact Type | Skill to Invoke | What It Provides |
|---------------|-----------------|------------------|
| **Schema**    | `infrahub-managing-schemas`    | Schema property reference, node/generic definitions, attribute kinds, relationship types, CoreFileObject, naming conventions, validation rules |
| **Transform** | `infrahub-managing-transforms` | Transform types (Python/Jinja2), query patterns, artifact definitions, content types |
| **Check**     | `infrahub-managing-checks`     | Check definition structure, validation logic patterns, proposed change pipeline |
| **Generator** | `infrahub-managing-generators` | Generator class patterns, target groups, query parameters, idempotent creation |
| **Menu**      | `infrahub-managing-menus`      | Menu structure, node organization, sidebar customization |

For multi-artifact prompts, invoke the skill for the FIRST artifact type in the dependency chain (the one being specified in this cycle).

**Anti-rationalization check** — if any of these thoughts appear, invoke the skill anyway:
- "I already know Infrahub schemas" — the skill has validated reference material that's not in training data
- "I fetched the docs via WebFetch" — web docs can be incomplete or outdated
- "This is a simple change" — simple changes still need correct attribute kinds, cardinalities, and naming
- "I'll invoke it later during planning" — the spec fixes entities and requirements NOW

## Step 7 — Resolve the template path

Resolve the template path for the selected artifact type:

1. Prefer `.specify/extensions/infrahub/templates/<template-name>.md` (e.g. `spec-schema-template.md`). Note: these templates are shipped by the separate optional `infrahub` spec-kit extension (not by `infrahub-speckit`).
2. If that file does not exist, fall back to `.specify/templates/spec-template.md`. Emit a warning that the Infrahub extension templates are missing.

## Step 8 — Emit the routing directive and return

Emit the following directive verbatim as the final output of this hook. The core `speckit-specify` skill reads the hook output as part of its context before entering its Outline phase, and the agent must honor this directive when reaching the template-loading step in the skill body:

```
[infrahub-speckit routing — applies to this /speckit.specify run only]

Artifact type: <SELECTED-ARTIFACT-TYPE>
Skill loaded: <SKILL-NAME>
Template override: When the core specify skill references `.specify/templates/spec-template.md` or "spec-template", use the template at <RESOLVED-TEMPLATE-PATH> instead. All other behavior of the core skill (feature directory, branch hook ordering, quality checklist, after_specify hooks) is unchanged.
```

Substitute the bracketed placeholders with the actual values from Steps 4–7. Then return — the core `speckit-specify` skill body runs next.

If multiple artifact types were detected in Step 5, also remind the user at the end of the spec cycle to re-run `/speckit.specify` for the next artifact in the chain. (This reminder lives in the hook output; the core skill will surface it when reporting completion.)
