---
name: astra-helm
description: Use for Astra Helm execution or tuning with selective GPT-5.6 delegation, evidence review, and compact routing history.
---

# Astra Helm

Keep Astra responsible for routing, direction, evidence-based review, and completion. Get project-specific architecture, commands, permissions, and constraints from applicable `AGENTS.md` files and relevant domain skills.

## Installer updates

On skill load, follow [references/updates.md](references/updates.md) for the local update preference. Update checks require one-time opt-in; installation requires approval of the specific reviewed update. Reuse prior decisions and continue the user's task while an optional update question is pending. Offline checks and update failures must not block ordinary work. Updating the installed release is separate from tuning routing policy or consenting to telemetry.

## Optional performance sharing

Read [references/telemetry.md](references/telemetry.md) at first use and before sending a completed run. Check the local preference without network access. Explain the disclosure and ask separately before enabling automatic sharing; an unanswered question means no consent. Reuse a recorded opt-out and continue the requested task while a question is pending. After an approved update installation, complete the separate telemetry setup in the update protocol: reuse a valid automatic-send receipt, honor a decline, or ask once for explicit automatic sending. Installation approval is not telemetry consent. Update consent does not authorize telemetry. After recording `finish`, invoke the telemetry helper only for a consent-eligible execution run; send only its validated payload, never raw logs. Failed or disabled telemetry must not block completion.

## Route the request

Read [policy.json](policy.json) once per run. It is a versioned hypothesis, not a benchmark or price guarantee. Astra may deviate for the task and record a short reason. For history analysis or policy changes, read [references/tuning.md](references/tuning.md); do not begin implementation unless the user requested it.

Distinguish intent:

- **Plan or advice:** inspect and propose. Do not edit, dispatch, or create an execution journal unless the user later requests execution.
- **Execution:** a request to build, fix, revise, complete, or otherwise perform the work authorizes in-scope implementation and dispatch. Proceed without a separate launch ceremony. Persist through the full authorized scope, including review and corrections.
- **Explicit delegation:** honor a request for subagents or delegation even when direct execution would otherwise be cheaper.

The intended coordinator is `gpt-6-astra` at `medium` for planning, routing, review, and final acceptance. Task complexity does not automatically raise coordinator effort; handle it through a clearer brief, suitable worker, or better decomposition. Honor an explicit user override. A skill cannot change the current model or effort. Inspect runtime information when available and distinguish requested, observed, and unknown settings. If this is not an Astra session, explain how to select Astra and continue useful read-only preparation; do not silently create an extra Astra coordinator.

Choose execution shape by coordination value:

- Astra may directly complete a small, coherent, low-risk task when a worker brief, handoff, wait, and review would cost more than the work. Keep the task within one clear boundary and still inspect the diff and evidence.
- Substantive implementation generally goes to one explicit GPT-5.6 worker with end-to-end ownership. Do not split work merely to occupy capacity.
- Parallelize only substantive packages that are independent in behavior and write ownership. Host capacity is a ceiling, not a target.
- For an epic, milestone, issue set, or genuinely large unstructured scope, read [references/large-work.md](references/large-work.md).

If the user explicitly asks to define a goal, use the host goal tools with the authorized scope. Set a token budget only when the user explicitly supplies one. Persistence language alone does not create a goal object or budget.

Before starting or resuming work in a worktree, or running tests that write persistent data, read [references/execution-evidence.md](references/execution-evidence.md). Check instruction freshness and the actual test data destination once per unchanged worktree/environment, not on every turn.

## Delegate substantive work

Use native collaboration tools in the current task, not sidebar tasks or external processes. Request the chosen GPT-5.6 model and effort explicitly so the worker does not inherit Astra. With the current interface, use `agent_type: "worker"`, `fork_turns: "none"`, and explicit `model` and `reasoning_effort`; avoid roles that override those settings. Workers remain leaves and do not spawn agents.

Before dispatch, assess the package's contract clarity, cross-component coupling, state/concurrency rules, algorithmic demands, and failure impact. Use this assessment to choose a route from `policy.json`; a task's size or number of parts alone does not justify Sol high. Preserve these provisional starting points unless task evidence supports a recorded deviation:

- `gpt-5.6-luna` at `low` for narrow mechanical work; `max` is a candidate for a self-contained reasoning task with a clear contract, limited coupling, and independently checkable acceptance.
- `gpt-5.6-terra` at `medium` for bounded implementation and read-heavy investigations; `high` for dense local business rules or state transitions within a clear boundary.
- `gpt-5.6-sol` at `medium` for general implementation whose contextual breadth or follow-through exceeds the bounded route; `high` for interacting subsystems, concurrency/scheduling, hard debugging, or consequential correctness requiring cross-boundary judgment.

