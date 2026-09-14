# Layer3 research scoring rubric v2

The Python engine already owns `earnings_momentum` and `business_quality`.
Never replace or recalculate them. Research supplies only `industry_cycle`,
`expectation_delta`, and `risk`, each from 0 to 100.

## Industry cycle

- 80-100: multiple current indicators show improving price, demand, utilization,
  orders, or falling inventory, supported mainly by tier 1-2 sources.
- 60-79: direction is moderately positive but incomplete or uneven.
- 40-59: neutral, mixed, or no material change.
- 20-39: weakening demand, price, utilization, or rising inventory.
- 0-19: broad and strongly supported deterioration.

## Expectation delta

This measures change in future earnings expectations, not absolute company
quality.

- 80-100: strong evidence that the next 3-12 month earnings path is materially
  better than previously expected.
- 60-79: credible positive revision or catalyst, with some uncertainty.
- 40-59: expectations broadly unchanged or evidence mixed.
- 20-39: credible downward revision or catalyst disappointment.
- 0-19: severe and broad expectation deterioration.

Do not infer market consensus from share-price performance alone. If no dated
consensus, guidance, order, price, capacity, or operating evidence is available,
keep the result `partial` rather than inventing a precise expectation score.

## Risk

Higher is worse:

- 0-29 / `LOW`: normal operating risks with no near-term dominant threat.
- 30-59 / `MEDIUM`: material but manageable uncertainty.
- 60-79 / `HIGH`: significant downside risk requiring caution.
- 80-100 / `RED`: investigation, fraud concern, major solvency/default risk,
  delisting risk, severe governance failure, or another evidence-backed veto.

A `RED` level or any `vetoes` entry must have direct evidence. Never use RED
only because the stock is volatile or valuation appears high.

## State and signals

Choose `IMPROVING`, `STABLE`, `DETERIORATING`, or `UNCERTAIN` from the combined
direction of current operating, industry, and expectation evidence.

For `complete`, answer every signal with true or false:

- `revenue_accelerating`
- `profit_accelerating`
- `margin_improving`
- `industry_improving`
- `expectation_revision`

The first three must respect the financial quantities already supplied in the
request. Research may explain them but may not contradict the supplied figures
without explicit evidence of a data defect. Use null signals for `partial` when
the evidence cannot support true or false.

## Confidence

- 0.80-1.00: several timely tier 1-2 sources and strong cross-checking.
- 0.60-0.79: adequate primary/official support with limited gaps.
- Below 0.60: incomplete, stale, indirect, or conflicting support; normally use
  `partial`.

Confidence measures evidence quality and coverage, not enthusiasm about the
stock.

## Evidence-to-score calibration

- A precise score is a summary of the mapped evidence, not an independent fact.
- When evidence only supports a range, choose the midpoint conservatively and
  explain uncertainty in the matching summary.
- Scores of 80 or above need current, direct evidence; do not award them from a
  single promotional statement or an announced-but-unfinished plan.
- If two credible sources conflict materially, add a `source_conflict` quality
  flag, lower confidence, and normally return `partial` until the conflict can be
  resolved.
- Low-base growth, accounting-scope changes, and unit ambiguity must not be
  treated as operating acceleration without an explicit adjustment.
