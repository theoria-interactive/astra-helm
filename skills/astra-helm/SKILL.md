---
name: astra-helm
description: Use for Astra Helm execution or tuning with selective GPT-5.6 delegation, evidence review, and compact routing history.
---

# Astra Helm

Keep Astra responsible for routing, direction, evidence-based review, and completion. Get project-specific architecture, commands, permissions, and constraints from applicable `AGENTS.md` files and relevant domain skills.

## Installer updates

On skill load, follow [references/updates.md](references/updates.md) for the local update preference. Update checks require one-time opt-in; installation requires approval of the specific reviewed update. Reuse prior decisions and continue the user's task while an optional update question is pending. Offline checks and update failures must not block ordinary work. Updating the installed release is separate from tuning routing policy or consenting to telemetry.

## Explicitly requested performance sharing

During ordinary skill use, do not mention telemetry, ask about sharing, check sharing status, preview a payload, submit, or retry a delivery. This includes skill load, execution, finish, update checks, and installation. Legacy automatic consent and saved per-run approvals do not authorize a new attempt.

Only when the user specifically asks to send telemetry, read [references/telemetry.md](references/telemetry.md) and submit the requested closed execution run with the helper. A request to analyze telemetry, improve the skill, or install an update is not a request to send. Keep local execution journals under the logging protocol; they do not initiate sharing.

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

Before starting or resuming work in a worktree, or running tests that write persistent data, read [references/execution-evidence.md](references/execution-evidence.md). Inspect instruction freshness and the isolation gate once per unchanged worktree/environment; the gate must check actual runtime data destinations before each mutating test launch.

## Delegate substantive work

Use native collaboration tools in the current task, not sidebar tasks or external processes. Request the chosen GPT-5.6 model and effort explicitly so the worker does not inherit Astra. With the current interface, use `agent_type: "worker"`, `fork_turns: "none"`, and explicit `model` and `reasoning_effort`; avoid roles that override those settings. Workers remain leaves and do not spawn agents.

Before dispatch, assess the package's contract clarity, cross-component coupling, state/concurrency rules, algorithmic demands, and failure impact. Use this assessment to choose a route from `policy.json`; a task's size or number of parts alone does not justify Sol high. Favor `gpt-5.6-terra` at `high` for substantive implementation and investigations, following the user’s explicit preference. This preference is not a telemetry-derived cost or quality ranking. Keep these routes available and record a concrete task-specific reason when departing from Terra high:

- `gpt-5.6-luna` at `low` for narrow mechanical work; `max` is a candidate for a self-contained reasoning task with a clear contract, limited coupling, and independently checkable acceptance.
- `gpt-5.6-terra` at `high` as the preferred default for general and bounded implementation, read-heavy investigations, and dense local business rules or state transitions. `medium` remains available for clearly routine packages with a recorded reason.
- `gpt-5.6-sol` at `medium` or `high` when a concrete contextual, cross-component, concurrency/scheduling, or hard-debugging requirement warrants it over Terra high. Neither size nor a generic complexity label automatically selects Sol; choose effort for the specific requirement.

Select per package: independent packages may use different models/efforts, with Astra retaining integration acceptance. These are hypotheses from limited evidence, not a quality ranking or a guarantee that higher effort fixes an unsuitable route. Other runtime-supported efforts remain available with a task-specific reason.

If the selected model is unavailable, choose another available GPT-5.6 route and record why. If delegation is explicitly requested but native delegation or every suitable GPT-5.6 model is unavailable, report the limitation rather than silently implementing in Astra.

For work spanning persistence, retries, recovery, or multiple stateful consumers, enforce an early integration gate. Before broad implementation, identify the production entry point, affected readers/writers and lifecycle consumers, and state invariants. Define and run the smallest representative probe through the real persistence/recovery boundary in an isolated environment: include write–read–recreate or close/reopen as applicable, plus the relevant failure/retry path. Mock-only or helper-only success does not pass this gate. If the backend or required environment is unavailable, record the verification gap and limit progress to independent work; do not accept the affected milestone as verified.

