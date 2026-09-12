# Journal protocol

Run the installed `scripts/journal.py` with Python 3. It uses the standard library. The helper reads `settings.json` for the shared log directory; `--log-root DIR` overrides it. Without settings it uses `work/astra-helm-logs` under the current working directory. Keep that root stable throughout a run.

Resolve access before `start`: the configured shared path must be within the current writable roots or covered by an actual grant. If access is missing, request write access to that directory only using the available host permission tool, at most once per session. Reuse grants; do not retry a denied request. If the host cannot grant access, pass `--log-root` before the subcommand to use an authorized workspace directory and report that fallback root once. The Python helper cannot grant itself sandbox permissions. A run already started in fallback stays there. Once shared-root access is available, register its location with `register-root --path DIR`; this writes only a root reference and does not copy, move, or close the run. If registration is unavailable, retain the exact path in handoff notes and use `summary --include-root DIR` for analysis. Prefer a durable authorized workspace fallback over temporary storage. A logging failure must not stop otherwise authorized work; disclose missing history without repeated permission prompts.

Only the coordinator writes events. A UUID-named JSONL file holds one run. Records are append-only, timestamped in UTC, and locked during writes. The start record captures the current policy and a skill fingerprint. This is an operational record of agent decisions, not automatic runtime telemetry.

Plan- or advice-only work does not need an execution journal. For a small task executed directly by Astra, record `start` and `finish`; include the checks and evidence in the finish payload and do not create fictitious `dispatch`, `report`, or `review` events. Delegated work retains the applicable milestone sequence below.

Write a small JSON payload to a scratch file using a structured file tool or a safely quoted heredoc. Then pass its path with `--data-file`; do not interpolate user text into shell arguments. Resolve `<skill-dir>` to the directory containing SKILL.md and `<run-id>` to the UUID returned by start.

```text
python3 <skill-dir>/scripts/journal.py start --data-file work/helm-start.json
python3 <skill-dir>/scripts/journal.py record --run-id <run-id> --event dispatch --data-file work/helm-dispatch.json
python3 <skill-dir>/scripts/journal.py record --run-id <run-id> --event report --data-file work/helm-report.json
python3 <skill-dir>/scripts/journal.py record --run-id <run-id> --event review --data-file work/helm-review.json
python3 <skill-dir>/scripts/journal.py record --run-id <run-id> --event finish --data-file work/helm-finish.json
python3 <skill-dir>/scripts/journal.py summary --project example-project --last 30
```

Payloads are JSON objects. Keep each under 16 KB, normally a few hundred words at most. Missing measurements must remain null. Do not store code, full diffs, terminal output, credentials, private reasoning, or full user prompts. Evidence paths and short summaries are sufficient. The helper does not automatically redact secrets: select the payload carefully.

| Event | Required payload fields | Useful additional fields |
|---|---|---|
| `start` | `project`, `task_summary`, `task_type`, `risk` | `kind` (execution/test/tuning), `thread_id`, `coordinator`, `acceptance_criteria`, `plan_ref`, `parent_id`, `work_size`, `item_count`, `dispatch_authorization`, `goal_id` |
| `dispatch` | `assignment_id`, `model`, `effort`, `reason` | `agent_id`, `actual_model`, `actual_effort`, `runtime_source`, `owned_paths`, `acceptance_criteria`, `quality_contract`, `routing_assessment`, `work_item_id`, `parent_id`, `depends_on`, `plan_ref`, `scheduling_reason`, `active_worker_count` |
| `report` | `assignment_id`, `summary` | `changed_paths`, `checks`, `evidence_paths`, `limitations`, `usage`, confirmed runtime settings |
| `review` | `assignment_id`, `verdict`, `findings` (array) | `evidence_paths`, `verification_gaps`, `coordinator`, `round`, `functional_status`, `quality_assessment`, `criteria_changes`, `correction_kind` |
| `replan` | `reason` | `assignment_id`, `cause`, `next_action`, `spawn_error` |
| `finish` | `outcome` | `summary`, `checks`, `evidence_paths`, `remaining_limitations`, `usage`, `quality_acceptance`, `delivered_work_status`, `blocker_reasons`, `improvement_candidates` |
| `feedback` | `summary` | `assignment_id`, `regression`, `source`, `evidence_paths` |
| `runtime` | `source`, `actual_model`, `actual_effort`, and exactly one of `assignment_id` or `coordinator: true` | `usage` with measurement ID and scope; see below |
| `policy_change` | `reason`, `before_version`, `after_version` | `supporting_run_ids`, `before`, `after`, `revision_artifact` |

Start example:

