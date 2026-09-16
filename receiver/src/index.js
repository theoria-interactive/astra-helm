const MAX_BODY_BYTES = 32 * 1024;
const MAX_TOKEN_COUNT = 1_000_000_000_000;
const RETENTION_SECONDS = 30 * 24 * 60 * 60;
const GLOBAL_RATE_LIMIT_SHARDS = 16;

const TASK_TYPES = new Set([
  "feature",
  "bugfix",
  "refactor",
  "mechanical",
  "investigation",
  "unknown",
]);
const RISK_LEVELS = new Set(["low", "medium", "high", "unknown"]);
const OUTCOMES = new Set([
  "completed",
  "blocked",
  "cancelled",
  "failed",
  "unknown",
]);
const CHARACTERISTIC_LEVELS = new Set(["low", "medium", "high"]);
const CONTRACT_CLARITY = new Set(["clear", "mixed", "unclear"]);
const BLOCKER_REASONS = new Set([
  "pending_decision",
  "external_approval",
  "environment_limitation",
  "unresolved_defect",
  "verification_gap",
]);
const DELIVERED_WORK_STATUSES = new Set([
  "accepted",
  "changes_requested",
  "not_reviewed",
]);
const ASSIGNMENT_DISPOSITIONS = new Set(["superseded", "cancelled"]);
const MODELS = new Set([
  "gpt-5.6-sol",
  "gpt-5.6-terra",
  "gpt-5.6-luna",
  "unknown",
]);
const EFFORTS = new Set([
  "low",
  "medium",
  "high",
  "xhigh",
  "max",
  "ultra",
  "unknown",
]);
const VERDICTS = new Set([
  "accepted",
  "changes_requested",
  "blocked",
  "unknown",
]);
const USAGE_REASONS = new Set([
  "no_measurements",
  "unsupported_scope",
  "incomplete_counters",
  "conflicting_measurements",
]);

const TOP_REQUIRED_KEYS = new Set([
  "schema_version",
  "event_id",
  "policy_version",
  "task_type",
  "risk",
  "outcome",
  "worker_count",
  "dependency_count",
  "routes",
  "coordinator_usage",
  "coordinator_usage_reason",
]);
const TOP_OPTIONAL_KEYS = new Set([
  "contract_clarity",
  "coupling",
  "state_concurrency",
  "blocker_reasons",
  "delivered_work_status",
]);
const ROUTE_REQUIRED_KEYS = new Set([
  "model",
  "effort",
  "actual_model",
  "actual_effort",
  "functional_corrections",
  "quality_corrections",
  "unclassified_corrections",
  "final_verdict",
  "usage",
  "usage_reason",
]);
const ROUTE_OPTIONAL_KEYS = new Set(["correction_rounds", "assignment_disposition"]);
const USAGE_KEYS = new Set([
  "input_tokens",
  "cached_input_tokens",
  "output_tokens",
  "reasoning_output_tokens",
]);

const UUID_V4 = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;
const SEMVER = /^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$/;

class BodyTooLargeError extends Error {}