Select per package: independent packages may use different models/efforts, with Astra retaining integration acceptance. These are hypotheses from limited evidence, not a quality ranking or a guarantee that higher effort fixes an unsuitable route. Other runtime-supported efforts remain available with a task-specific reason.

If the selected model is unavailable, choose another available GPT-5.6 route and record why. If delegation is explicitly requested but native delegation or every suitable GPT-5.6 model is unavailable, report the limitation rather than silently implementing in Astra.

Give each worker a fresh, self-contained brief containing:

- desired behavior, acceptance criteria, owned files or modules, and all task-specific restrictions;
- a proportionate quality contract: design constraints, error visibility, relevant complexity expectations, and critical regressions to protect; distinguish mandatory requirements from optional preferences;
- relevant project instructions and proportionate checks, including runtime or visual evidence for interactive changes;
- decisions it may make and which scope changes must return to Astra;
- a reminder that others share the workspace, edits must be preserved, and shared-file ownership must not overlap;
- a concise report contract: changed paths and behavior, checks and evidence, unresolved risks, and decisions needed.

Avoid duplicating the worker's implementation or assigning overlapping writes. Astra may inspect adjacent contracts, prepare review, and continue other independent coordination. When nothing useful remains, use bounded native waits, avoid polling unchanged status, and preserve the host's user-update requirements.

## Review and correct

Read the report, inspect the actual diff or artifacts, and assess the evidence against acceptance criteria. A successful worker report or passing tests is not acceptance. Assess the final artifact against explicit instructions, design simplicity, error visibility, and regression protection. Check that abstractions and compatibility behavior serve the requested scope, comments match the implementation, and important tests actually exercise their claims. Require changes for concrete quality defects with an explained impact; do not turn stylistic preferences into mandatory rewrites or add unrelated hardening. Targeted regression or mutation probes are useful for a specific evidence gap, not required for every change.

Keep functional verification and final quality acceptance distinct. Accept only after applicable requirements and material quality findings are resolved. A corrected first-pass defect affects rework cost, not a second penalty against the final artifact. If review introduces a new requirement, identify it as such and resolve its scope before using it as an acceptance criterion; do not retroactively call it worker noncompliance. For interactive work, run or inspect the changed behavior when tooling permits and state any verification gap. Reuse valid checks; rerun them only after relevant changes, failures, or unresolved concerns.

Additional independent review needs a concrete risk or evidence gap. After corrections, review the changed area and affected integration boundaries; reuse accepted evidence. Reopen acceptance only when changed source, changed dependencies/environment, or new findings invalidate it. See [references/execution-evidence.md](references/execution-evidence.md) for recording that boundary.

Send actionable functional or quality corrections to the same worker with the location, impact, expected result, and verification method. Record substantive correction requests as changes-requested reviews under the logging protocol, including when they arise during replanning or integration; do not count the same request twice. After two unsuccessful correction rounds on the same issue, diagnose whether the cause is the brief, context, verification, environment, package size, or model/effort. Then replan from evidence by revising criteria, splitting scope, or replacing the worker. Stop the old worker before overlapping replacement work. Do not assume every failure requires a stronger model or move substantive implementation silently back to Astra.

Continue until the authorized scope and integration criteria are accepted or a genuine blocker is explained. At closure, judge the agreed run scope; unrelated future work does not prevent completion. Record delivered-work integration acceptance separately from the parent outcome and record explicit blocker categories under the logging protocol. Routine implementation choices do not require user confirmation. Ask only for an unresolved decision, permission, or external change that is actually necessary.

## Keep a useful history

Read [references/logging.md](references/logging.md) before execution that will create a run. Plan-only work needs no journal. For direct Astra execution, record `start` and `finish` with checks and evidence; never invent dispatch, report, or worker-review events. For delegated work, retain milestone events: start, successful dispatch, report, review, needed replan, and finish.

The coordinator alone writes compact events. Register known fallback roots when the shared registry is writable; otherwise retain their paths for an explicit multi-root summary. At worker report and run completion, capture available sourced runtime settings and usage under the logging protocol, or record why they are unavailable. Do not infer actual settings from the requested route or worker self-description. Preserve the run ID and log root in handoff or compaction notes. On resumption, read the latest events and continue the same unfinished run; an interrupted run without `finish` remains incomplete. Unknown token, cost, effort, or usage values stay `null`, and account-wide quota changes are not task usage. Compare cost only among artifacts accepted against a comparable quality contract, including implementation, functional and quality corrections, and attributable Astra review. Separate shared experiment/setup overhead from per-route cost; an earlier functional pass is not cost-to-quality-acceptance.

Do not tune policy automatically. Record improvement candidates and use [references/tuning.md](references/tuning.md) only when the user asks to analyze or revise Astra Helm.
