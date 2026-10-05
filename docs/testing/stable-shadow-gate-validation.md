# Stable shadow gate input contract

`stable_shadow_gate_v2` changes validation, not trading thresholds or permission.
It evaluates `BALANCED_STABLE` evidence for paper observation only. Demo/live
execution stays disabled. No real artifact was promoted during these tests.

Required evidence is a JSON object whose `profile` matches `BALANCED_STABLE`.
`execution_attempted` must be boolean false; `not_for_demo_live` and
`stable_filters_applied` must be boolean true. Strings and numeric substitutes
are invalid. Legacy summaries may omit `order_send_called`/`order_check_called`;
when present, each must be boolean false.

`total_trades` must be a finite, nonnegative integral JSON number. A usable
sample requires at least 100 trades and `USABLE_SAMPLE` or
`PROMOTION_SAMPLE_SIZE`. Profit factor must be finite and at least 1.20, and
expectancy in R finite and positive. Booleans, numeric strings, NaN, infinity,
fractional counts and absent metrics fail closed. If winrate is supplied it
must be a finite percentage between 0 and 100. Missing or invalid report
numbers become JSON null, not zero or an assumed favorable value.

The accepted classification vocabulary is limited to current producer outputs:

| Evidence | Accepted states |
| --- | --- |
| Monte Carlo | `MONTE_CARLO_OK`, `MONTE_CARLO_WARNING` |
| Stress | `STRESS_OK`, `STRESS_WARNING` |
| Walk-forward | `WALK_FORWARD_OK`, `WALK_FORWARD_WARNING` |
| Cost sensitivity | `COST_SENSITIVITY_OK` |

Warnings retain the existing paper-only policy; this does not certify a
profitable strategy. Missing, unknown, limited and insufficient states cannot
approve observation. Known failure states retain their existing remediation
decisions. The stability-repair summary is supplementary historical context;
it cannot substitute for any missing robustness classification.

Malformed JSON, non-object JSON and non-finite JSON constants produce a
negative decision. If the preferred robustness summary exists but is invalid
or empty, an older fallback cannot override it. A genuinely absent preferred
path retains the existing `runs_root/robustness/robustness_summary.json` fallback.

Compatibility: complete legacy summaries with correctly typed metrics, flags,
profile identity and accepted states retain their result. Previously accepted
incomplete/unknown summaries now require regeneration. This gate does not
authenticate source, configuration or strategy hashes; it does not manufacture
provenance for old artifacts. Binding promotion to verified data/config/code
remains a separate requirement, and no hash is inferred from these labels.

Verification: `tests/python/test_stable_shadow_gate_fail_closed.py` covers each
numeric and boolean corruption, classification allowlists, old valid summaries,
negative states, unchanged boundaries and preferred-artifact fallback behavior.
All file-writing tests use temporary directories and synthetic evidence.
