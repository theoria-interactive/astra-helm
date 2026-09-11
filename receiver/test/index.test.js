import test from "node:test";
import assert from "node:assert/strict";

import worker, {
  canonicalStringify,
  handleScheduled,
  validateTelemetryEvent,
} from "../src/index.js";

function event(overrides = {}) {
  return {
    schema_version: 1,
    event_id: "01234567-89ab-4cde-8f01-23456789abcd",
    policy_version: "1.2.3",
    task_type: "feature",
    risk: "medium",
    outcome: "completed",
    worker_count: 1,
    dependency_count: 0,
    routes: [
      {
        model: "gpt-5.6-sol",
        effort: "high",
        actual_model: null,
        actual_effort: null,
        functional_corrections: 0,
        quality_corrections: 0,
        unclassified_corrections: 0,
        final_verdict: "accepted",
        usage: {
          input_tokens: 10,
          cached_input_tokens: 0,
          output_tokens: 5,
          reasoning_output_tokens: 0,
        },
        usage_reason: null,
      },
    ],
    coordinator_usage: null,
    coordinator_usage_reason: "no_measurements",
    ...overrides,
  };
}

class MockDatabase {
  constructor() {
    this.rows = new Map();
    this.insertAttempts = 0;
    this.deleteCutoff = null;
    this.failure = null;
  }

  prepare(sql) {
    const database = this;
    return {
      args: [],
      bind(...args) {
        this.args = args;
        return this;
      },
      async run() {
        if (database.failure) throw database.failure;
        if (sql.startsWith("INSERT OR IGNORE")) {
          database.insertAttempts += 1;
          const [eventId, payloadJson, payloadHash, ingestedAt] = this.args;
          if (database.rows.has(eventId)) return { meta: { changes: 0 } };
          database.rows.set(eventId, {
            payload_json: payloadJson,
            payload_sha256: payloadHash,
            ingested_at: ingestedAt,
          });
          return { meta: { changes: 1 } };
        }
        if (sql.startsWith("DELETE FROM events")) {
          [database.deleteCutoff] = this.args;
          return { meta: { changes: 0 } };
        }
        throw new Error("unexpected statement");
      },
      async first() {
        if (database.failure) throw database.failure;
        const [eventId] = this.args;
        return database.rows.get(eventId) ?? null;
      },
    };
  }
}

function envWith({ database = new MockDatabase(), limit } = {}) {
  return {
    DB: database,
    RATE_LIMITER: {
      async limit(input) {
        return limit ? limit(input) : { success: true };
      },
    },
  };
}

function post(body, headers = {}) {
  return new Request("https://telemetry.example/v1/events", {
    method: "POST",
    headers: {
      "content-type": "application/json",
      "CF-Connecting-IP": "192.0.2.10",
      ...headers,
    },
    body: typeof body === "string" || body instanceof ReadableStream ? body : JSON.stringify(body),
    ...(body instanceof ReadableStream ? { duplex: "half" } : {}),
  });
}

test("accepts zeros and contractually nullable values without sentinels", () => {
  const payload = event({
    policy_version: null,
    worker_count: 1,
    dependency_count: null,
    routes: [
      {
        ...event().routes[0],
        usage: null,
        usage_reason: "unsupported_scope",
      },
    ],
  });
  assert.equal(validateTelemetryEvent(payload), true);
  assert.equal(
    validateTelemetryEvent({
      ...payload,
      coordinator_usage_reason: "unknown",
    }),
    false,
  );
  assert.equal(validateTelemetryEvent({ ...payload, policy_version: `${"1".repeat(30)}.1.1` }), false);
});

test("rejects unknown fields recursively and invalid counter relationships", () => {
  const unknownTop = { ...event(), prompt: "do not collect" };
  assert.equal(validateTelemetryEvent(unknownTop), false);

  const nested = event();
  nested.routes[0].usage.source = "untrusted";
  assert.equal(validateTelemetryEvent(nested), false);

  const badCounters = event();
  badCounters.routes[0].usage.cached_input_tokens = 11;
  assert.equal(validateTelemetryEvent(badCounters), false);

  const unsafe = event();
  unsafe.routes[0].usage.input_tokens = 1_000_000_000_001;
  assert.equal(validateTelemetryEvent(unsafe), false);
});

