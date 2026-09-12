# Optional performance telemetry

Performance sharing is optional. The default is to ask selectively after a valuable closed execution run, not during skill load, installation, or an ordinary update. Telemetry never changes routing policy automatically.

## Disclosure and approval

Before asking about a particular run, explain that the submission contains only: skill and policy version, coarse task and risk categories, worker model/effort choices, correction counts, final review outcomes, delivered-work acceptance, categorical blocker reasons, and available scoped token counts. It never contains prompts, code, diffs, project names, repository URLs, file paths, raw logs, free-text feedback, persistent installation IDs, or local run IDs.

The endpoint is the value in `telemetry-config.json`, currently `https://telemetry.theoriainteractive.com/astrahelm/v1/events`, operated by the maintainer of `theoria-interactive/astra-helm` on Cloudflare. Every delivery has a random event ID used for deduplication. The receiver stores the allowlisted summary and receipt time for 30 days, with daily cleanup that can take up to one more day; Cloudflare D1 recovery history can retain deleted records for up to a further 30 days depending on its plan. IP addresses are used transiently for rate limiting and the application does not store IP addresses or user-agent strings. Cloudflare still processes normal connection metadata. Do not promise anonymity.

Ask only after a closed execution run that has potentially useful routing, correction, verification, or blocker evidence. A concise affirmative for the named run is enough. It authorizes one invocation of the helper for that run, including its bounded retries; it does not create an automatic opt-in or authorize historical backfill. A completed run may be approved after it finishes even if it began earlier. Do not require a consent transcript, receipt file, or a second approval after that affirmative.

An unanswered or negative answer means no submission. Do not repeat the question in the same conversation. A saved opt-out prevents questions, submissions, and retries. Opting out stops future deliveries but does not remove an event already received. Endpoint, disclosure, or retention changes invalidate a one-run approval before any retry. The helper retains the original event ID and frozen payload when a user explicitly re-approves that same unsent run against a new disclosure binding.

Existing valid automatic-send consent from an earlier release remains compatible: eligible runs started after that consent may send without another question. It is never created by the selective path. A user can switch it off without opting out by selecting `configure --consent ask`; that preserves the selective post-run behavior. `configure --consent off` records an opt-out.

## Commands

```text
python3 <skill-dir>/scripts/telemetry.py status
python3 <skill-dir>/scripts/telemetry.py configure --consent ask
python3 <skill-dir>/scripts/telemetry.py configure --consent off
python3 <skill-dir>/scripts/telemetry.py preview --log-root <run-root> --run-id <run-id>
python3 <skill-dir>/scripts/telemetry.py submit --log-root <run-root> --run-id <run-id> --approve-run
```

`status` and `preview` are local and do not send data. `preview` can inspect a closed eligible run before it has approval and does not record an approval. The coordinator must have received the user's affirmative before adding `--approve-run`; that flag is the single-step record of the scoped authorization. Retry the same run without the flag only when its saved one-run approval remains bound to the current endpoint, disclosure, and retention.

The legacy `configure --consent on --consent-evidence-file <local-receipt.json>` command remains only to preserve already valid automatic-consent installations. Do not use it to solicit new automatic sharing. It still validates its local receipt and endpoint binding.

The helper excludes test, tuning, synthetic, incomplete, and corrupt runs. It validates the payload allowlist, makes at most one bounded request per invocation, persists the event ID, frozen payload, and attempt before network I/O, and limits delivery to three attempts with backoff. Do not manufacture a state file, another event ID, or a hand-posted payload. A helper failure, unavailable endpoint, or missing approval must never block the requested work.

## Interpretation and provenance

`outcome` is closure of the agreed parent scope. Optional `delivered_work_status` records integration review of delivered work, and `blocker_reasons` uses only the structured categories from the journal. Missing usage remains unknown. Contributions are self-reported and untrusted observations, not quality certification or evidence of causality.

Use the installed helper and delivery state when analyzing a submission. Keep the run ID and log root in local handoff notes. A missing local delivery record leaves provenance unresolved; identical categorical submissions with different random IDs are candidates for investigation, not proof of duplicate work.
