# Optional local cost accounting

`scripts/cost_receipt.py` calculates a local **API-equivalent** receipt from two files you supply. It never reads journals, transcripts, account quotas, or subscription billing, and it does not contact a network service. It does not include price data: provide a dated, versioned snapshot with its source URL for the exact rates you want applied.

Run it with Python 3:

```text
python3 skills/astra-helm/scripts/cost_receipt.py INPUT.json --pricing PRICING.json
```

The input must name the bounded scope, a cutoff, the expected atomic call IDs, and an explicit completeness assertion. Each call records a rostered agent and role, a model, a required `regime`, and sourced usage for exactly one atomic call. The regime is exactly `{"mode":"standard","source":"observed"}` or `{"mode":"standard","source":"assumed"}`. It never defaults a missing regime. Assumed standard eligibility remains in the output's `assumptions` array.

The schema is deliberately closed: input root keys are `schema_version`, `scope`, `agent_roster`, `calls`, and optional `astra_repricing`; call keys are `call_id`, `agent`, `model`, `regime`, and `usage`; a usage object has only `source`, `scope`, and the four token counters. Pricing root keys are `schema_version`, `snapshot`, and `models`; snapshot keys are `version`, `as_of`, and `source_url`; each model has only the three fixed USD-per-million rate keys shown below. Unknown fields are rejected, including service tiers, aggregation metadata, estimated-usage markers, currency declarations, and context metadata, because this calculator cannot establish whether a fixed standard rate applies to them.

`usage: null` means the call is known but unavailable; a missing expected call record means its coverage is unavailable. A null token counter or rate has the same meaning as an absent one: unknown, never zero. The calculator accepts only `atomic_call` usage. It rejects duplicate IDs, cumulative or parent-inclusive counters, negative or boolean token counts, cached input greater than input, reasoning output greater than output, and unsupported batch, tier, cache-write, or context regimes. A declared roster member without a call record also leaves the scope incomplete.

`input_tokens` includes cached tokens; `cached_input_tokens` is priced at the cached-input rate and is not charged again at the uncached-input rate. `reasoning_output_tokens` is recorded for provenance and must be a subset of output, but it is not charged a second time.

Use a distinct pricing file whenever the applicable price schedule changes. The snapshot must have `version`, `as_of`, and an HTTP(S) `source_url`. Rates are fixed per model and USD per million tokens; they must be applicable to the declared standard regime. A model may be absent, and an individual rate may be absent or `null`, when it is unknown: the result then preserves that gap instead of making up a cost. The calculator has no hardcoded context threshold or alternate-price schedule.

This full example is copyable. **Every model name, source URL, date, and rate below is fictional and illustrative; do not use these values as a price quote.**

`receipt-input.json`:

```json
{
  "schema_version": 1,
  "scope": {
    "id": "example-task-2026-09-19",
    "description": "Implementation and review calls observed before the stated cutoff",
    "cutoff": "2026-09-19T16:00:00Z",
    "expected_call_ids": ["worker-turn-1", "review-turn-1"],
    "completeness_assertion": {
      "complete": true,
      "basis": "The host runtime export listed these two and no other calls in this scope before the cutoff."
    }
  },
  "agent_roster": [
    {"id": "worker-1", "role": "implementer"},
    {"id": "coordinator-1", "role": "reviewer"}
  ],
  "calls": [
    {
      "call_id": "worker-turn-1",
      "agent": {"id": "worker-1", "role": "implementer"},
      "model": "fictional-worker-v1",
      "regime": {"mode": "standard", "source": "observed"},
      "usage": {
        "source": "host runtime result for worker turn 1",
        "scope": "atomic_call",
        "input_tokens": 120000,
        "cached_input_tokens": 30000,
        "output_tokens": 8000,
        "reasoning_output_tokens": 4000
      }
    },
    {
      "call_id": "review-turn-1",
      "agent": {"id": "coordinator-1", "role": "reviewer"},
      "model": "fictional-coordinator-v1",
      "regime": {"mode": "standard", "source": "observed"},
      "usage": {
        "source": "host runtime result for coordinator review turn 1",
        "scope": "atomic_call",
        "input_tokens": 40000,
        "cached_input_tokens": 10000,
        "output_tokens": 2000,
        "reasoning_output_tokens": 1000
      }
    }
  ],
  "astra_repricing": {"model": "fictional-astra-v1"}
}
```

`pricing-snapshot.json`:

```json
{
  "schema_version": 1,
  "snapshot": {
    "version": "fictional-price-list-2026-09",
    "as_of": "2026-09-19",
    "source_url": "https://example.invalid/fictional-api-pricing"
  },
  "models": {
    "fictional-worker-v1": {
      "input_usd_per_million": "2.00",
      "cached_input_usd_per_million": "0.50",
      "output_usd_per_million": "10.00"
    },
    "fictional-coordinator-v1": {
      "input_usd_per_million": "4.00",
      "cached_input_usd_per_million": "1.00",
      "output_usd_per_million": "20.00"
    },
    "fictional-astra-v1": {
      "input_usd_per_million": "3.00",
      "cached_input_usd_per_million": "0.75",
      "output_usd_per_million": "15.00"
    }
  }
}
```

The JSON result always separates `observed_subset` from `full_scope_estimate`. A result is `complete` only when the caller asserts complete coverage and every expected call has sourced, priceable atomic usage. A partial assertion, a missing call, `usage: null`, a missing counter, or a missing rate makes `full_scope_estimate` unavailable. The priceable records can still appear in `observed_subset`; they are never relabeled as a whole-task total.

`astra_repricing` is optional. When requested, it reprices the exact same observed token counters using the named model only when the declared scope is completely observed and comparable. It is a same-token API counterfactual, not measured all-Astra savings, an observed model-performance comparison, an invoice, or a Codex subscription cost.
