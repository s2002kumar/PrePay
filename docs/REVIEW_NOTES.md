# Architecture review — what changed from Claude's first proposal

2026-10-27. Source: original `prepay.zip` reviewed against Freddie Mac's July 2026 Release 47 General User Guide, Freddie dataset terms, FRED methodology notes and official model-governance material.

## Verdict

**Keep Prepay. Rewrite the implementation spec before coding.** The original single-machine DuckDB + dbt + LightGBM + FastAPI direction is appropriate and credible. The main weaknesses were *financial-event semantics, future cash-flow interpretation, probability mathematics, potentially unauthorized publication of protected outputs, and an unrealistic perfect-score mandate*. The new design fixes those and gives Claude permission to implement complete vertical slices instead of asking for approval at every milestone.

## Material corrections

| Issue in original ZIP | Why it matters | Revised decision |
|---|---|---|
| Code `15` mapped to default | Official guide identifies it as whole-loan sales | right-censor as external loan transfer |
| First modification `Y` mapped to default | contract changes; not terminal loss | censor/exclude post-modification in v1, quantify impact |
| 90+ delinquency mapped to absorbing default | serious delinquency can cure; does not realize cash loss | model *terminal credit disposition*, not delinquency-as-loss |
| Scheduled principal calculated for survivors only; interest described as received | distort expected payment timing/credit cash claims | explicit schedule-before-exit convention, separate contractual accrual vs receipt |
| Credit principal counted as exit and payoff cash ambiguously | wrong investor cash ledger | credit exposure exit vs delayed recovery/loss separated |
| `p+d` clipped to <=1 after two classifiers | silently breaks probability validity and log-loss calibration | coherent three-class softmax or factored competing-risk challenger |
| GBM must beat all baselines in all holdouts | cannot promise outcome; encourages test reuse | lock honest candidate, report results even if baseline wins |
| Actual vs projected cohort removes future censored loans on both sides | future censor events aren't known at forecast date | censor-aware event-incidence evaluation; never condition simulation on future censoring |
| Grouping at least 25 real loans used as implied publishing license | data/derived product terms are more restrictive | fictional public demo, restricted private research, explicit publication review |
| No bounded-memory design for large cumulative loan-month history | hundreds of millions of months possible | streaming Parquet/DuckDB, memory benchmark, deterministic sampling only if necessary |
| Public demo backed by private representative loans/models | source/license and reconstruction risk | independent synthetic portfolios and optional synthetic-trained model |
| CLI milestone loop stopped for approval every time | owner requested end-to-end delegation | autonomous PR loop within locked scope, escalation only for permissions/core changes |
| “real MBS cash flows” could be inferred | no fees/servicing/waterfall and incomplete collections | clearly called illustrative mortgage pool contractual cash-flow simulator |

## Trade-offs we chose deliberately

- **No Spark or Kafka** because it would create architectural ceremony rather than demonstrate value at sample-scale. Strong idempotency, lineage, DuckDB, dbt, batch processing and tests are more credible.
- **No LLM layer** because this project's differentiator is trained and reproducibly evaluated statistical ML with direct cash-flow consequences.
- **No grand “default prediction” marketing language** because a prepay/terminal disposition competing-risk model is narrower but more economically accurate.
- **No automatic public real-model inference** because source-data terms require an independent permission decision. The private validated ML pipeline remains a flagship achievement.
- **No fake history or numbers**: built examples and synthetic test fixtures are explicitly identified; real holdout results require actual data and code execution.

## Outstanding owner dependencies

The provided ZIP contains only markdown and configuration, not Freddie Mac archive files or implemented source code. It is impossible to produce honest historical metrics or a trained real-data model from that ZIP alone. At implementation time the owner must have a registered Freddie Mac data download/authorized local source for the private research track, and separately approve any account connections, charges, public repo visibility or real-derived publication. Claude should autonomously implement everything else.
