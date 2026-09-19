#!/usr/bin/env python3
"""Calculate a local, sourced API-equivalent cost receipt.

The calculator intentionally does not read Astra Helm journals, call a network
service, or ship prices.  Its inputs are an explicit usage export and a dated,
versioned pricing snapshot supplied by the caller.
"""

from __future__ import annotations

import argparse
import datetime as dt
from decimal import Decimal, InvalidOperation
import json
from pathlib import Path
import sys


SCHEMA_VERSION = 1
BILLABLE_COUNTERS = ("input_tokens", "cached_input_tokens", "output_tokens")
ALL_COUNTERS = BILLABLE_COUNTERS + ("reasoning_output_tokens",)
RATE_FIELDS = {
    "input_tokens": "input_usd_per_million",
    "cached_input_tokens": "cached_input_usd_per_million",
    "output_tokens": "output_usd_per_million",
}
class ReceiptError(ValueError):
    """An input is malformed, internally contradictory, or unsupported."""


def error(message: str, code: str = "invalid_input") -> ReceiptError:
    return ReceiptError(f"{code}: {message}")


def reject_unknown_fields(value: dict, allowed: set[str], label: str) -> None:
    unexpected = sorted(set(value) - allowed)
    if unexpected:
        raise error(f"{label} contains unsupported field(s): {', '.join(unexpected)}")


def read_object(path: str, label: str) -> dict:
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise error(f"cannot read {label}: {exc}") from exc
    if not isinstance(value, dict):
        raise error(f"{label} must be a JSON object")
    return value