function isObject(value) {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function hasExactKeys(value, required, optional = new Set()) {
  if (!isObject(value)) return false;
  const keys = Object.keys(value);
  if (keys.length < required.size || keys.length > required.size + optional.size) {
    return false;
  }
  for (const key of required) {
    if (!Object.hasOwn(value, key)) return false;
  }
  for (const key of keys) {
    if (!required.has(key) && !optional.has(key)) return false;
  }
  return true;
}

function isIntegerInRange(value, maximum) {
  return Number.isSafeInteger(value) && value >= 0 && value <= maximum;
}

function validateUsage(usage) {
  if (!hasExactKeys(usage, USAGE_KEYS)) return false;
  for (const key of USAGE_KEYS) {
    if (!isIntegerInRange(usage[key], MAX_TOKEN_COUNT)) return false;
  }
  return (
    usage.cached_input_tokens <= usage.input_tokens &&
    usage.reasoning_output_tokens <= usage.output_tokens
  );
}

function validateUsagePair(usage, reason) {
  if (usage === null) return USAGE_REASONS.has(reason);
  return reason === null && validateUsage(usage);
}

function validateRoute(route) {
  if (!hasExactKeys(route, ROUTE_REQUIRED_KEYS, ROUTE_OPTIONAL_KEYS)) return false;
  if (!MODELS.has(route.model) || !EFFORTS.has(route.effort)) return false;
  if (route.actual_model !== null && !MODELS.has(route.actual_model)) return false;
  if (route.actual_effort !== null && !EFFORTS.has(route.actual_effort)) return false;
  if (!isIntegerInRange(route.functional_corrections, 1_000)) return false;
  if (!isIntegerInRange(route.quality_corrections, 1_000)) return false;
  if (!isIntegerInRange(route.unclassified_corrections, 1_000)) return false;
  if (Object.hasOwn(route, "correction_rounds")) {
    const minimumRounds = Math.max(
      route.functional_corrections,
      route.quality_corrections,
    ) + route.unclassified_corrections;
    const maximumRounds = route.functional_corrections
      + route.quality_corrections
      + route.unclassified_corrections;
    if (
      !isIntegerInRange(route.correction_rounds, 1_000) ||
      route.correction_rounds < minimumRounds ||
      route.correction_rounds > maximumRounds
    ) return false;
  }
  if (!VERDICTS.has(route.final_verdict)) return false;
  if (
    Object.hasOwn(route, "assignment_disposition") &&
    !ASSIGNMENT_DISPOSITIONS.has(route.assignment_disposition)
  ) return false;
  return validateUsagePair(route.usage, route.usage_reason);
}

export function validateTelemetryEvent(value) {
  if (!hasExactKeys(value, TOP_REQUIRED_KEYS, TOP_OPTIONAL_KEYS)) return false;
  if (value.schema_version !== 1) return false;
  if (typeof value.event_id !== "string" || !UUID_V4.test(value.event_id)) return false;
  if (
    value.policy_version !== null &&
    (typeof value.policy_version !== "string" ||
      value.policy_version.length > 32 ||
      !SEMVER.test(value.policy_version))
  ) {
    return false;
  }
  if (!TASK_TYPES.has(value.task_type)) return false;
  if (!RISK_LEVELS.has(value.risk)) return false;
  if (!OUTCOMES.has(value.outcome)) return false;
  if (!isIntegerInRange(value.worker_count, 64)) return false;
  if (
    value.dependency_count !== null &&
    (!isIntegerInRange(value.dependency_count, 4_096) ||
      value.dependency_count > (value.worker_count * (value.worker_count - 1)) / 2)
  ) {
    return false;
  }
  if (!Array.isArray(value.routes) || value.routes.length > 64) return false;
  if (value.routes.length !== value.worker_count) return false;
  if (!value.routes.every(validateRoute)) return false;
  if (!validateUsagePair(value.coordinator_usage, value.coordinator_usage_reason)) {
    return false;
  }
  if (
    Object.hasOwn(value, "contract_clarity") &&
    !CONTRACT_CLARITY.has(value.contract_clarity)
  ) {
    return false;
  }
  if (Object.hasOwn(value, "coupling") && !CHARACTERISTIC_LEVELS.has(value.coupling)) {
    return false;
  }
  if (
    Object.hasOwn(value, "state_concurrency") &&
    !CHARACTERISTIC_LEVELS.has(value.state_concurrency)
  ) {
    return false;
  }
  if (Object.hasOwn(value, "blocker_reasons")) {
    if (
      !Array.isArray(value.blocker_reasons) ||
      value.blocker_reasons.some((reason) => !BLOCKER_REASONS.has(reason)) ||
      new Set(value.blocker_reasons).size !== value.blocker_reasons.length ||
      (value.blocker_reasons.length > 0 && value.outcome !== "blocked")
    ) {
      return false;
    }
  }
  if (
    Object.hasOwn(value, "delivered_work_status") &&
    !DELIVERED_WORK_STATUSES.has(value.delivered_work_status)
  ) {
    return false;
  }
  return true;
}

export function canonicalStringify(value) {
  if (Array.isArray(value)) {
    return `[${value.map(canonicalStringify).join(",")}]`;
  }
  if (isObject(value)) {
    return `{${Object.keys(value)
      .sort()
      .map((key) => `${JSON.stringify(key)}:${canonicalStringify(value[key])}`)
      .join(",")}}`;
  }
  return JSON.stringify(value);
}

async function sha256Hex(value) {
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(value));
  return [...new Uint8Array(digest)]
    .map((byte) => byte.toString(16).padStart(2, "0"))
    .join("");
}