test("requires one route record for each reported worker", () => {
  assert.equal(validateTelemetryEvent(event({ worker_count: 1 })), true);
  assert.equal(validateTelemetryEvent(event({ worker_count: 0, routes: [] })), true);
  assert.equal(validateTelemetryEvent(event({ worker_count: 0 })), false);
  assert.equal(validateTelemetryEvent(event({ worker_count: 2 })), false);
});

test("accepts optional structured outcome metadata while legacy payloads remain valid", () => {
  assert.equal(validateTelemetryEvent(event()), true);
  assert.equal(validateTelemetryEvent(event({ blocker_reasons: [] })), true);
  assert.equal(
    validateTelemetryEvent(event({
      outcome: "blocked",
      blocker_reasons: ["pending_decision", "verification_gap"],
      delivered_work_status: "changes_requested",
    })),
    true,
  );
});

test("rejects malformed, duplicate, unknown, and outcome-inconsistent metadata", () => {
  for (const overrides of [
    { blocker_reasons: "verification_gap" },
    { outcome: "blocked", blocker_reasons: ["private free text"] },
    { outcome: "blocked", blocker_reasons: ["verification_gap", "verification_gap"] },
    { outcome: "blocked", blocker_reasons: [{}] },
    { outcome: "completed", blocker_reasons: ["verification_gap"] },
    { delivered_work_status: "private free text" },
    { delivered_work_status: {} },
  ]) {
    assert.equal(validateTelemetryEvent(event(overrides)), false);
  }
});

test("bounds dependencies to an earlier-dispatch DAG", () => {
  assert.equal(validateTelemetryEvent(event({ dependency_count: 1 })), false);
  assert.equal(
    validateTelemetryEvent(event({ worker_count: 0, routes: [], dependency_count: 1 })),
    false,
  );

  const route = event().routes[0];
  const twoWorkers = event({
    worker_count: 2,
    routes: [route, structuredClone(route)],
    dependency_count: 1,
  });
  assert.equal(validateTelemetryEvent(twoWorkers), true);
  assert.equal(validateTelemetryEvent({ ...twoWorkers, dependency_count: 2 }), false);
});

test("canonical JSON is independent of object key order", () => {
  const original = event();
  const reordered = Object.fromEntries(Object.entries(original).reverse());
  assert.equal(canonicalStringify(original), canonicalStringify(reordered));
});

test("reads the stream with an absolute 32 KiB bound despite content-length", async () => {
  const bytes = new TextEncoder().encode("x".repeat(32 * 1024 + 1));
  const body = new ReadableStream({
    start(controller) {
      controller.enqueue(bytes.subarray(0, 10));
      controller.enqueue(bytes.subarray(10));
      controller.close();
    },
  });
  const response = await worker.fetch(post(body, { "content-length": "1" }), envWith());
  assert.equal(response.status, 413);
  assert.deepEqual(await response.json(), { ok: false, error: "body_too_large" });
});

test("stores once and treats reordered duplicate payload as success", async () => {
  const database = new MockDatabase();
  const env = envWith({ database });
  const payload = event();
  const reordered = Object.fromEntries(Object.entries(payload).reverse());

  const first = await worker.fetch(post(payload), env);
  const second = await worker.fetch(post(reordered), env);

  assert.equal(first.status, 200);
  assert.equal(second.status, 200);
  assert.equal(database.rows.size, 1);
  assert.equal(database.insertAttempts, 2);
});

test("rejects a reused event ID with different canonical payload", async () => {
  const env = envWith();
  assert.equal((await worker.fetch(post(event()), env)).status, 200);
  const response = await worker.fetch(post(event({ outcome: "failed" })), env);
  assert.equal(response.status, 409);
  assert.deepEqual(await response.json(), { ok: false, error: "event_id_conflict" });
});