def require_string(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise error(f"{label} must be a non-empty string")
    return value


def require_bool(value: object, label: str) -> bool:
    if not isinstance(value, bool):
        raise error(f"{label} must be true or false")
    return value


def require_iso_date(value: object, label: str, *, cutoff: bool = False) -> str:
    text = require_string(value, label)
    candidate = text[:-1] + "+00:00" if text.endswith("Z") else text
    try:
        if cutoff:
            if "T" not in candidate or dt.datetime.fromisoformat(candidate).tzinfo is None:
                raise ValueError
        else:
            dt.datetime.fromisoformat(candidate)
    except ValueError as exc:
        expectation = "an ISO-8601 timestamp with a timezone" if cutoff else "an ISO-8601 date or timestamp"
        raise error(f"{label} must be {expectation}") from exc
    return text


def require_count(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise error(f"{label} must be a nonnegative integer (booleans are not counts)")
    return value


def require_decimal(value: object, label: str) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (str, int, float, Decimal)):
        raise error(f"{label} must be a nonnegative finite decimal")
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise error(f"{label} must be a nonnegative finite decimal") from exc
    if not number.is_finite() or number < 0:
        raise error(f"{label} must be a nonnegative finite decimal")
    return number


def decimal_text(value: Decimal) -> str:
    text = format(value, "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


def validate_pricing(pricing: dict) -> dict:
    reject_unknown_fields(pricing, {"schema_version", "snapshot", "models"}, "pricing")
    if pricing.get("schema_version") != SCHEMA_VERSION:
        raise error(f"pricing.schema_version must be {SCHEMA_VERSION}")
    snapshot = pricing.get("snapshot")
    if not isinstance(snapshot, dict):
        raise error("pricing.snapshot must be an object")
    reject_unknown_fields(snapshot, {"version", "as_of", "source_url"}, "pricing.snapshot")
    require_string(snapshot.get("version"), "pricing.snapshot.version")
    require_iso_date(snapshot.get("as_of"), "pricing.snapshot.as_of")
    require_string(snapshot.get("source_url"), "pricing.snapshot.source_url")
    source_url = snapshot["source_url"]
    if not source_url.startswith(("https://", "http://")):
        raise error("pricing.snapshot.source_url must be an http(s) URL")
    models = pricing.get("models")
    if not isinstance(models, dict):
        raise error("pricing.models must be an object")
    parsed_models: dict[str, dict[str, Decimal]] = {}
    for model, rates in models.items():
        require_string(model, "pricing.models key")
        if not isinstance(rates, dict):
            raise error(f"pricing.models.{model} must be an object")
        reject_unknown_fields(rates, set(RATE_FIELDS.values()), f"pricing.models.{model}")
        parsed: dict[str, Decimal] = {}
        for field in set(RATE_FIELDS.values()):
            if field in rates and rates[field] is not None:
                parsed[field] = require_decimal(rates[field], f"pricing.models.{model}.{field}")
        parsed_models[model] = parsed
    return {"snapshot": snapshot, "models": parsed_models}


def validate_receipt_input(receipt: dict) -> dict:
    reject_unknown_fields(receipt, {"schema_version", "scope", "agent_roster", "calls", "astra_repricing"}, "input")
    if receipt.get("schema_version") != SCHEMA_VERSION:
        raise error(f"input.schema_version must be {SCHEMA_VERSION}")
    scope = receipt.get("scope")
    if not isinstance(scope, dict):
        raise error("input.scope must be an object")
    reject_unknown_fields(scope, {"id", "description", "cutoff", "expected_call_ids", "completeness_assertion"}, "input.scope")
    for name in ("id", "description"):
        require_string(scope.get(name), f"input.scope.{name}")
    require_iso_date(scope.get("cutoff"), "input.scope.cutoff", cutoff=True)
    assertion = scope.get("completeness_assertion")
    if not isinstance(assertion, dict):
        raise error("input.scope.completeness_assertion must be an object")
    reject_unknown_fields(assertion, {"complete", "basis"}, "input.scope.completeness_assertion")
    require_bool(assertion.get("complete"), "input.scope.completeness_assertion.complete")
    require_string(assertion.get("basis"), "input.scope.completeness_assertion.basis")
    expected = scope.get("expected_call_ids")
    if not isinstance(expected, list) or not expected:
        raise error("input.scope.expected_call_ids must be a non-empty array")
    expected_ids = [require_string(value, "input.scope.expected_call_ids item") for value in expected]
    if len(set(expected_ids)) != len(expected_ids):
        raise error("input.scope.expected_call_ids contains duplicates")

    roster = receipt.get("agent_roster")
    if not isinstance(roster, list) or not roster:
        raise error("input.agent_roster must be a non-empty array")
    roster_pairs = set()
    roster_ids = set()
    for index, member in enumerate(roster):
        if not isinstance(member, dict):
            raise error(f"input.agent_roster[{index}] must be an object")
        reject_unknown_fields(member, {"id", "role"}, f"input.agent_roster[{index}]")
        pair = (require_string(member.get("id"), f"input.agent_roster[{index}].id"),
                require_string(member.get("role"), f"input.agent_roster[{index}].role"))
        if pair[0] in roster_ids:
            raise error("input.agent_roster contains duplicate agent id")
        roster_pairs.add(pair)
        roster_ids.add(pair[0])

    calls = receipt.get("calls")
    if not isinstance(calls, list):
        raise error("input.calls must be an array")
    parsed_calls = []
    seen_ids = set()
    for index, call in enumerate(calls):
        if not isinstance(call, dict):
            raise error(f"input.calls[{index}] must be an object")
        reject_unknown_fields(call, {"call_id", "agent", "model", "regime", "usage"}, f"input.calls[{index}]")
        call_id = require_string(call.get("call_id"), f"input.calls[{index}].call_id")
        if call_id in seen_ids:
            raise error(f"duplicate atomic call_id: {call_id}")
        seen_ids.add(call_id)
        if call_id not in expected_ids:
            raise error(f"input.calls[{index}].call_id is outside scope.expected_call_ids")
        agent = call.get("agent")
        if not isinstance(agent, dict):
            raise error(f"input.calls[{index}].agent must be an object")
        reject_unknown_fields(agent, {"id", "role"}, f"input.calls[{index}].agent")
        pair = (require_string(agent.get("id"), f"input.calls[{index}].agent.id"),
                require_string(agent.get("role"), f"input.calls[{index}].agent.role"))
        if pair not in roster_pairs:
            raise error(f"input.calls[{index}].agent is not in input.agent_roster")
        model = require_string(call.get("model"), f"input.calls[{index}].model")
        regime = validate_regime(call.get("regime"), f"input.calls[{index}].regime")
        usage = validate_usage(call.get("usage"), f"input.calls[{index}].usage")
        parsed_calls.append({"call_id": call_id, "agent": {"id": pair[0], "role": pair[1]},
                             "model": model, "regime": regime, "usage": usage})

    repricing = receipt.get("astra_repricing")
    if repricing is not None:
        if not isinstance(repricing, dict):
            raise error("input.astra_repricing must be an object or null")
        reject_unknown_fields(repricing, {"model"}, "input.astra_repricing")
        repricing = {"model": require_string(repricing.get("model"), "input.astra_repricing.model")}
    return {"scope": scope, "expected_ids": expected_ids, "roster": roster, "calls": parsed_calls, "repricing": repricing}


def validate_regime(regime: object, label: str) -> dict:
    if regime is None:
        raise error(f"{label} is required; explicitly state standard eligibility and whether it was observed or assumed")
    if not isinstance(regime, dict):
        raise error(f"{label} must be an object when supplied")
    reject_unknown_fields(regime, {"mode", "source"}, label)
    if regime.get("mode") != "standard":
        raise error(f"{label}.mode must be 'standard'; tiered, batch, cache-write, and context pricing are unsupported")
    source = require_string(regime.get("source"), f"{label}.source")
    if source not in {"observed", "assumed"}:
        raise error(f"{label}.source must be 'observed' or 'assumed'")
    return {"mode": "standard", "source": source}


def validate_usage(usage: object, label: str) -> dict | None:
    if usage is None:
        return None
    if not isinstance(usage, dict):
        raise error(f"{label} must be an object or null")
    for forbidden in ("cumulative", "parent_inclusive", "aggregate", "includes_child_calls"):
        if forbidden in usage:
            raise error(f"{label}.{forbidden} is not allowed; only atomic per-call usage is accepted")
    reject_unknown_fields(usage, {"source", "scope", *ALL_COUNTERS}, label)
    require_string(usage.get("source"), f"{label}.source")
    if usage.get("scope") != "atomic_call":
        raise error(f"{label}.scope must be 'atomic_call'; cumulative and parent-inclusive aggregates are rejected")
    parsed = {"source": usage["source"], "scope": "atomic_call"}
    for counter in ALL_COUNTERS:
        if counter in usage and usage[counter] is not None:
            parsed[counter] = require_count(usage[counter], f"{label}.{counter}")
    if ("cached_input_tokens" in parsed and "input_tokens" in parsed
            and parsed["cached_input_tokens"] > parsed["input_tokens"]):
        raise error(f"{label}.cached_input_tokens cannot exceed input_tokens")
    if ("reasoning_output_tokens" in parsed and "output_tokens" in parsed
            and parsed["reasoning_output_tokens"] > parsed["output_tokens"]):
        raise error(f"{label}.reasoning_output_tokens cannot exceed output_tokens")
    return parsed


def price_usage(usage: dict | None, rates: dict[str, Decimal] | None) -> tuple[Decimal | None, str | None]:
    if usage is None:
        return None, "usage_unavailable"
    missing_counts = [counter for counter in BILLABLE_COUNTERS if counter not in usage]
    if missing_counts:
        return None, "missing_usage:" + ",".join(missing_counts)
    if rates is None:
        return None, "model_not_in_pricing_snapshot"
    missing_rates = [RATE_FIELDS[counter] for counter in BILLABLE_COUNTERS if RATE_FIELDS[counter] not in rates]
    if missing_rates:
        return None, "missing_rates:" + ",".join(missing_rates)
    uncached_input = usage["input_tokens"] - usage["cached_input_tokens"]
    total = (
        Decimal(uncached_input) * rates["input_usd_per_million"] / Decimal(1_000_000)
        + Decimal(usage["cached_input_tokens"]) * rates["cached_input_usd_per_million"] / Decimal(1_000_000)
        + Decimal(usage["output_tokens"]) * rates["output_usd_per_million"] / Decimal(1_000_000)
    )
    return total, None


def usage_gap(usage: dict | None) -> str | None:
    if usage is None:
        return "usage_unavailable"
    missing = [counter for counter in BILLABLE_COUNTERS if counter not in usage]
    return "missing_usage:" + ",".join(missing) if missing else None


def usage_total(calls: list[dict]) -> dict:
    result = {}
    for counter in ALL_COUNTERS:
        values = [call["usage"].get(counter) for call in calls]
        result[counter] = sum(values) if values and all(value is not None for value in values) else None
    return result


def calculate(receipt: dict, pricing: dict) -> dict:
    parsed_pricing = validate_pricing(pricing)
    parsed = validate_receipt_input(receipt)
    calls_by_id = {call["call_id"]: call for call in parsed["calls"]}
    priceable, unavailable, coverage_gaps, observed_calls = [], [], [], []
    for call_id in parsed["expected_ids"]:
        call = calls_by_id.get(call_id)
        if call is None:
            gap = {"call_id": call_id, "reason": "call_record_missing"}
            unavailable.append(gap)
            coverage_gaps.append(gap)
            continue
        usage_reason = usage_gap(call["usage"])
        if usage_reason:
            gap = {"call_id": call_id, "reason": usage_reason}
            unavailable.append(gap)
            coverage_gaps.append(gap)
            continue
        observed_calls.append(call)
        cost, reason = price_usage(call["usage"], parsed_pricing["models"].get(call["model"]))
        if cost is None:
            unavailable.append({"call_id": call_id, "reason": reason})
        else:
            call = dict(call)
            call["cost"] = cost
            priceable.append(call)
    subset_cost = sum((call["cost"] for call in priceable), Decimal(0)) if priceable else None
    assertion = parsed["scope"]["completeness_assertion"]
    called_agent_ids = {call["agent"]["id"] for call in parsed["calls"]}
    unavailable_agents = [
        {"id": member["id"], "role": member["role"], "reason": "agent_has_no_call_record"}
        for member in parsed["roster"] if member["id"] not in called_agent_ids
    ]
    if unavailable_agents:
        coverage_gaps.extend(unavailable_agents)
    coverage_complete = assertion["complete"] and not coverage_gaps
    full_complete = coverage_complete and not unavailable
    if full_complete:
        status = "complete"
    elif priceable:
        status = "partial"
    else:
        status = "unavailable"
    result = {
        "schema_version": SCHEMA_VERSION,
        "status": status,
        "pricing_snapshot": parsed_pricing["snapshot"],
        "scope": {
            "id": parsed["scope"]["id"], "description": parsed["scope"]["description"],
            "cutoff": parsed["scope"]["cutoff"], "completeness_assertion": assertion,
            "expected_call_ids": parsed["expected_ids"],
            "coverage_complete": coverage_complete,
            "unavailable_calls": unavailable,
            "unavailable_agents": unavailable_agents,
        },
        "observed_subset": {
            "status": "available" if priceable else "unavailable",
            "call_ids": [call["call_id"] for call in priceable],
            "usage": usage_total(priceable) if priceable else None,
            "cost_usd": decimal_text(subset_cost) if subset_cost is not None else None,
        },
        "full_scope_estimate": ({"status": "available", "call_ids": parsed["expected_ids"],
                                 "cost_usd": decimal_text(subset_cost)} if full_complete else
                                {"status": "unavailable", "cost_usd": None,
                                 "reason": "coverage is incomplete, unobserved, or lacks rates"}),
        "limitations": [
            "This is a local API-equivalent calculation from caller-supplied prices and sourced usage, not an invoice.",
            "It does not measure Codex subscription charges, account quotas, or any all-Astra savings.",
            "Journal aggregates and parent-inclusive counters are intentionally not read or accepted as provenance.",
        ],
        "assumptions": [
            {"call_id": call["call_id"], "kind": "standard_regime_eligibility", "value": "standard"}
            for call in parsed["calls"] if call["regime"]["source"] == "assumed"
        ],
    }
    if parsed["repricing"] is not None:
        target = parsed["repricing"]["model"]
        if not coverage_complete:
            result["astra_same_token_repricing"] = {
                "status": "unavailable", "model": target,
                "reason": "requires complete, observed, comparable atomic-call coverage",
                "cost_usd": None,
            }
        else:
            target_costs = [price_usage(call["usage"], parsed_pricing["models"].get(target)) for call in observed_calls]
            missing = [reason for cost, reason in target_costs if cost is None]
            if missing:
                result["astra_same_token_repricing"] = {
                    "status": "unavailable", "model": target,
                    "reason": "target pricing unavailable: " + "; ".join(missing), "cost_usd": None,
                }
            else:
                target_total = sum((cost for cost, _ in target_costs), Decimal(0))
                result["astra_same_token_repricing"] = {
                    "status": "available", "model": target,
                    "basis": "same observed tokens across the complete declared scope",
                    "cost_usd": decimal_text(target_total),
                    "limitation": "A same-token API counterfactual; it does not measure all-Astra savings or subscription costs.",
                }
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Calculate a local sourced API-equivalent cost receipt.")
    parser.add_argument("input", help="receipt input JSON")
    parser.add_argument("--pricing", required=True, help="dated, versioned pricing snapshot JSON")
    args = parser.parse_args(argv)
    try:
        output = calculate(read_object(args.input, "input"), read_object(args.pricing, "pricing"))
    except ReceiptError as exc:
        print(json.dumps({"schema_version": SCHEMA_VERSION, "status": "error",
                          "error": {"code": "invalid_input", "message": str(exc)}}, ensure_ascii=False))
        return 2
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