async function readBoundedJson(request) {
  const declaredLength = request.headers.get("content-length");
  if (
    declaredLength !== null &&
    /^[0-9]+$/.test(declaredLength) &&
    Number(declaredLength) > MAX_BODY_BYTES
  ) {
    throw new BodyTooLargeError();
  }
  if (request.body === null) return null;

  const reader = request.body.getReader();
  const chunks = [];
  let total = 0;
  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      total += value.byteLength;
      if (total > MAX_BODY_BYTES) {
        await reader.cancel();
        throw new BodyTooLargeError();
      }
      chunks.push(value);
    }
  } finally {
    reader.releaseLock();
  }

  const bytes = new Uint8Array(total);
  let offset = 0;
  for (const chunk of chunks) {
    bytes.set(chunk, offset);
    offset += chunk.byteLength;
  }
  const text = new TextDecoder("utf-8", { fatal: true }).decode(bytes);
  return JSON.parse(text);
}

function jsonResponse(body, status = 200, extraHeaders = {}) {
  return Response.json(body, {
    status,
    headers: {
      "Cache-Control": "no-store",
      "X-Content-Type-Options": "nosniff",
      ...extraHeaders,
    },
  });
}

function errorResponse(code, status, extraHeaders) {
  return jsonResponse({ ok: false, error: code }, status, extraHeaders);
}

async function rateLimitResponse(request, env) {
  const clientIp = request.headers.get("CF-Connecting-IP") ?? "unavailable";
  try {
    const ipHash = await sha256Hex(clientIp);
    const perIp = await env.RATE_LIMITER.limit({ key: `ip:${ipHash}` });
    if (!perIp.success) {
      return errorResponse("rate_limited", 429, { "Retry-After": "60" });
    }

    // Sixteen independently limited shards provide an approximate 160/minute
    // per-location aggregate ceiling while retaining the required 10/minute IP limit.
    const shard = Number.parseInt(ipHash.slice(0, 2), 16) % GLOBAL_RATE_LIMIT_SHARDS;
    const aggregate = await env.RATE_LIMITER.limit({ key: `aggregate:${shard}` });
    if (!aggregate.success) {
      return errorResponse("rate_limited", 429, { "Retry-After": "60" });
    }
    return null;
  } catch {
    return errorResponse("rate_limiter_unavailable", 503);
  }
}

async function storeEvent(event, env) {
  const payloadJson = canonicalStringify(event);
  const payloadHash = await sha256Hex(payloadJson);
  const ingestedAt = Math.floor(Date.now() / 1_000);

  const insertResult = await env.DB.prepare(
    "INSERT OR IGNORE INTO events (event_id, payload_json, payload_sha256, ingested_at) VALUES (?1, ?2, ?3, ?4)",
  )
    .bind(event.event_id, payloadJson, payloadHash, ingestedAt)
    .run();

  if (insertResult.meta?.changes === 1) return "stored";

  const existing = await env.DB.prepare(
    "SELECT payload_json, payload_sha256 FROM events WHERE event_id = ?1",
  )
    .bind(event.event_id)
    .first();
  if (
    existing !== null &&
    existing.payload_sha256 === payloadHash &&
    existing.payload_json === payloadJson
  ) {
    return "duplicate";
  }
  return "conflict";
}

async function postEvent(request, env) {
  const contentType = request.headers.get("content-type");
  if (contentType === null || contentType.split(";", 1)[0].trim().toLowerCase() !== "application/json") {
    return errorResponse("content_type_must_be_application_json", 415);
  }

  const limited = await rateLimitResponse(request, env);
  if (limited !== null) return limited;

  let event;
  try {
    event = await readBoundedJson(request);
  } catch (error) {
    if (error instanceof BodyTooLargeError) return errorResponse("body_too_large", 413);
    return errorResponse("invalid_json", 400);
  }
  if (!validateTelemetryEvent(event)) return errorResponse("invalid_event", 400);

  try {
    const result = await storeEvent(event, env);
    if (result === "conflict") return errorResponse("event_id_conflict", 409);
    return jsonResponse({ ok: true });
  } catch {
    return errorResponse("storage_unavailable", 503);
  }
}

