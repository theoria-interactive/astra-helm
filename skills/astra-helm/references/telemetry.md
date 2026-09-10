# Optional performance telemetry

Performance sharing is optional and independent of update checks. It is disabled until the installer explicitly opts in to the current endpoint, disclosure version, and retention period. Telemetry is a signal for reviewed improvements, not permission to change routing policy automatically.

## Disclosure before consent

Explain this before enabling sharing:

> Help improve Astra Helm by automatically sharing a small summary after eligible future runs: skill version, coarse task categories, worker model/effort choices, correction counts, final review outcomes, and available scoped token counts. No prompts, code, diffs, project names, repository URLs, file paths, raw logs, or free-text feedback are sent. The service is operated by the maintainer of `theoria-interactive/astra-helm` on Cloudflare. Sharing is optional and can be disabled at any time without affecting the skill.

Also disclose the concrete endpoint in `telemetry-config.json`, currently `https://telemetry.theoriainteractive.com/astrahelm/v1/events`, and these limits:

- Each transmitted event has a random delivery ID for deduplication. No persistent installation identifier or local run/assignment ID is sent.
- The receiver stores the allowlisted summary and its receipt time. IP addresses are used transiently for rate limiting; the application does not store them or user-agent strings. Cloudflare handles connection metadata under its own policies. Do not promise anonymity.
- Active records are retained for 30 days and removed by a daily cleanup, allowing up to one extra day. Cloudflare D1 recovery history may retain deleted records for up to a further 30 days depending on the plan. See [D1 Time Travel](https://developers.cloudflare.com/d1/reference/time-travel/).
- Opting out stops future submissions and retries; it does not retroactively remove received events. Historical runs from before consent are never backfilled.
- The data is self-reported, and its review outcomes are not independent quality certification. Missing usage stays unknown; it is not replaced by account quota, guessed cost, or inferred zero.

Ask whether the installer wants to enable this sharing. Save only an explicit answer. If unanswered, continue the original task with sharing disabled and avoid repeating the question in the same conversation. Remember an opt-out without re-prompting each run. Changes to endpoint, disclosure, or retention require renewed consent before sending; never silently carry old consent forward.

## Commands and lifecycle

```text
python3 <skill-dir>/scripts/telemetry.py status
python3 <skill-dir>/scripts/telemetry.py configure --consent on
python3 <skill-dir>/scripts/telemetry.py configure --consent off
python3 <skill-dir>/scripts/telemetry.py preview --log-root <run-root> --run-id <run-id>
python3 <skill-dir>/scripts/telemetry.py submit --log-root <run-root> --run-id <run-id>
```

Status and preview do not send network requests. Resolve local file/network permissions through the host as needed; permission to use the filesystem is not user consent to share data. Never run configure-on merely because the author of the skill enabled telemetry support.

After an eligible execution run's `finish` event, use `submit` once. The helper checks consent, the run's start time, source validity, and its own allowlist. It excludes tuning, test, synthetic, incomplete, and corrupt runs. It never sends journal contents wholesale. It makes at most one bounded request per invocation, remembers successful delivery, and limits retries with backoff. There is no daemon or unbounded background queue. Reattempt only a known eligible failed submission when the helper allows it; do not scan history to invent a backlog.

Keep `.telemetry-state.json` and the lock local and untracked. The state holds consent and delivery bookkeeping; preserve it during updates. The public endpoint and disclosure settings are managed release files, so a changed destination is visible in review and invalidates consent. Do not place authentication secrets in the distributable skill.

## Interpretation

Use comparable task categories and policy versions; distinguish requested settings from sourced runtime evidence. A corrected defect is rework, not an enduring final-code penalty. Keep functional, quality, and unclassified corrections separate. Optional task characteristics are transmitted only if explicitly recorded as supported categories. Usage is exported only for a single complete measurement with a supported turn scope. Multiple measurements cannot establish non-overlap from journal IDs alone, so they remain null, as do ambiguous or incomplete counters, with a categorical reason.

An open ingestion endpoint cannot establish that a real user consented, that a model ran, or that an event is honest. Treat contributions as untrusted observations, retain missing-data indicators, and validate proposed routing changes using targeted tests or benchmarks. Do not expose raw contributed events through public read endpoints or treat a high event count as evidence of causality.
