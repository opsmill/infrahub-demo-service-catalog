# opsmill-speckit

OpsMill house [spec-kit](https://github.com/github/spec-kit) repo. Ships two
independently installable artifacts:

1. **Extension `opsmill`** — seven workflow commands under the `opsmill`
   namespace:
   - `/speckit.opsmill.auto` — run the full pipeline end-to-end (prep +
     implement) autonomously, making all decisions without pausing. Stops
     before extract.
   - `/speckit.opsmill.prep` — run the preparation phases
     (specify → plan → critique → tasks → spec/ask alignment check)
     autonomously, stopping before implementation.
   - `/speckit.opsmill.implement` — run the implementation + review tail from an
     existing `tasks.md` in clean-context subagents, then emit a final report.
   - `/speckit.opsmill.extract` — extract durable knowledge, guidelines, and
     ADRs from completed spec directories into `dev/knowledge/`,
     `dev/guidelines/`, `dev/adr/`.
   - `/speckit.opsmill.retrospect` — run a session retrospective that surfaces
     context-management gaps and routes them to `fix-now`, `open-pr`,
     `github-issue`, or `local-only` dispositions.
   - `/speckit.opsmill.summary` — produce a flow-level timeline of the current
     Claude Code session next to `spec.md` / `plan.md` in the active feature
     directory.
   - `/speckit.opsmill.qa` — produce a manual QA checklist (`qa-checklist.md`)
     next to `spec.md` / `plan.md` so a human tester can verify the
     just-implemented feature step-by-step.

2. **Presets** — drop-in overrides for spec-kit commands (native or
   extension-provided). Each preset is installed independently of the
   extension. Currently two ship:
   - [`taskstoissues-jira`](presets/taskstoissues-jira/README.md) — overrides
     `/speckit.taskstoissues` with a Jira-flavored implementation that fans
     `tasks.md` out into Jira issues under a single Epic (one issue per
     `## Phase N:` block) via the Atlassian MCP.
   - [`reconcile-opsmill`](presets/reconcile-opsmill/README.md) — overrides
     `/speckit.reconcile.run` from the
     [stn1slv/spec-kit-reconcile](https://github.com/stn1slv/spec-kit-reconcile)
     extension with an OpsMill-adapted command body: remediation tasks
     stay inside `## Phase <N>:` blocks, `[P]` keeps its core
     "parallelizable" meaning, the compliance gate reads
     `dev/guidelines/` + `dev/adr/`, and the report is
     Jira-aware. Requires the `reconcile` extension to be
     installed in the consumer repo.

## Requires

- spec-kit `>=0.8.0`
- `check-prerequisites.sh` (shipped by spec-kit core; present at
  `.specify/scripts/bash/check-prerequisites.sh` in any spec-kit-initialized
  repo). Used by the `summary` command via the `{SCRIPT}` placeholder.
- **Two companion extensions.** The `prep`, `auto`, and `implement` commands
  invoke skills provided by separate extensions:
  - [`critique`](https://github.com/arunt14/spec-kit-critique) — provides the
    `speckit-critique-run` skill used by `prep` and `auto`.
  - [`review`](https://github.com/ismaelJimenez/spec-kit-review) — provides the
    `speckit-review-run` skill used by `implement` and `auto`.

  Install both before using `prep`, `auto`, or `implement` (see below).

## Install

Latest `main`:

```bash
specify extension add opsmill \
  --from https://github.com/opsmill/opsmill-speckit/archive/refs/heads/main.zip
```

Pinned release:

```bash
specify extension add opsmill \
  --from https://github.com/opsmill/opsmill-speckit/archive/refs/tags/v1.0.0.zip
```

Local development install (from a working tree):

```bash
specify extension add --dev /path/to/opsmill-speckit
```

### Companion extensions

The `prep`, `auto`, and `implement` commands depend on two other extensions.
Install both:

```bash
# review — install from the fix branch. The upstream v1.0.1 tag fails to
# install on spec-kit 1.0.x; see Troubleshooting below.
git clone https://github.com/iddocohen/spec-kit-review -b fix/script-name-slugs
specify extension add ./spec-kit-review --dev

specify extension add critique \
  --from https://github.com/arunt14/spec-kit-critique/archive/refs/tags/v1.0.0.zip
```

Once upstream tags `v1.0.2`, the fork is no longer needed and `review` installs
the same way as `critique`:

```bash
specify extension add review \
  --from https://github.com/ismaelJimenez/spec-kit-review/archive/refs/tags/v1.0.2.zip
```

Neither is a hard dependency. `prep`, `auto`, and `implement` resolve their
quality gates at runtime and fall back to a reduced built-in critique or review
subagent when a companion extension is missing. The fallback is always reported
on the machine-readable status line (`CRITIQUE:` / `REVIEW:`) and in the run
summary, so a degraded run is never silent. Install both for the full passes.

## Commands

### `/speckit.opsmill.extract`

Analyzes one or more completed spec directories and extracts durable knowledge
into the project's documentation system (`dev/knowledge/`, `dev/guidelines/`,
`dev/adr/`), then marks each spec as extracted.

Accepts multiple specs as space-separated arguments and processes them
sequentially.

### `/speckit.opsmill.retrospect`

Runs a retrospective on the current agent session while the work is still
fresh in context. Identifies concrete improvements to the repository's
context-management surface area (`AGENTS.md`, `CLAUDE.md`,
`.claude/settings.json`, `.agents/skills/`, `.agents/commands/`,
`.specify/templates/`, `dev/knowledge/`, `dev/guides/`, `dev/guidelines/`,
`dev/adr/`) and routes them through user-approved dispositions.

Stays read-only until the user approves each disposition bucket.

### `/speckit.opsmill.summary`

Produces a flow-level summary of the current Claude Code session — executive
summary, chronological timeline, and outcomes — written into the active
feature directory next to `spec.md` / `plan.md`.

Supports `--since <commit|time>` to bound the summary window.

### `/speckit.opsmill.qa`

Produces a manual QA checklist at `FEATURE_DIR/qa-checklist.md` that walks
a human tester through verifying the just-implemented feature. Scope is
**manual / user-facing only** — exact commands, URLs, UI paths, and the
outputs to look for. Automated test suites are intentionally out of scope.

The checklist is organized into Scope, Prerequisites, Setup, Test Scenarios,
Edge Cases, Teardown, and Sign-off sections. Re-running on the same feature
prompts before overwriting; pass `--force` to skip the prompt, or any other
free-form text as scope guidance (e.g. `focus on the CLI surface`).

### `/speckit.taskstoissues` (preset override)

Provided by the [`taskstoissues-jira`](presets/taskstoissues-jira/README.md)
preset, not the extension. Install separately:

```bash
specify preset add taskstoissues-jira \
  --from https://github.com/opsmill/opsmill-speckit/archive/refs/heads/main.zip \
  --subdir presets/taskstoissues-jira
```

See [`presets/taskstoissues-jira/README.md`](presets/taskstoissues-jira/README.md)
for config (`dev/jira.yml`) and failure-mode details.

### `/speckit.reconcile.run` (preset override)

The `/speckit.reconcile.run` command comes from the
[stn1slv/spec-kit-reconcile](https://github.com/stn1slv/spec-kit-reconcile)
extension; the [`reconcile-opsmill`](presets/reconcile-opsmill/README.md)
preset overrides its body. Install the extension first (it must be
present in the consumer repo), then the preset:

```bash
specify extension add reconcile \
  --from https://github.com/stn1slv/spec-kit-reconcile/archive/886f1dd.zip

git clone https://github.com/opsmill/opsmill-speckit
specify preset add --dev opsmill-speckit/presets/reconcile-opsmill
```

See [`presets/reconcile-opsmill/README.md`](presets/reconcile-opsmill/README.md)
for provenance and behavior.

## Hooks (auto-fire during SDD)

The extension registers one opt-in hook at install time. It prompts before
running (`optional: true`):

| Event | Command | Purpose |
|---|---|---|
| `after_taskstoissues` | `/speckit.opsmill.summary` | Capture the session timeline at the moment of handoff to the issue tracker. |

`/speckit.opsmill.extract`, `/speckit.opsmill.retrospect`, and
`/speckit.opsmill.qa` are not wired by default — they remain manual commands.
Extract is intentionally manual so the user can review the implementation
report before promoting content into `dev/`.

The `extension.yml` `hooks:` schema accepts one command per event. To fire
additional commands at the same event (or to re-wire `extract` or `qa` to
fire automatically after implement if you prefer that workflow), append
entries to your repo's `.specify/extensions.yml` registry. Example: fire
`extract` and `qa` at `after_implement` on the consumer side:

```yaml
# .specify/extensions.yml (consumer-side, snippet)
hooks:
  after_implement:
    - extension: opsmill
      command: speckit.opsmill.extract
      enabled: true
      optional: true
      prompt: "Extract knowledge, guidelines, and ADRs from the completed spec?"
    - extension: opsmill
      command: speckit.opsmill.qa
      enabled: true
      optional: true
      prompt: "Create QA testing checklist?"
```

## Troubleshooting

### `Validation Error: Invalid script name 'detect-changed-files.sh'`

Installing the `review` companion extension fails on spec-kit **1.0.x**:

```
$ specify extension add review --from .../spec-kit-review/archive/refs/tags/v1.0.1.zip
Validation Error: Invalid script name 'detect-changed-files.sh': must be lowercase alphanumeric with hyphens only
```

Upstream bug in `ismaelJimenez/spec-kit-review`: its `extension.yml` puts the
file name in `provides.scripts[].name`, which spec-kit 1.0.0 began validating
against `^[a-z0-9-]+$` (the path belongs in `file:`). Validation aborts before
any command or hook is registered, so `speckit-review-run` is absent rather
than broken.

Tracked in opsmill/opsmill-speckit#16. Upstream fix:
[issue](https://github.com/ismaelJimenez/spec-kit-review/issues/4),
[PR](https://github.com/ismaelJimenez/spec-kit-review/pull/5).

Until upstream tags v1.0.2, install from the fix branch:

```bash
git clone https://github.com/iddocohen/spec-kit-review -b fix/script-name-slugs
specify extension add ./spec-kit-review --dev
```

Without it, `implement` and `auto` run their fallback reviewer and report
`REVIEW: fallback`. That is a safety net with less depth than the extension,
not an equivalent pass.

### `implement` or `auto` reports `REVIEW: none` / `CRITIQUE: none`

The companion extension is missing **and** the harness offered no subagent
dispatch, so no fallback was possible. `REVIEW: none` marks the run
`INCOMPLETE` by design. Install the companion extension and re-run the gate
over the same diff.

## Provenance

The `extract`, `retrospect`, and `summary` command bodies originated as lifts
from an internal spec-kit extensions set, with two surgical line edits to
update self-references to the namespaced form (`speckit.opsmill.<cmd>`); no
other content changes.

The `auto`, `prep`, and `implement` commands (added in 1.1.0) are authored
from scratch in this repo — they are **not** lifts. See `CHANGELOG.md`.

## License

Apache-2.0. See `LICENSE`.