const PRIVACY_DISCLOSURE = {
  service: "Astra Helm opt-in telemetry receiver",
  schema_version: 1,
  disclosure_version: "5",
  operator: "This endpoint is operated by Theoria Interactive, owner of the Astra Helm repository.",
  purpose: "Aggregate categorical routing outcomes to improve Astra Helm defaults.",
  trust: "Events are untrusted, opt-in self-reports; the server cannot prove user consent.",
  accepted_fields: {
    required: [
      "schema_version",
      "event_id",
      "policy_version",
      "task_type",
      "risk",
      "outcome",
      "worker_count",
      "dependency_count",
      "routes",
      "coordinator_usage",
      "coordinator_usage_reason",
    ],
    optional: [
      "contract_clarity",
      "coupling",
      "state_concurrency",
      "blocker_reasons",
      "delivered_work_status",
    ],
    route: [...ROUTE_REQUIRED_KEYS, ...ROUTE_OPTIONAL_KEYS],
    route_required: [...ROUTE_REQUIRED_KEYS],
    route_optional: [...ROUTE_OPTIONAL_KEYS],
    usage: [...USAGE_KEYS],
    blocker_reasons: [...BLOCKER_REASONS],
    delivered_work_status: [...DELIVERED_WORK_STATUSES],
    assignment_disposition: [...ASSIGNMENT_DISPOSITIONS],
  },
  excluded_data: [
    "prompts",
    "project names or identifiers",
    "file or directory paths",
    "source code or source text",
    "IP addresses",
    "User-Agent values",
  ],
  application_storage: "Only validated allowlist payloads, their event IDs and hashes, and server ingestion timestamps are stored.",
  network_metadata: "An IP address is used transiently to derive rate-limit keys and is not persisted by this application. Cloudflare may process connection metadata under its separate policies.",
  observability_enabled: false,
  max_body_bytes: MAX_BODY_BYTES,
  active_retention_days: 30,
  cleanup_interval_days: 1,
  maximum_deletion_lag_days: 1,
  provider_recovery_history_days: { free_plan: 7, paid_plan: 30 },
  active_retention: "Rows are eligible for deletion after 30 days. Daily UTC cleanup can add up to one day of lag.",
  recovery_history: "After active deletion, D1 Time Travel recovery history may retain deleted data for up to 30 additional days on paid plans (7 days on free plans), under Cloudflare's provider policy.",
  rate_limits: "Approximately 10 events per minute per IP and 160 events per minute per Cloudflare location; enforcement is intentionally approximate.",
};

export async function handleScheduled(controller, env) {
  const cutoff = Math.floor(controller.scheduledTime / 1_000) - RETENTION_SECONDS;
  await env.DB.prepare("DELETE FROM events WHERE ingested_at < ?1").bind(cutoff).run();
}

export default {
  async fetch(request, env) {
    try {
      const url = new URL(request.url);
      // Preserve legacy paths for installed clients while mounting the new address.
      const path = url.pathname === "/astrahelm" || url.pathname === "/astrahelm/"
        ? "/privacy"
        : url.pathname.startsWith("/astrahelm/")
          ? url.pathname.slice("/astrahelm".length)
          : url.pathname;
      if (path === "/health") {
        if (request.method !== "GET") {
          return errorResponse("method_not_allowed", 405, { Allow: "GET" });
        }
        return jsonResponse({ ok: true });
      }
      if (path === "/privacy") {
        if (request.method !== "GET") {
          return errorResponse("method_not_allowed", 405, { Allow: "GET" });
        }
        return jsonResponse(PRIVACY_DISCLOSURE);
      }
      if (path === "/v1/events") {
        if (request.method !== "POST") {
          return errorResponse("method_not_allowed", 405, { Allow: "POST" });
        }
        return await postEvent(request, env);
      }
      return errorResponse("not_found", 404);
    } catch {
      return errorResponse("internal_error", 500);
    }
  },

  async scheduled(controller, env) {
    await handleScheduled(controller, env);
  },
};