```json
{
  "project": "example-project",
  "task_summary": "Correct controller navigation in the inventory",
  "task_type": "bugfix",
  "risk": "medium",
  "kind": "execution",
  "coordinator": {
    "requested_model": "gpt-6-astra",
    "actual_model": null,
    "requested_effort": "medium",
    "actual_effort": null
  },
  "acceptance_criteria": ["Selection remains visible when changing inventory tabs"]
}
```

Use a stable project label across worktrees. Prefer a small consistent set of `task_type` values such as feature, bugfix, refactor, mechanical, investigation; use low/medium/high for risk. `model` and `effort` in dispatch mean requested settings. Record confirmed values only with a runtime source; a successful spawn request or worker self-description alone does not confirm which backend model actually ran.

Assign each work package or replacement worker its own `assignment_id`. Reports and reviews use that ID. Follow-up corrections to the same package use more report/review events, not fictitious new agents. Record a failed spawn as `replan` with `spawn_error`; count `dispatch` only after a worker was actually created. If a new worker replaces one, include the relationship in `reason`.

Keep a concise record of the user-authorized execution or delegation scope in `dispatch_authorization`, not the full user prompt. Include `goal_id` only when an actual user-requested goal was created. Plan-only work creates no execution run; once execution is requested, record only milestones that actually occur.

For an epic or milestone, use one run for the authorized parent scope and link dispatches with stable `work_item_id` values. A replacement gets a new assignment ID but retains the item's ID. A reused worker taking a different item gets a new assignment ID and a dispatch event with its existing agent ID. Keep the detailed item/dependency table in `plan_ref`, not in every journal event. `active_worker_count` is an observed scheduling count, not a quota measurement. Record dependency, ownership, or capacity constraints in `scheduling_reason` so later analysis can distinguish useful parallelism from avoidable serial execution. Reports and reviews remain linked by assignment ID. The parent finish follows the combined integration review, or explicitly records incomplete blocked/failed scope.

Review verdicts: `accepted`, `changes_requested`, `blocked`. `accepted` means both applicable functional and quality criteria are satisfied. In the existing review event, record functional status separately from a compact quality assessment covering instruction compliance, design simplicity, error visibility, and critical regression protection; note non-applicable dimensions briefly. Link findings to the source/evidence boundary and classify correction requests as functional, quality, or both. Record newly introduced criteria separately from violations of the original brief. These payload additions are descriptive fields; the helper does not validate or decide quality. Keep corrected defects in historical review events without treating them as defects of the final artifact. Findings should describe observable problems and expected corrections. Finish outcomes: `completed`, `blocked`, `cancelled`, `failed`. Do not mark work completed while acceptance criteria remain unverified without explaining and resolving that limitation. After finishing, append later feedback to the same run. A resumed task that was formally closed should use a new run and reference the previous ID.

## Record substantive corrections consistently

When review finds a concrete defect requiring worker changes, append one `review` with `verdict: "changes_requested"`, the affected `assignment_id`, findings, and `correction_kind: "functional"`, `"quality"`, or `"both"`. Do this even when the finding arrives during integration or native diagnostics. If the same decision also changes the plan, add a `replan` describing that change; do not replace the correction review with a replan or hide it only in a later report.

Group findings sent together into one correction round. Do not create another correction review merely to repeat an already-recorded request, and do not classify routine implementation progress, environment-only retries, optional polish, or newly introduced requirements as original-brief defects. Worker self-corrections before review may be described in reports but are not coordinator correction rounds. Record later acceptance after inspecting the corrected evidence.

Telemetry correction counts measure recorded review rounds, not individual defects, all edits, tokens, or total remediation effort. A `both` round contributes to both counters; adding those counters does not give a distinct-round total. Missing historical review events remain unknown: do not backfill synthetic reviews or alter previously submitted summaries to improve the statistics.

## Record closure against the agreed scope

Set `outcome` against the run's agreed acceptance criteria: `completed` when they are satisfied, `blocked` when an unresolved dependency prevents finishing, `cancelled` when the scope is stopped, or `failed` when the attempt ends unsuccessfully. Unrelated future work and optional enhancements do not make completed scope blocked. Do not shrink the agreed scope at closure to manufacture completion. An interruption without a closure decision stays unfinished without a `finish` event.

Record `delivered_work_status` separately: `accepted` only after reviewing the delivered work together against its applicable functional and quality criteria, `changes_requested` when delivered work has unresolved review findings, or `not_reviewed` when integration acceptance has not occurred. Accepted individual workers do not imply accepted integration or completed parent scope. A blocked parent may have accepted delivered work and unfinished requirements.

