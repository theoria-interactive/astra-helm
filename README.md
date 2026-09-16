# Astra Helm

Astra Helm keeps Astra responsible for planning, task-aware routing, source review, corrections, and final acceptance. It delegates substantive packages to explicitly chosen GPT-5.6 workers and can run independent packages in parallel with different models and efforts.

This is Theoria Interactive’s maintained home of Astra Helm, originally published in [kivancguckiran/skills](https://github.com/kivancguckiran/skills). The original repository retains a migration snapshot; future Astra Helm releases are published here.

## Install

Copy the whole `skills/astra-helm` directory into your Codex skills directory, preserving your existing local `settings.json` and preference files when upgrading manually. The folder contains the skill, routing policy, journal helper, updater, and optional telemetry client.

```bash
git clone https://github.com/theoria-interactive/astra-helm.git
mkdir -p "${CODEX_HOME:-$HOME/.codex}/skills"
cp -R astra-helm/skills/astra-helm "${CODEX_HOME:-$HOME/.codex}/skills/"
```

The copy command is for a fresh installation. Review or back up an existing customized copy before a manual upgrade. Use the skill in a new task after installation so the host can load the new instructions. Astra and suitable native GPT-5.6 worker models must be available; installing the skill does not provide models or change the host's selected model.

## Routing and acceptance

The coordinator stays at Astra medium unless explicitly overridden. Small coherent work can remain in Astra. Larger requests are split when behavior and file ownership provide useful boundaries; dependent packages wait for accepted prerequisites. Model and effort are selected per package, with Astra retaining integration acceptance.

Passing tests alone is not acceptance: review considers instruction compliance, design simplicity, error visibility, and critical regression coverage. See [the skill](skills/astra-helm/SKILL.md) and [versioned policy](skills/astra-helm/policy.json).

## Updates

Update checks are opt-in and throttled to about once weekly when the agent loads the skill. Installation requires approval of the offered immutable commit. The updater verifies managed-file hashes, preserves settings and local preferences, detects customizations, and keeps a backup. It does not update maintained Git checkouts. See [the update protocol](skills/astra-helm/references/updates.md).

Version 1.6.0 in the original skills repository changes the updater source to this repository. Existing 1.5.0 installers can receive that migration release through the old source; later checks use this one. Copies older than 1.5.0 need a reviewed manual upgrade to obtain the updater and baseline manifest.

## Optional performance sharing

Telemetry is **explicit-request-only**. Normal skill use never mentions sharing, asks a question, checks sharing status, or attempts a submission or retry. Sending requires the user to specifically request the closed execution run. Previous automatic consents and saved run approvals do not authorize new attempts. The installer emits no sharing follow-up.

The Theoria Interactive-operated endpoint is `https://telemetry.theoriainteractive.com/astrahelm/v1/events`. Only allowlisted categories, review and correction counts, and available scoped measurements are sent. No prompts, code, free-text logs, project names, paths, repository URLs, persistent installation IDs, or local run IDs are transmitted. Application storage excludes IP addresses and user-agent strings; Cloudflare still processes connection metadata and IP addresses are used transiently for rate limiting.

Active rows are retained for 30 days with up to one day of cleanup lag. Provider recovery history is separate. See [the full disclosure and commands](skills/astra-helm/references/telemetry.md). The [receiver](receiver/README.md) has no public data-read API.

Version 1.9.0 added a distinct `correction_rounds` count alongside overlapping functional/quality categories and local assignment-closure diagnostics. Parent completion, delivered-work acceptance, and individual worker reviews remain separate evidence. Older payloads remain valid; missing measurements are unknown, and frozen deliveries are preserved. Model routing defaults are unchanged because the selected observations do not establish comparable cost or quality rankings.

## Astra Helm benchmarks

A small, exploratory benchmark on September 7, 2026 compared Astra medium coordination with different GPT-5.6 worker models and reasoning efforts. Astra handled planning, dispatch, source review, and acceptance. Workers received the same task contract within each comparison and produced separate implementations. These observations informed the provisional routing and quality acceptance rules in [Astra Helm](skills/astra-helm/SKILL.md) and its [policy](skills/astra-helm/policy.json).

### Tasks and functional results

The pilot combined a dependency-graph batch planner and an asynchronous cache, evaluated with 28 independent checks. Each route used one fresh worker. All six routes passed 28/28 on their first submitted implementation; no coordinator-requested correction was needed.

| Pilot worker | Effort | Total worker tokens | Worker cost equivalent (USD) |
| --- | --- | ---: | ---: |
| Sol | medium | 333,380 | $0.6248 |
| Sol | high | 317,293 | $0.6973 |
| Terra | medium | 313,541 | $0.2005 |
| Terra | high | 321,287 | $0.2271 |
| Luna | low | 252,408 | $0.0136 |
| Luna | max | 665,141 | $0.0462 |

Two harder tasks examined implementation and integration:

- **A — Transactional inventory:** one worker implemented atomic batches, compare-and-swap retries, durable idempotency, reservations, expiration, rollback, and detached snapshots. There were 23 independent checks.
- **B — Three-part workflow engine:** three workers per route owned a graph compiler, immutable state reducer, and concurrent runner with retries and cancellation. Component review preceded the first combined evaluation of 30 checks. Separate ownership did not imply that all workers ran simultaneously.

| Task | Worker route | Workers | First → final checks passed | Correction turns | Total worker tokens | Worker cost equivalent (USD) |
| --- | --- | ---: | --- | ---: | ---: | ---: |
| A | Luna max | 1 | 22/23 → 23/23 | 1 | 1,079,861 | $0.0638 |
| A | Terra high | 1 | 23/23 → 23/23 | 0 | 259,106 | $0.2295 |
| A | Sol high | 1 | 23/23 → 23/23 | 0 | 471,866 | $0.5808 |
| B | Luna max | 3 | 30/30 → 30/30 | 0 | 2,379,263 | $0.1278 |
| B | Terra high | 3 | 30/30 → 30/30 | 0 | 1,609,828 | $0.8712 |
| B | Sol high | 3 | 30/30 → 30/30 | 0 | 1,328,993 | $1.5086 |

Correction turns count follow-ups requested by Astra after submission. Workers' own pre-submission revisions are included in token usage. Luna's inventory correction restored a required reservation `id` field and added regression coverage; its row includes that correction's usage.

### Final code quality

Passing the functional checks did not establish equal maintainability or complete instruction compliance. A subsequent source review assessed the final implementations, including corrected code:

- **Sol high was the preferred overall implementation foundation in these two harder tasks.** Its inventory normalization was more direct, and its workflow runner used an incremental priority queue instead of repeatedly scanning the whole plan. This was a design finding, not a measured runtime speedup.
- **Terra high offered a particularly straightforward state reducer.** Its inventory validation included an avoidable quadratic scan, while its runner silently swallowed unexpected callback errors and overstated its overall complexity in a comment. Those findings warranted quality corrections despite passing tests; an actual hang on valid contract inputs was not demonstrated.
- **Luna max needed more design simplification, but its corrected inventory tests protected an important requirement better.** Removing the required `id` field in isolated copies caused Luna's final tests to fail; Terra's and Sol's tests still passed. This was one targeted mutation experiment, not a general test-quality score. The corrected initial defect was counted as rework, not penalized again as a defect of the final code.
- **The graph compilers showed no compelling quality separation.** All three used appropriate heap-based topological processing and detached, frozen plans.

The stronger quality criteria were applied after the functional benchmark. Additional cleanup rounds to satisfy them were **not run**, so the tables do not measure total cost to final quality acceptance. Explicit contract violations were distinguished from newly introduced review expectations and optional style preferences.

### Cost interpretation and limits

Token totals come from runtime usage records: input includes cached input and repeated context; output includes reasoning tokens, which are not counted twice. Costs are historical **standard API equivalents**, calculated using the experiment's rates per million uncached input / cached input / output tokens: Astra $10 / $1 / $50; Sol $4 / $0.40 / $20; Terra $2 / $0.20 / $12; Luna $0.20 / $0.02 / $1.20. They are not current price quotes, actual invoices, Codex subscription quota measurements, or measured priority-tier charges.

The tables contain worker costs only. At the recorded cutoffs, the pilot used 5,179,934 tokens ($6.4403 equivalent), including shared Astra work; the harder-task experiment used 17,248,820 tokens ($16.2927 equivalent), including 10,119,903 Astra tokens ($12.9110). Shared work included benchmark preparation, coordination, review, and reporting. It cannot be treated as the marginal coordinator cost of a single route, and reporting after the cutoffs was excluded.

There was one implementation per task/route, one coordinator, and no blind quality review or repeated trials. Cache and execution-order effects were not controlled. The harder tasks compared only Luna max, Terra high, and Sol high; they do not establish an ordering at other efforts. Raw local benchmark artifacts are not included in this repository, so this section reports observations rather than providing a reproducible benchmark suite.

The resulting policy is to choose a worker for each package's requirements, review against a shared quality contract, and compare costs among solutions that meet it. Clear, independent work can justify Luna or Terra; coupled scheduling and concurrency work can justify Sol high. Mixed-model execution remains a routing option whose end-to-end savings were not measured here.

## Version 1.10.0

Persistent application tests require a runtime-resolved destination gate before writes; when no safe gate is available, the affected test remains unrun. Bugfix verification must demonstrate sensitivity to the pre-fix behavior at the claimed boundary or retain an explicit evidence gap. Long-running suite monitoring stays with the coordinator while workers own bounded repair packages.

Explicitly requested summaries can include a per-route `assignment_disposition` category (`superseded` or `cancelled`) without transmitting assignment IDs or replacing historical review verdicts. Older payloads and frozen retries remain valid. Routing defaults and explicit-request-only sharing are unchanged.

## Development

```bash
python3 -m unittest discover -s skills/astra-helm/scripts -p 'test_*.py'
```

Receiver tests and deployment instructions are in [receiver/README.md](receiver/README.md). Update `policy.json` for behavior changes, then regenerate the update manifest after all distributable files are final:

```bash
python3 skills/astra-helm/scripts/build_update_manifest.py --note "Describe the reviewed release changes"
```

Private logs, state, credentials, and receiver data do not belong in the repository. The manifest includes public telemetry configuration but excludes installer-local preferences and journals.

## License

MIT; see [LICENSE](LICENSE).
