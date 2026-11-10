---
description: "Hook command — runs after /speckit.implement in Infrahub projects. Scans the finished cycle for evidence that an Infrahub skill's guidance had a gap, and offers to draft a skill-friction report. Detection is automatic; drafting and filing are not."
---

# Infrahub Routing — post-implement friction hook

This command is fired as an `after_implement` hook by the `infrahub-speckit` extension. It runs every time the `speckit-implement` skill finishes, after its completion validation. If `.infrahub.yml` is not present, this command is a no-op.

Infrahub skills fail quietly. A missing or unclear rule does not crash the run; it produces extra round trips and repeated user nudges until the model works the answer out on its own. That friction is invisible by the time the cycle ends, which is why this hook looks for it while the session still holds the evidence.

**This hook detects. It does not draft, and it does not file.** Its entire output on the positive path is a one-line offer. Loading `infrahub-reporting-skill-gaps`, searching the tracker, and drafting anything happen only if the user accepts. Filing happens only after `infrahub-reporting-issues` takes the user through its own content-review and submission-method gates.

## Hook return semantics

Throughout this file, **"return"** means: stop emitting hook-command output and let control flow back to the calling core skill. Do NOT terminate the session or abort the parent slash command.

Unlike the `before_*` hooks in this extension, **this hook has no halt case**. It runs after implementation has already succeeded, so nothing it discovers may fail, retry, or roll back a finished run. Every path through this file ends in a return:

- emit a no-op line and return (not an Infrahub project, reporting skill absent, or no qualifying evidence), OR
- emit the Step 4 friction offer and return (positive case).

If any step of this hook errors, is ambiguous, or cannot be completed, emit a no-op line and return. A missed friction report costs nothing. A hook that disrupts a completed implementation cycle costs the user real work.

## Step 1 — Detect Infrahub project

If the repository has no `.infrahub.yml`, emit:

```
[infrahub-speckit] No .infrahub.yml detected. No friction check applied.
```

Then return.

## Step 2 — Check the reporting chain is available

The accept path is a **two-skill chain**: `infrahub-reporting-skill-gaps` is forbidden from filing and must hand its draft to `infrahub-reporting-issues`. Confirm **both** appear in your available-skills inventory.

**If either is missing**, emit this line naming the absent skill and return:

```
[infrahub-speckit] <MISSING-SKILL-NAME> not installed. Friction check skipped.
```

Check both, not just the first. Offering a report the chain cannot complete is worse than staying quiet: the user accepts, pays for a tracker search and a full draft, and then dead-ends at a handoff target that does not exist. The two skills do ship in the same package, but a manual or partial install can leave one behind, so do not infer the second from the first.

Do NOT halt. Do NOT print install guidance. Do NOT block the completed run. This differs deliberately from Step 2 of the `route-specify`, `route-plan`, and `route-implement` hooks, which halt when the mandatory `infrahub-managing-*` skills are absent. Those skills are load-bearing for the work itself, and running without them is the silent-failure mode this extension exists to close. This one is load-bearing for nothing: implementation is already done, and an absent reporting skill means only that a report cannot be offered.

## Step 3 — Evidence gate

Scan **this session only** for evidence that an Infrahub skill's guidance had a gap. This is a cheap in-session read, not an investigation.

**Do not, in this hook:** run `gh` or search any issue tracker, diff anything against git history, fetch documentation, load rule files into context in full, or draft any part of a report. All of that belongs to `infrahub-reporting-skill-gaps` and happens only after the user accepts the offer. Probe B's directory listing and topic grep below are the single exception, and are bounded to one skill's `rules/` directory.

The gate opens on **probe A or probe C** below. Probe B is not a trigger: it is the attribution read that fills the `Rule coverage:` line of the offer. `evidence-detection-ladder.md` is explicit that "probe A without probe B is incomplete. A tells you something broke; B tells you which file owns it." A topic with no matching rule file is a topic that is undocumented, which is true of plenty of topics on a perfectly healthy cycle. On its own it is not evidence that anything went wrong.

### Probe A (opens the gate) — verifier verdict

A red-to-green transition on the same target within this session: a verifier for the artifact type rejected the artifact and later accepted it. Strongest evidence there is, because no self-assessment produced it.

Use whichever verifier the artifact type actually has, as named by that artifact's own `infrahub-managing-*` skill. **This file deliberately does not enumerate the commands.** `evidence-detection-ladder.md` owns that list, and a copy here would drift from it; the copy that used to live in this table had already drifted into command names that do not exist.

Two conditions bound this probe, and **both** must hold:

1. **The skill must have been loaded before the artifact was authored.** The bound is on the authoring attempt, not on the verifier run. Within a single `/speckit.implement` only `route-implement`'s load is visible: `route-specify` and `route-plan` ran in earlier commands, and skill content does not persist across commands. So this condition holds only when the artifact was authored or edited **in this session, after the skill was loaded**. A red-to-green on an artifact authored in an earlier session says nothing about that skill's guidance, however the verifier behaved today, and a fresh session that only loads or validates pre-existing artifacts is the common shape of that case. **When the authoring is not visible in-session, the probe is not satisfied** — emit the no-op line rather than attributing the friction to a skill that never guided the work.
2. **The failure must be the artifact being rejected on its own merits.** Authentication, connectivity, a missing or unstarted container, and product-side 5xx errors do **not** open the gate. They exit to level-1 triage, per the same rule. A red-to-green on `infrahubctl schema load` because the user started their instance halfway through the cycle is the single most likely red-to-green in a dev session, and it says nothing at all about any skill's rules.

### Probe C (opens the gate) — correction delta