For a blocked finish, record all applicable `blocker_reasons` from `pending_decision`, `external_approval`, `environment_limitation`, `unresolved_defect`, and `verification_gap`. Use each category once. Keep concrete reasons, affected requirements, and the next action in local `remaining_limitations` or `summary`. An omitted category list means unknown; an empty list means no recorded categories. Nonempty blocker lists require `outcome: "blocked"`. These fields are optional for older records; never infer them from prose or rewrite historical events.

For example, reviewed implementation waiting on an in-scope access-policy decision can close with `outcome: "blocked"`, `delivered_work_status: "accepted"`, and `blocker_reasons: ["pending_decision"]`. If that decision belongs to a separate future project phase, judge this run on its own agreed criteria.

If actual usage is supplied, preserve its scope and provenance, for example `usage: {"scope": "worker_turn", "source": "runtime result", "input_tokens": 100, "output_tokens": 40}`. Otherwise use `usage: null`. Never extrapolate API prices to Codex quota or infer a task's cost from account-wide usage. Elapsed wall time measures time between journal events, including waiting. Attribute implementation, correction, and coordinator-review usage only where observable; do not invent phase splits from aggregate counters. Preserve shared setup/benchmark overhead separately. A functional pass followed by unresolved quality findings is not a completed cost-to-acceptance measurement.

`summary` gives compact run rows and aggregates for routing analysis. Group labels refer to requested worker settings; review counts are events, not unique tasks or benchmark scores. Inspect raw records for runtime confirmation, causes, partial progress, and feedback. Synthetic tests belong in a scratch root and must never contaminate real usage statistics.

## Collect fallback history

Register only known journal directories, with access to the shared root resolved as above:

```text
python3 <skill-dir>/scripts/journal.py register-root --path <fallback-directory>
python3 <skill-dir>/scripts/journal.py summary --last 30
python3 <skill-dir>/scripts/journal.py summary --include-root <unregistered-directory> --last 30
```

The local root registry belongs beside journal files, never in the public skill repository. Summary reads the selected root and explicitly registered/included roots, without recursively discovering other directories. Repeated roots and identical copies of a run must not inflate counts. Conflicting copies are a history problem, not two executions; inspect warnings and resolve provenance before using them in comparisons. Missing temporary roots and unfinished journals remain evidence gaps, not inferred failures or successes.

## Capture runtime evidence

At each worker report and at completion, check whether the host exposes attributable model/effort and token usage. Record observations through a `runtime` event with a source reference; usage observations also require a measurement ID. Keep requested settings in `dispatch`/`coordinator`; only runtime evidence can establish actual settings. If unavailable, record null values and a brief reason in the report or finish (`runtime_unavailable_reason`, `usage_unavailable_reason`). Do not block task completion or run extra model calls merely to obtain telemetry.

Record available input, cached-input, output, and reasoning-output counters with their scope and provenance. Cached input is a subset of input; reasoning output is a subset of output. Zero is a measured value, not missing data. Preserve each measurement's boundary: worker turn, coordinator turn, or an explicitly bounded run. Distinguish implementation, corrections, and review only when the source actually supports those phase boundaries. Reused workers need assignment/turn attribution; their lifetime totals do not belong to every package.

Use one stable measurement ID per observation. A repeated observation must not become new consumption. Updated cumulative snapshots and per-turn measurements may overlap; the summary exposes evidence without adding these into a billable total. Do not subtract counters across resets or substitute account quota changes. If a reliable source only becomes available after finish, append runtime evidence to the same run; do not rewrite old events or fabricate missing history. The helper validates supplied evidence structure, not the truth of a claimed source, and does not scrape transcripts or query account billing.

Example runtime payload (illustrative values only):

```json
{
  "assignment_id": "inventory",
  "source": "host runtime result for worker turn 2",
  "actual_model": "gpt-5.6-terra",
  "actual_effort": "high",
  "usage": {
    "measurement_id": "inventory-turn-2",
    "scope": "worker_turn",
    "source": "host runtime usage for worker turn 2",
    "input_tokens": 1000,
    "cached_input_tokens": 800,
    "output_tokens": 200,
    "reasoning_output_tokens": 100
  }
}
```

For coordinator evidence, replace `assignment_id` with `"coordinator": true`. Both actual-setting fields are required but may be null; usage may be omitted or null. Save the payload and append it with:

```text
python3 <skill-dir>/scripts/journal.py record --run-id <run-id> --event runtime --data-file work/helm-runtime.json
```

After finish, optional sharing is governed by [telemetry.md](telemetry.md). The journal remains the local evidence record; only the dedicated telemetry helper may construct and submit the minimized allowlist, after checking separate consent. Never send this journal file or its free-text fields to the receiver.