Split integration-heavy packages into small behavioral milestones with explicit ownership, prerequisites, and acceptance evidence. The first milestone establishes the representative production boundary; each subsequent milestone adds one coherent lifecycle or consumer slice. Within one package, the worker verifies prerequisite milestones and proceeds without waiting for Astra. Milestones are internal checkpoints, not mandatory handoffs; Astra reviews the completed package and its accumulated evidence. Dependencies between separately owned packages still require Astra acceptance before handoff. Keep one implementation owner where state or files overlap; smaller milestones do not require more workers. After two unsuccessful corrections on the same boundary, stop repeating patches and diagnose the contract, fixture, or ownership boundary, then narrow or replan the milestone before continuing.

The worker owns its package end to end: early probes, implementation, tests, self-review, and self-correction. Return when the package is ready for acceptance. Interrupt Astra earlier only for a failed foundational probe that prevents dependent work, a material architectural decision outside the agreed brief, a scope change, or a genuine blocker. Routine progress and successful checkpoints do not require an acknowledgement or continuation prompt. Astra must not send repeated status requests, incremental review findings, or reminders while the worker is making progress; required user-facing updates do not require worker round trips.

Keep delegation visible with a concise user-facing update at dispatch: name the package, its bounded deliverable, the requested model and effort, and the task-specific selection reason. At its ready report, failure, interruption, or blocker, briefly state the actual outcome and material verification gaps. Distinguish worker-ready from coordinator-accepted. Include runtime-observed model/effort when exposed with their source; otherwise say the settings are unconfirmed rather than presenting the request as observation. Cover reviewers and failed dispatches the same way. Combine simultaneous updates when useful; avoid rigid receipts, repeated status messages, and extra worker calls solely for reporting.

For long packages or repeated context recovery, use [references/worker-context.md](references/worker-context.md). Keep tool output focused and give the worker a durable, compact working checkpoint. Judge verified progress and repeated recovery work, not compaction count alone; preserve autonomous internal milestones and reassess scope at a natural boundary when recovery is crowding out delivery.

Give each worker a fresh, self-contained brief containing:

- desired behavior, acceptance criteria, owned files or modules, and all task-specific restrictions;
- a proportionate quality contract: design constraints, error visibility, relevant complexity expectations, and critical regressions to protect; distinguish mandatory requirements from optional preferences;
- relevant project instructions and proportionate checks, including runtime or visual evidence for interactive changes; for changes spanning persistence, retries, or shared contracts, identify affected consumers and state invariants, and run one representative integration probe early;
- decisions it may make, authority to continue through internal checkpoints and self-corrections, and the specific escalation conditions that must return to Astra; for long packages include the working-checkpoint path and relevant context-management guidance;
- a reminder that others share the workspace, edits must be preserved, and shared-file ownership must not overlap;
- a concise report contract: changed paths and behavior, checks and evidence, unresolved risks, and decisions needed.

The worker owns and waits for package-scoped checks, including long-running ones. The coordinator monitors shared suites spanning multiple packages and dispatches bounded failure groups with owned files, focused checks and a clear completion result. An active suite is progress, not a completed handoff; its duration alone does not require transferring ownership. Avoid duplicating the worker's implementation or assigning overlapping writes. Astra may inspect adjacent contracts, prepare review, and continue other independent coordination. When nothing useful remains, use bounded native waits, avoid polling unchanged status, and preserve the host's user-update requirements.

## Review and correct

Default to one consolidated Astra review when the package is ready. Inspect the complete relevant diff and evidence before sending a single batch of material findings; do not drip-feed ordinary corrections as files arrive. Intervene during implementation only for the escalation conditions above or a concrete safety or destructive-action risk. Read the report, inspect the actual diff or artifacts, and assess the evidence against acceptance criteria. A successful worker report or passing tests is not acceptance. Assess the final artifact against explicit instructions, design simplicity, error visibility, and regression protection. Check that abstractions and compatibility behavior serve the requested scope, comments match the implementation, and important tests actually exercise their claims. Require changes for concrete quality defects with an explained impact; do not turn stylistic preferences into mandatory rewrites or add unrelated hardening. For a bugfix, require focused evidence that the regression check detects pre-fix behavior and exercises the claimed user or persistence boundary; retain an explicit gap when this cannot be demonstrated. Use proportionate checks for other changes.

