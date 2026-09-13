# Research output contract

Start from the generated `result.template.json`. Preserve these fields exactly:

- `schema_version`
- `run_id`
- `input_hash`
- `code`
- `name`
- `as_of_date`

Allowed status values are `complete`, `partial`, and `failed`. Use `failed` only
for an operational failure that prevented research. Use `partial` for missing or
conflicting evidence.

## Complete result requirements

A `complete` record must contain:

- numeric `industry_cycle`, `expectation_delta`, and `risk` scores from 0 to 100;
- all five signals as booleans;
- at least one risk;
- at least one traceable evidence item;
- non-empty `why_now`, `industry_summary`, `expectation_summary`, and
  `risk_summary`;
- confidence from 0 to 1 and a consistent risk level.

Each evidence object must include:

- `claim`: the exact conclusion supported;
- `source_type`: use `filing`, `investor_relations`, `company`, `industry`,
  `government`, `research`, or `media`;
- `source_name`;
- `source_tier`: 1, 2, 3, or 4;
- `published_date`: exact `YYYY-MM-DD`, never later than `as_of_date`;
- `effective_period`;
- `confidence`: 0 to 1;
- at least one of `source_url` or `document_id`;
- `excerpt`: a short necessary paraphrase or excerpt, preferably no more than
  25 Chinese characters or 25 words.

Source tiers:

1. Exchange filings, financial reports, earnings forecasts, official investor
   relations records.
2. Company websites, industry associations, government statistics.
3. Broker research and professional financial media.
4. General media and online discussion.

Tier 4 evidence cannot be the sole support for a score, catalyst, veto, or RED
risk. Search-result snippets are discovery aids, not final evidence; open the
underlying source before citing it.

## Atomic handoff

Write a complete JSON object to a temporary file in the same inbox directory,
parse it once to confirm valid JSON, then rename it to `<code>.json`. Never edit
files under `research/results/`; the Python validator owns that directory.

After writing, use the project command to validate and merge. A result is not
accepted merely because the inbox file exists.
