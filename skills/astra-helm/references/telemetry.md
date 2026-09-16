# Explicitly requested performance sharing

Read this reference only when the user specifically requests a submission or asks about the sharing mechanism. During ordinary skill use, do not mention telemetry, solicit sharing, run status or preview, submit, or retry. Skill load, finish, update checks, and installation never trigger sharing. Local journals remain available for execution evidence and analysis.

## Requested submission

A specific user request to send a named closed execution run authorizes its submission. If the user says to send the current completed run, resolve it from the current journal; do not ask again when the scope is clear. A request to analyze the database, improve the skill, or install an update does not authorize sending. Clarify only an unresolved run identity or destination that actually prevents the requested action.

Use the installed helper and its existing delivery state. Include `--approve-run` only after that specific request. Each invocation requires current authorization: legacy automatic consent, a saved approval, or an unfinished retry never authorizes a new invocation by itself. An explicit request to retry authorizes that retry; do not schedule, poll, or retry automatically after failure. A current explicit request may authorize one run despite an older saved opt-out, without enabling future sharing.

The submission goes to the endpoint in `telemetry-config.json`, currently `https://telemetry.theoriainteractive.com/astrahelm/v1/events`, operated by the maintainer of `theoria-interactive/astra-helm`. The payload contains only allowlisted policy version, coarse task/risk and explicitly recorded routing categories, requested and available observed worker settings, correction counts and distinct correction rounds, final review outcomes, delivered-work acceptance, blocker categories, and available scoped token counts. It never contains prompts, code, diffs, project names, repository URLs, file paths, raw logs, free-text feedback, persistent installation IDs, or local run IDs. Do not add another approval ceremony when the user has already requested this submission; briefly report its result.

Every delivery has a random event ID for deduplication. The receiver stores the allowlisted summary and receipt time for 30 days, with daily cleanup that can take up to one more day; provider recovery history can retain deleted records for up to a further 30 days depending on the plan. The application does not store IP addresses or user-agent strings. IP addresses are used transiently for rate limiting, and Cloudflare processes connection metadata under its own policies. Do not promise anonymity.

## Commands

```text
python3 <skill-dir>/scripts/telemetry.py preview --log-root <run-root> --run-id <run-id>
python3 <skill-dir>/scripts/telemetry.py submit --log-root <run-root> --run-id <run-id> --approve-run
```

`preview` is local and records no approval; use it only when relevant to a user-requested inspection or submission. Bare `submit` cannot send, even when old state contains automatic consent or approval. `configure --consent on` and `configure --consent ask` return an explicit-only error; `configure --consent off` can still record a decline when specifically requested. Global automatic or selective-question modes are no longer supported. Do not invoke configuration or status as a routine part of skill use.

The helper excludes test, tuning, synthetic, incomplete, and corrupt runs. It validates the allowlist, makes at most one bounded request per invocation, saves the delivery ID, frozen payload, and attempt before network I/O, and limits delivery to three attempts with backoff. An explicitly requested retry keeps the same identity and exact payload; new fields are never backfilled into frozen deliveries. A new request binds authorization to the current endpoint, disclosure, and retention. Do not manufacture a state file, another event ID, or a hand-posted payload. A failed submission must not prevent completion of other requested work.

## Interpretation and provenance

`outcome` describes closure of the agreed parent scope. Optional `delivered_work_status` records integration review; `blocker_reasons` uses explicit journal categories. A worker's `final_verdict` is its last recorded review, not inferred from parent acceptance. Optional per-route `assignment_disposition` carries only an explicitly recorded `superseded` or `cancelled` category. It does not overwrite the last review or imply acceptance. Missing disposition is unknown; assignment IDs and replacement explanations remain local.

Optional `correction_rounds` counts each changes-requested review once. Functional and quality category counts overlap for `both` reviews; do not add categories to obtain a distinct-round total. Missing historical fields and unavailable usage remain unknown. Contributions are self-reported and selected for submission, not representative usage statistics, quality certification, or evidence of causality.

Keep run IDs and log roots in local handoff notes. Missing local delivery records leave provenance unresolved; identical categorical submissions with different random IDs are candidates for investigation, not proof of duplicate work. Never upload journals or their free-text fields.
