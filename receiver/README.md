# Astra Helm telemetry receiver

This directory contains the minimal Cloudflare Worker that receives Astra Helm's opt-in, categorical telemetry. Its production base is `https://telemetry.theoriainteractive.com/astrahelm`. It has these public routes:

- `POST /astrahelm/v1/events` validates and stores one event.
- `GET /astrahelm/health` returns only `{ "ok": true }`.
- `GET /astrahelm/privacy` returns the field allowlist and privacy/retention disclosure.

`GET /astrahelm` (with or without a trailing slash) also returns the privacy disclosure. The original Workers.dev routes remain available for existing clients; requests are not redirected. Updated clients require renewed consent for the new endpoint and disclosure.

There are no public data-reading routes. The receiver never logs requests or application errors, and Workers observability is intentionally disabled so telemetry payloads and request metadata do not enter Workers Logs or traces. The payload is untrusted self-reported data; accepting it cannot prove that a client obtained consent.

## Storage and retention

The D1 `events` table stores only a validated, canonical allowlist payload, its event ID and SHA-256 digest for idempotence, and the server ingestion timestamp. It does not store IP addresses, User-Agent values, prompts, project identifiers, paths, or source material.

A daily Cron Trigger runs at 03:17 UTC and deletes active rows older than 30 days. Scheduling adds up to one day of deletion lag. D1 Time Travel is separate provider-managed recovery history: after active deletion, deleted rows may remain recoverable for up to 30 additional days on paid plans or 7 days on free plans. Cloudflare may also process connection metadata under its own policies.

The rate limiter hashes the transient connecting IP and applies 10 events/minute per IP. Sixteen keys also give an approximate aggregate ceiling of 160 events/minute per Cloudflare location. Cloudflare documents these counters as local to a location and eventually consistent, so neither limit is an exact global quota. A rate-limiter failure returns `503` and never writes to D1.

## Local verification

Requires Node.js 20 or newer. Wrangler is pinned exactly in `package.json`.

```sh
npm install
npm test
npm run db:migrate:local
npm run check
```

For a local endpoint with the scheduled-test route enabled:

```sh
npm run dev
```

Wrangler keeps local D1 data under `.wrangler/`, which is ignored by Git.

## Operator setup and deploy

The dedicated D1 database and account ID are declared in `wrangler.jsonc`. The rate-limit namespace ID must remain a positive integer unique to the account; replace the checked-in value if it is already used by another limiter.

Apply the migration before deploying:

```sh
npm run db:migrate:remote
npm run check
npm run deploy
```

No secret or private credential belongs in this repository. Wrangler obtains operator authentication from its normal interactive or CI environment. The expected production route is `https://telemetry.theoriainteractive.com/astrahelm/v1/events`.

The proxied DNS record for `telemetry.theoriainteractive.com` is an originless AAAA record (`100::`). The two path-scoped Worker routes in `wrangler.jsonc` serve Astra Helm without claiming other telemetry paths.

## Outcome metadata rollout

Version 1.7.0 adds optional `delivered_work_status` and `blocker_reasons` fields to schema version 1. The receiver accepts older payloads with these fields absent; no D1 migration or historical backfill is needed. Missing fields mean unknown. Blocker categories describe why the parent scope stopped, while delivered-work status records integration acceptance separately.

Deploy the updated receiver before installing or distributing clients that emit these fields: the previous receiver's strict allowlist rejects them. Then clients must renew consent to disclosure version 3 before sending expanded summaries. A source push alone does not deploy the receiver or update installed skills. Preserve frozen retry payloads and historical rows.
