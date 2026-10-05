---
description: Run the speckit implementation phase chunk-by-chunk in clean-context subagents, then review, then produce a final report. Picks up from an existing tasks.md.
---

## User Input

```text
$ARGUMENTS
```

You **MUST** consider the user input before proceeding (if not empty). `$ARGUMENTS` is optional and may name the spec directory to operate on (e.g. `specs/008-foo`). If empty, operate on the most recently modified spec directory under `specs/` that has a `tasks.md`.

## Outline

You are running the **implementation + review tail** of the speckit pipeline. This command picks up where `speckit-opsmill-prep` leaves off: it expects a feature directory under `specs/` containing `spec.md`, `plan.md`, and `tasks.md`. It does **not** generate or modify those documents — it executes them.

The implementation phase runs as a **loop** over chunks of `tasks.md`, with each chunk implemented inside a **clean-context subagent**. The orchestrator (you) never edits feature code directly — it dispatches, integrates, and reports.

After all chunks are complete, you run a single review pass across the whole change set, fix any high-severity findings, and emit a final report.

> Each phase below is executed by invoking the named skill (e.g. via the agent's Skill tool). Skills are agent-agnostic, so this workflow runs identically across any harness that supports skill discovery — not only those exposing speckit slash commands.

### Phase 0 — Preflight

**Invocation context.** This command runs in one of two modes, and the stop-conditions below behave differently in each:

- **Interactive** (a user invoked it directly). On a stop-condition you may pause and ask the user, as written.
- **Autonomous parent** (invoked as Phase B of `speckit-opsmill-auto`). There is no user to resume a pause, so you **MUST NOT** pause or wait. Treat every stop-condition below as a hard abort: do **not** start the implement loop, and end your run with the `STATUS: BLOCKED` status line defined in **Completion** so the parent orchestrator can detect it and stop cleanly. Never proceed on a dirty tree or missing docs — doing so contaminates the `HEAD@start..HEAD@now` review diff. You can tell you are running under an autonomous parent because you were dispatched with a resolved spec-dir path and no interactive session.

Before any work begins:

1. Resolve the target spec directory (from `$ARGUMENTS` or the most recently modified `specs/<feature>/` with a `tasks.md`). Record the absolute path; you will pass this to every subagent.
2. Verify `spec.md`, `plan.md`, and `tasks.md` all exist. If any are missing: interactive → abort with a clear error directing the user to run `speckit.opsmill.prep` first; autonomous parent → abort with `STATUS: BLOCKED` (reason: missing prep artifacts).
3. Read `tasks.md` end-to-end and identify the chunking boundaries (see "Chunking strategy" below). Build a numbered list of chunks with their task IDs.
4. Verify the working tree is clean (or only contains expected prep artifacts). If it is dirty in unrelated ways: interactive → surface that and pause; autonomous parent → abort with `STATUS: BLOCKED` (reason: unexpectedly dirty working tree). Do not attempt to stash or clean it yourself.
5. Note the current `HEAD` commit — you will diff against it for the review and report.
6. **Resolve the review provider.** Decide how Phase 6 will review the change set and record the answer as `REVIEW_MODE`. Run this check from the repository root and read `REVIEW_MODE` off its output — do not decide from memory:

   ```bash
   if [ -d .specify/extensions/review ] || grep -q '"review"' .specify/extensions/.registry 2>/dev/null; then
     echo "review extension: installed"
   else
     echo "review extension: missing"
   fi
   ```

   | Check output | `REVIEW_MODE` |
   |--------------|---------------|
   | `installed` | `extension` |
   | `missing`, and you can dispatch clean-context subagents | `fallback` |
   | `missing`, and no subagent dispatch is available | `none` |

   Both signals are written by `specify extension add` itself: `.specify/extensions/review/` is the unpacked extension, and `.specify/extensions/.registry` is the installer's record of what registered successfully. Neither is harness-specific, and neither exists when the install aborts on manifest validation (see Troubleshooting in the README), which is the case this step exists to catch. Do **not** key the decision off `.claude/skills/speckit-review-run/` — that path only exists under Claude Code. Do not ask yourself whether you "have" the skill either: agents cannot reliably enumerate their own skills, and quietly improvising around a skill that was never installed is the exact failure this step prevents.

   A missing reviewer is **not** a stop-condition, in either invocation mode. The Phase 0 aborts above exist because a dirty tree or missing prep artifacts contaminate the `HEAD@start..HEAD@now` diff; a missing reviewer does not corrupt anything, it only lowers assurance, and Phase 6 has a defined fallback for it. Carry `REVIEW_MODE` forward to Phase 6, Phase 7 §5, and the status line.

### Phase 5 — Implement (looped, clean-context subagents)

> **Phase numbering.** This file is the implementation tail; phases jump 0 → 5 → 6 → 7 on purpose. Phases 1–4 (Specify → Plan → Critique → Tasks) run in `speckit-opsmill-prep`. They are not missing or skipped here.

Loop over the chunks identified in Phase 0. For **each chunk**:

1. **Dispatch a subagent with a clean context.** Use your harness's subagent / Task tool (in Claude Code: the `Agent` tool with `subagent_type=general-purpose`). The subagent **must not** inherit the orchestrator's conversation history — every chunk starts fresh.

2. **Brief the subagent self-contained.** The orchestrator has read context the subagent does not. The prompt to the subagent must include:
   - Absolute path to the spec directory.
   - Absolute path to the repository root.
   - Pointers to project context files the subagent should read first, when present at the repo root or in their conventional locations: `AGENTS.md`, `CLAUDE.md`, `CONTEXT.md`, and the project constitution (commonly `.specify/memory/constitution.md`, `dev/constitution.md`, or `constitution.md`). The orchestrator should resolve which of these actually exist before dispatch and pass the resolved absolute paths — do not ask the subagent to guess. If none exist, say so explicitly so the subagent does not waste a turn searching.
   - The **exact chunk** of tasks to implement, copied verbatim from `tasks.md` (task IDs, descriptions, and any `[P]` parallel markers).
   - An explicit instruction to invoke the `speckit-implement` skill scoped to **only those task IDs** — not the full `tasks.md`.
   - The commit policy: the subagent should run formatters/linters and commit its own work via the `speckit-checkpoint-commit` skill before returning.
   - **The local-pass policy.** Every test the chunk adds or modifies — unit, integration, **and E2E when the project supports running them locally** — MUST be observed to PASS locally at least once before the chunk is reported as done. Marker-clean / lint-clean / type-clean is NOT a substitute. If a test class cannot be executed locally in this project (e.g. an E2E suite that requires infrastructure the developer machine cannot provide), the subagent MUST state that explicitly and explain why, rather than silently skipping. For every test that was run, the subagent MUST return the evidence specified in the response contract below; if it cannot produce the evidence for a test it claims to have written, the chunk's outcome line for that task MUST be `⚠️ partial` or `❌ blocked` (not ✅ done) with the reason.
   - **Discovering how tests run.** Before executing tests, the subagent should determine the project's test conventions by reading `AGENTS.md` / `CLAUDE.md`, then the repo's standard locations (`Makefile`, `package.json` scripts, `pyproject.toml`, `Cargo.toml`, `go.mod`, CI config, `tasks.md` itself). Use whatever runner the project actually uses — `pytest`, `go test`, `cargo test`, `npm test`, `vitest`, `make test`, etc. Do not assume a specific framework.
   - A short response contract: return (a) a one-line outcome per task ID (✅ done / ⚠️ partial / ❌ blocked + reason), (b) the commit SHA(s) it produced, (c) any decisions worth flagging upward, (d) overall lint/format status, (e) **for every new or modified test: the test identifier (node ID, function name, or file::test as the runner reports it), the exact command used to run it, an ISO 8601 wall-clock timestamp of the passing run, any environment context that matters for reproducibility (e.g. cluster id + kubeconfig path, container/compose service, browser version, DB fixture name) — or `n/a` if the runner needs none — and the verbatim pass line from the runner's output (e.g. `PASSED ...`, `ok`, `--- PASS:`, `✓ ...`)**. If the chunk added or modified no tests, the subagent MUST say so explicitly so the orchestrator can record "n/a" rather than an omission. If an E2E test was added but not run locally because the project does not support local E2E execution, the subagent MUST state that as a separate line and include any CI-side runbook / command that will exercise it instead.
   - Length cap on the report (e.g. "under 250 words", excluding the test evidence block which has no cap) so the orchestrator's context does not balloon.

3. **Wait for the subagent to return**, then:
   - Pull its outcome lines into your running ledger of chunk results.
   - Verify `tasks.md` checkboxes for that chunk are now `[X]` (re-read the file). If the subagent forgot to tick them, do it yourself and add a **fresh fixup commit** — do **not** `--amend` the subagent's commit. Its SHA is already recorded in the Phase 7 chunk ledger (§2) and may be referenced elsewhere; amending would rewrite it and make the final report cite a commit that no longer exists.
   - If the subagent reports ❌ blocked: do not auto-retry blindly. Decide between (i) re-dispatching with sharper instructions, (ii) splitting the chunk smaller and retrying, or (iii) recording the block and moving on. State which you chose and why.
   - Do **not** invoke `speckit-checkpoint-commit` again here — the subagent already committed. Only commit yourself if you applied a fixup (e.g. ticking missed checkboxes).

4. Move to the next chunk. **Never run two implementation subagents in parallel** — chunks may share files and conflicting writes are far more expensive than the wall-clock savings.

#### Chunking strategy

Prefer the natural phase headings already present in `tasks.md` (`### Phase 3.1: Setup`, `### Phase 3.2: Tests First (TDD)`, `### Phase 3.3: Core Implementation`, etc.). Each phase becomes one chunk.

If a phase contains more than ~10 tasks or touches > ~15 files, split it further along cohesive seams (e.g. one chunk per module, one chunk per contract test). If two adjacent small phases together total < ~5 tasks, do **not** merge them — keep the boundary; small chunks help review and reduce blast radius if a subagent goes off the rails.

Respect explicit dependencies in `tasks.md`. Sequential `[P]`-free tasks must stay in their original order across chunks; `[P]` markers within a chunk are fine for the subagent to parallelise internally.

### Phase 6 — Review

Once **all** chunks have completed (including any retries), review the full diff (`HEAD`-at-start..`HEAD`-now). How you *produce* the findings depends on the `REVIEW_MODE` resolved in Phase 0. What you *do* with them does not.

**6a — `REVIEW_MODE: extension`.** Invoke the `speckit-review-run` skill once across the full diff.

If that invocation fails — the skill is not found, or it errors out without returning findings — the extension is present on disk but not usable (files unpacked, command never registered). Do **not** continue as though the review happened. Downgrade to `REVIEW_MODE: fallback` and run 6b, or to `REVIEW_MODE: none` if no subagent dispatch is available, then record the downgrade and its cause in Phase 7 §5 and §6. The Phase 0 value is a starting point, not a commitment: the mode you report is the mode that actually ran.

**6b — `REVIEW_MODE: fallback`.** No usable review extension, so run the review yourself. Dispatch **one** clean-context review subagent using the same briefing protocol as Phase 5 (self-contained prompt, no inherited history, resolved absolute paths). Brief it with:

- Absolute paths to the repository root and the spec directory.
- The diff range (`HEAD`-at-start..`HEAD`-now), and the project context files resolved by the same rule as Phase 5 (`AGENTS.md`, `CLAUDE.md`, `CONTEXT.md`, the constitution). Pass the paths that actually exist; say so explicitly if none do.
- `spec.md` and `tasks.md`, as the statement of intent the diff is reviewed against.
- Instructions to cover these six aspects and nothing else: **code quality** (project guideline compliance, bugs, security), **comments** (accuracy, documentation completeness, comment rot), **tests** (behavioural coverage, critical gaps, test resilience), **error handling** (silent failures, catch blocks, error logging), **type design** (encapsulation, invariants, enforcement), **simplification** (clarity, unnecessary complexity, redundant abstractions).
- The required return shape: a severity-rated finding list (`high` / `medium` / `low`), each finding carrying file, line where known, and a one-line summary. **Findings only** — the subagent must not fix anything, so that the fix decisions below stay with the orchestrator.

This is a safety net, not a replacement. It will not match the extension's depth, and the report must say so rather than present it as an equivalent pass.

**6c — `REVIEW_MODE: none`.** No review is possible. Proceed to Phase 7 with an empty finding list and carry `REVIEW_MODE: none` forward. Do **not** continue as though the change set had been reviewed, and do **not** substitute a quick unstructured read of the diff for a review and report it as one.

**Finding handling is identical in 6a and 6b:**

- For findings rated **high severity or above**, fix them inline. Prefer fixing them yourself if the change is small and localised; dispatch a fresh clean-context subagent (same protocol as Phase 5) if the fix spans multiple files or needs significant code understanding.
- For lower-severity findings, record them in the report (do not block).
- Commit any review-driven fixes via `speckit-checkpoint-commit`.

### Phase 7 — Final Report

Write a markdown report to `<spec-dir>/opsmill-implement-report.md` and also print it to the user. The report **must** contain:

1. **Header** — feature name, spec dir, base commit, head commit, total wall-clock time if known.
2. **Chunk-by-chunk ledger** — for each chunk dispatched, in order:
   - Chunk name (phase heading from `tasks.md`).
   - Number of tasks in the chunk.
   - Outcome counts (✅ / ⚠️ / ❌).
   - Commit SHA(s) produced by the subagent.
   - Any decisions or surprises the subagent flagged upward.
3. **Tasks not completed** — task IDs still `[ ]` in `tasks.md`, with the reason from the relevant subagent's report. Empty section if everything is `[X]`.
4. **Local-pass evidence (REQUIRED).** A table of every test added or modified by this run — unit, integration, and E2E — with one row per test:

   | Test id | Type (unit/integration/e2e) | Run command | Passed at (ISO 8601) | Environment context | Verbatim pass line |
   |---------|-----------------------------|-------------|----------------------|---------------------|--------------------|

   Aggregate the rows from each chunk subagent's response. If a chunk added/modified a test but did not return evidence, the row's "Passed at" cell MUST be `MISSING — see chunk <N>` and the test MUST also appear in §3 "Tasks not completed" as a blocker — never silently elide it.

   If an E2E test was added but not executable locally in this project, record it as a separate row with `Passed at` = `deferred — local E2E not supported` and put the CI-side command in `Run command`. Call this out in §6 "Autonomous decisions" so the user can confirm the call.

   If no tests were added or modified by the whole run, write `n/a — no new or modified tests in this implementation` instead of the table and state it explicitly so reviewers can verify the claim against the diff.
5. **Review findings** — MUST open with a `Review mode:` line, before the table, stating how the findings were produced:

   - `Review mode: extension (speckit-review-run)`
   - `Review mode: fallback (built-in reviewer, reduced depth — install the review extension for a full pass)`
   - `Review mode: none — NO REVIEW WAS PERFORMED`

   In `fallback` and `none` mode, follow that line with the install hint: `specify extension add review` (see the repository README if the install itself fails).

   Then the table of severity / file / one-line summary, marking which findings were fixed inline and which were deferred. In `none` mode write `n/a — no review performed` in place of the table.
6. **Autonomous decisions** — any judgment calls the orchestrator made that the user might want to revisit (chunk splits, blocked-task handling, review-finding triage choices). A `REVIEW_MODE` other than `extension` MUST appear here, with the reason the extension was unavailable.
7. **Suggested next steps** — e.g. "open a PR", "rerun `speckit.opsmill.implement` to retry the 2 blocked tasks", "address the deferred review findings".

**Blocking rule.** If §4 contains any `MISSING` row, the report header MUST mark the run `INCOMPLETE` and §7 MUST list "produce local-pass evidence for the listed tests" as the first next step. Do not declare the spec done while local-pass evidence is missing. (`deferred — local E2E not supported` rows do NOT trigger this rule, but they MUST be flagged in §6.)

**Review blocking rule.** If `REVIEW_MODE` is `none`, the report header MUST mark the run `INCOMPLETE` and §7 MUST list "install the review extension and re-run the review over this diff" as the first next step. `REVIEW_MODE: fallback` does **not** trigger this rule, because a review did happen, but it MUST be flagged in §5 and §6.

`REVIEW: none` blocks where `CRITIQUE: none` in `speckit-opsmill-prep` does not, on purpose: an un-critiqued spec is still read by a human before any code exists, so the gap is visible and cheap to close, whereas an unreviewed diff is already-written code that nothing downstream re-checks. See the Completion section of `speckit-opsmill-prep` for the full rationale.

Commit the report via `speckit-checkpoint-commit` as the final action.

## Completion

Print a 4-6 line summary mirroring the report header + outcome counts so the user does not need to open the file to know the result.

**Machine-readable status line (REQUIRED).** The **final line** of your output MUST be exactly:

`STATUS: <DONE|INCOMPLETE|BLOCKED> | SPEC_DIR: <absolute spec-dir path> | REVIEW: <extension|fallback|none|n/a> | REASON: <short reason or n/a>`

- `STATUS: DONE` — all chunks completed and §4 local-pass evidence has no `MISSING` rows.
- `STATUS: INCOMPLETE` — the run finished but the report is marked `INCOMPLETE` (e.g. missing local-pass evidence, blocked tasks recorded, or `REVIEW: none`).
- `STATUS: BLOCKED` — a Phase 0 stop-condition aborted the run before the implement loop (missing prep artifacts, unexpectedly dirty tree). In this case no report is written; emit only the summary explaining why, then this line.
- `REVIEW` mirrors the `REVIEW_MODE` resolved in Phase 0, so the parent never has to infer review coverage from prose. `REVIEW: fallback` is compatible with `STATUS: DONE`. `REVIEW: none` forces `STATUS: INCOMPLETE` per the review blocking rule. Use `REVIEW: n/a` only when the run aborted before Phase 0 resolved a provider.

The parent `speckit-opsmill-auto` parses this line; keep it as the literal last line, unwrapped.

Then stop — do **not** open a PR, do **not** push, do **not** start a new feature. The user will take it from there.