Keep functional verification and final quality acceptance distinct. Accept only after applicable requirements and material quality findings are resolved. A corrected first-pass defect affects rework cost, not a second penalty against the final artifact. If review introduces a new requirement, identify it as such and resolve its scope before using it as an acceptance criterion; do not retroactively call it worker noncompliance. For interactive work, run or inspect the changed behavior when tooling permits and state any verification gap. Reuse valid checks; rerun them only after relevant changes, failures, or unresolved concerns.

Additional independent review needs a concrete risk or evidence gap. After corrections, review the changed area and affected integration boundaries; reuse accepted evidence. Reopen acceptance only when changed source, changed dependencies/environment, or new findings invalidate it. See [references/execution-evidence.md](references/execution-evidence.md) for recording that boundary.

Send actionable functional or quality corrections to the same worker with the location, impact, expected result, and verification method. Record substantive correction requests as changes-requested reviews under the logging protocol, including when they arise during replanning or integration; do not count the same request twice. After two unsuccessful correction rounds on the same issue, diagnose whether the cause is the brief, context, verification, environment, package size, or model/effort. Then replan from evidence by revising criteria, splitting scope, or replacing the worker. Stop the old worker before overlapping replacement work. Do not assume every failure requires a stronger model or move substantive implementation silently back to Astra.

Continue until the authorized scope and integration criteria are accepted or a genuine blocker is explained. Before closure, reconcile each assignment’s latest review with the actual integration evidence; explicitly record replacements or cancelled packages and retain unresolved gaps. Do not infer worker acceptance from a parent finish. Identify required environments and external decisions early so they do not first appear at closure. At closure, judge the agreed run scope; unrelated future work does not prevent completion. Record delivered-work integration acceptance separately from the parent outcome and record explicit blocker categories under the logging protocol. Routine implementation choices do not require user confirmation. Ask only for an unresolved decision, permission, or external change that is actually necessary.

## Keep a useful history

Read [references/logging.md](references/logging.md) before execution that will create a run. Plan-only work needs no journal. For direct Astra execution, record `start` and `finish` with checks and evidence; never invent dispatch, report, or worker-review events. For delegated work, retain package-level events: start, successful dispatch, ready report, review, needed replan, and finish. Internal worker checkpoints do not require extra report/review exchanges; summarize their evidence in the ready report.

The coordinator alone writes compact events. Register known fallback roots when the shared registry is writable; otherwise retain their paths for an explicit multi-root summary. At worker report and run completion, capture available sourced runtime settings and usage under the logging protocol, or record why they are unavailable. Do not infer actual settings from the requested route or worker self-description. Preserve the run ID and log root in handoff or compaction notes. On resumption, read the latest events and continue the same unfinished run; an interrupted run without `finish` remains incomplete. Unknown token, cost, effort, or usage values stay `null`, and account-wide quota changes are not task usage. Compare cost only among artifacts accepted against a comparable quality contract, including implementation, functional and quality corrections, and attributable Astra review. Separate shared experiment/setup overhead from per-route cost; an earlier functional pass is not cost-to-quality-acceptance.

Do not tune policy automatically. Record improvement candidates and use [references/tuning.md](references/tuning.md) only when the user asks to analyze or revise Astra Helm.

## Optional cost accounting

Only when the user requests a cost estimate or receipt, use [references/cost-accounting.md](references/cost-accounting.md) and the local calculator. A request to add this capability does not enable receipts on later tasks. Do not automatically calculate, offer, or append receipts during ordinary work. Use sourced observed usage and an explicitly supplied dated pricing snapshot; retain missing usage and incomplete coverage as gaps. Same-token repricing is not measured savings, a quality comparison, or a subscription/quota estimate. This local calculation neither sends data nor authorizes performance sharing.
