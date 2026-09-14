# Research output contract v2

Start from the generated `result.template.json`. Preserve `schema_version`,
`run_id`, `input_hash`, `code`, `name`, and `as_of_date` exactly. Never downgrade
a v2 work item to v1.

## Status and metadata

Allowed statuses are `complete`, `partial`, and `failed`. Use `failed` only for
an operational failure. Use `partial` for missing, stale, indirect, ambiguous,
or conflicting evidence.

Fill every `research_metadata` field:

- preserve `skill_version` and `rubric_version` from the template;
- set the real `model_provider` and `model_name`;
- set `started_at` and `finished_at` as ISO 8601 timestamps with time zones.

## Complete result

A `complete` record must contain three numeric scores from 0 to 100, all five
signals as booleans, at least one risk, confidence from 0 to 1, and non-empty
`why_now`, `industry_summary`, `expectation_summary`, and `risk_summary`.
`catalysts`, `risks`, and `vetoes` each contain at most three concise,
non-duplicate Chinese conclusions.

## Evidence objects

Each evidence object must include:

- `evidence_id`: unique `E1`, `E2`, ... identifier;
- `claim`: the factual statement or explicitly labeled inference supported;
- `source_type`: `filing`, `investor_relations`, `company`, `industry`,
  `government`, `research`, or `media`;
- `source_name` and exact `source_title`;
- `source_tier`: 1, 2, 3, or 4;
- `published_date`: exact `YYYY-MM-DD`, never later than `as_of_date`;
- `effective_period` and evidence-level `confidence` from 0 to 1;
- `retrieved_at`: ISO 8601 timestamp with time zone;
- at least one of `source_url` or `document_id`;
- `excerpt`: a necessary short paraphrase or excerpt, preferably no more than
  25 Chinese characters or 25 words;
- `supports`: one or more exact conclusion targets.

Valid `supports` targets are:

- `industry_cycle_score`, `expectation_delta_score`, `risk_score`, `why_now`;
- `industry_summary`, `expectation_summary`, `risk_summary`;
- `signals.<signal_name>`;
- `catalysts.0` through `.2`, `risks.0` through `.2`, and `vetoes.0` through
  `.2`, matching the zero-based position in the result arrays.

Every score, summary, catalyst, risk, veto, and `why_now` must have mapped
evidence. One evidence item may support multiple genuinely related targets.
Tier 4 evidence cannot be the sole support for a required target. RED risks and
vetoes require tier 1-2 evidence.

Source tiers:

1. Exchange filings, financial reports, earnings forecasts, and official
   investor-relations records.
2. Company websites, industry associations, and government statistics.
3. Broker research and professional financial media.
4. General media and online discussion.

## Data-quality flags

Always return `quality_flags`, even when it is empty. Each flag contains `code`,
a specific Chinese `detail`, and any related `evidence_ids`. Allowed codes:

- `unit_ambiguity`
- `low_base_growth`
- `consolidation_scope_change`
- `plan_not_completed`
- `source_conflict`
- `stale_evidence`
- `date_ambiguity`
- `secondary_source_only`
- `other`

Do not silently normalize or resolve a material ambiguity. Record it and lower
confidence; use `partial` when it prevents a defensible score.

## Atomic handoff

Write a complete JSON object to a temporary file in the same inbox directory,
parse it once, then rename it to `<code>.json`. Never write under
`research/results/`; the Python validator owns that directory. An inbox file is
not accepted until the project command validates and merges it.