test("does not expose storage errors", async () => {
  const database = new MockDatabase();
  database.failure = new Error("raw sqlite details and payload must stay private");
  const response = await worker.fetch(post(event()), envWith({ database }));
  const text = await response.text();
  assert.equal(response.status, 503);
  assert.doesNotMatch(text, /sqlite|payload|private/i);
  assert.match(text, /storage_unavailable/);
});

test("enforces per-IP and aggregate rate limits before D1", async () => {
  const database = new MockDatabase();
  const keys = [];
  const response = await worker.fetch(
    post(event()),
    envWith({
      database,
      limit({ key }) {
        keys.push(key);
        return { success: keys.length === 1 };
      },
    }),
  );
  assert.equal(response.status, 429);
  assert.equal(keys.length, 2);
  assert.match(keys[0], /^ip:[0-9a-f]{64}$/);
  assert.match(keys[1], /^aggregate:(?:[0-9]|1[0-5])$/);
  assert.equal(database.insertAttempts, 0);
});

test("fails closed when the rate limiter fails and does not write", async () => {
  const database = new MockDatabase();
  const response = await worker.fetch(
    post(event()),
    envWith({
      database,
      limit() {
        throw new Error("rate service internals");
      },
    }),
  );
  const text = await response.text();
  assert.equal(response.status, 503);
  assert.match(text, /rate_limiter_unavailable/);
  assert.doesNotMatch(text, /internals/);
  assert.equal(database.insertAttempts, 0);
});

test("health and privacy expose no database rows", async () => {
  const database = new MockDatabase();
  database.rows.set("private", { payload_json: "secret" });
  const env = envWith({ database });
  const health = await worker.fetch(new Request("https://telemetry.example/health"), env);
  const privacy = await worker.fetch(new Request("https://telemetry.example/privacy"), env);
  assert.deepEqual(await health.json(), { ok: true });
  assert.doesNotMatch(await privacy.text(), /secret/);
  const disclosure = await (await worker.fetch(
    new Request("https://telemetry.example/privacy"), env,
  )).json();
  assert.equal(disclosure.disclosure_version, "3");
  assert.deepEqual(
    new Set(disclosure.accepted_fields.blocker_reasons),
    new Set(["pending_decision", "external_approval", "environment_limitation", "unresolved_defect", "verification_gap"]),
  );
  assert.equal(database.insertAttempts, 0);
});

test("scheduled cleanup deletes rows older than 30 days", async () => {
  const database = new MockDatabase();
  const scheduledTime = Date.UTC(2026, 8, 10, 3, 17, 0);
  await handleScheduled({ scheduledTime }, { DB: database });
  assert.equal(database.deleteCutoff, scheduledTime / 1_000 - 30 * 24 * 60 * 60);
});

test("mounted routes serve disclosure and health without exposing stored events", async () => {
  const env = envWith();
  for (const path of ["/astrahelm", "/astrahelm/", "/astrahelm/privacy"]) {
    const response = await worker.fetch(new Request(`https://telemetry.example${path}`), env);
    assert.equal(response.status, 200);
    assert.match((await response.json()).operator, /Theoria Interactive/);
  }
  const health = await worker.fetch(new Request("https://telemetry.example/astrahelm/health"), env);
  assert.deepEqual(await health.json(), { ok: true });
  for (const path of ["/astrahelm-other/health", "/astrahelm/events", "/astrahelm/v1/events/"]) {
    assert.equal((await worker.fetch(new Request(`https://telemetry.example${path}`), env)).status, 404);
  }
});

test("mounted intake retains validation, storage and method restrictions", async () => {
  const database = new MockDatabase();
  const env = envWith({ database });
  const url = "https://telemetry.example/astrahelm/v1/events";
  const response = await worker.fetch(new Request(url, {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(event()),
  }), env);
  assert.equal(response.status, 200);
  assert.equal(database.rows.size, 1);
  assert.equal((await worker.fetch(new Request(url), env)).status, 405);
  const invalid = await worker.fetch(new Request(url, {
    method: "POST", headers: { "Content-Type": "application/json" }, body: '{}',
  }), env);
  assert.equal(invalid.status, 400);
  assert.equal(database.rows.size, 1);
});