The user rejected or rewrote an artifact the agent authored during this cycle, and the accepted version differs in a way a rule could have prevented. The delta itself is the proposed rule change, so it must be visible in-session. Do not reconstruct it from git.

### Probe B (attribution only, never a trigger) — coverage read

Once probe A or C has opened the gate, `ls` the implicated skill's `rules/` directory **and grep it for the topic terms**, which is exactly what the ladder's probe B is: "Run `ls skills/<skill>/rules/` and grep the topic terms."

**A filename alone cannot settle this**, so do not try to answer from the listing. `relationship-identifiers.md` documents the bidirectional relationship case but never the generic-peer one; a name-only read would report it as covering a topic it does not cover, and that wrong claim is what the user sees in the offer and what seeds the eventual report. Scope the grep to that one directory, and still do not load whole rule files into context or read any other skill's rules.

The grep result sets the `Rule coverage:` value, per the ladder's own reading of probe B:

| Grep result | `Rule coverage:` value | What it means downstream |
| ----------- | ---------------------- | ------------------------ |
| A hit, and the output was still wrong | the filename | points at a bug in an existing rule |
| No hit | `no rule file covers this topic` | points at a feature or a docs gap |
| Directory could not be resolved | `unresolved` | attribution deferred to the reporting skill |

**Locate it by its invariant, not by a hard-coded path.** A skill's `rules/` directory is always a sibling of that skill's own `SKILL.md`, in every install method and under every assistant. So resolve `<root>/<skill-name>/SKILL.md` first, then read the `rules/` directory next to it.

Search these roots, project-local before global, and stop at the first hit:

| Root | Install method |
| ---- | -------------- |
| `.agents/skills/<skill>/` | `npx skills add`, assistant-neutral. The most common layout |
| `skills/<skill>/` | manual copy into the project, or a checkout of the skills repo itself |
| `.claude/skills/<skill>/` | Claude Code, project-local |
| `~/.agents/skills/<skill>/`, `~/.claude/skills/<skill>/` | the same layouts installed globally |
| `~/.claude/plugins/cache/opsmill/infrahub/<version>/skills/<skill>/` | Claude Code plugin marketplace |

**This table is a hint, not a closed set.** `npx skills add` installs for whichever assistants are present, and the skills support Claude Code, GitHub Copilot, Cursor, Windsurf, Amp, Cline, Codex and others. Each keeps context files in its own place, so a root that is not listed here is expected rather than an error. When none of the above resolve, glob for `<skill-name>/SKILL.md` beneath the project root and the user's home directory and use the `rules/` sibling of whatever it finds. Do not assume `.claude/`: this extension is driven from spec-kit, which is not Claude-specific, and an assistant-specific path is the wrong thing to hard-code in a hook that any of them can fire.

**If none of them resolve, still emit the offer** with `Rule coverage: unresolved`. Probe B is attribution, not evidence, so a failed path lookup must not suppress an offer that probe A or C already earned. `infrahub-reporting-skill-gaps` runs this read again properly as its own step 5.

### These do NOT open the gate

Not on their own, and not in combination:

- retry counts and round-trip counts
- edit churn on the same file
- the user asking the same thing more than once
- a docs escape to `docs.infrahub.app`

These are session-shape counters. They rise for reasons that have nothing to do with a skill's guidance: an unclear request, a slow instance, a user changing their mind. Per the skill's own ladder, counters open an investigation and never close one. A hook that fired on a retry count would offer a report on most cycles and train the user to ignore it.

**If no closing probe is present**, emit this line and return:

```
[infrahub-speckit] No skill-guidance friction detected this cycle.
```

This is the expected outcome for most cycles.

## Step 4 — Emit the friction offer and return

If the gate opened, emit exactly this block, then return:

```
[infrahub-speckit — friction offer, /speckit.implement]

Skill:        <IMPLICATED-SKILL-NAME>
Evidence:     <ONE-LINE-SUMMARY-OF-THE-CLOSING-PROBE>
Rule coverage: <RULE-FILENAME> | no rule file covers this topic | unresolved

An Infrahub skill's guidance may have a gap here. Reply "report it" to draft a
skill-friction report for review. Nothing is filed without your approval.
```

Substitute the placeholders with the values from Step 3. `Evidence` states what actually opened the gate, in one line, and so always describes probe A or probe C, never probe B. For example:

- `schema load rejected the file twice, passed after an identifier was set` (probe A)
- `user rewrote the generated check to query per-group rather than globally` (probe C)

`no rule covers <topic>` is a `Rule coverage` value, not an `Evidence` value. On its own it never earned the offer.

**Do NOT invoke `infrahub-reporting-skill-gaps` here.** The offer above is the trigger that skill already declares ("accepting a friction offer"), so a user reply routes into it through its own description with no further wiring from this extension. Invoking it from this hook would load its full rule set and begin the tracker search on a cycle where the user never asked for either.

Then return. `/speckit.implement` is complete, and any remaining `after_implement` hooks run next.

## What happens if the user accepts

Recorded here so the boundary is clear; none of it is this hook's work.

`infrahub-reporting-skill-gaps` runs its own detection ladder, searches `opsmill/infrahub-skills` for an existing report, triages skill defect vs. product defect, and drafts a redacted report from its template. It is explicitly forbidden from filing. It hands `{type, title, body, searched, issue?}` to `infrahub-reporting-issues`, which resolves the destination repo and owns the two remaining gates:

1. **Content review** (mandatory): target repo, title, and full body shown to the user, iterated until they approve.
2. **Submission method**: `gh` CLI, a GitHub MCP server, or manual copy-paste markdown plus the `issues/new` URL. The manual path sends nothing from this machine.

The user can stop at either gate.
