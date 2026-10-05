# Public trading project methodology review

Reviewed 2026-10-05 to continue from phase 82. These are engineering references,
not a profitability ranking. Popularity, feature counts and README performance
claims cannot establish the world's best strategy or an FX edge. Only public
documentation/repositories were reviewed; no private code or package imported.

| Reference and primary source | Pattern / our problem | Benefit and complexity | Risk and decision |
| --- | --- | --- | --- |
| [NautilusTrader backtesting](https://nautilustrader.io/docs/latest/concepts/backtesting/) | Reuse simulation and operation components. | One entry/exit adapter makes cost changes testable; low incremental complexity. | Duplicate helper calls do not prove full parity. Adopt shared fills and disclose gaps. |
| [LEAN time frontier](https://www.quantconnect.com/docs/v2/writing-algorithms/key-concepts/time-modeling/timeslices) | Bars become available at their end. Our decisions used closed OHLC at opening time. | Explicit availability prevents future-information fills; one optional contract field. | Preserve event-at-open callers; generated bar-close signals require availability. Implemented. |
| [Freqtrade lookahead analysis](https://www.freqtrade.io/en/stable/lookahead-analysis/) | Compare full and sliced histories. | Prefix and future-perturbation tests; low complexity. | Untriggered strategy branches remain unverified. Adopt the testing method with forced entries and real features/ensemble checks. |
| [CCXT unified API](https://docs.ccxt.com/) | Normalize provider data behind contracts. | Supports the design of the existing instrument registry and unique MT5 adapter. | Exchange integration has no current FX benefit. Reference only; do not install. Broker snapshot remains pending. |
| [FinceptTerminal](https://github.com/Fincept-Corporation/FinceptTerminal) | Research and data exploration workflows. | Possible future UI reference, no immediate correctness benefit. | Terminal functionality is not evidence of edge. Defer integration/UI work. |
| [Vibe-Trading, HKUDS](https://github.com/HKUDS/Vibe-Trading) | Agent-assisted research workflow. | Potential research aid once deterministic evidence is reliable. | LLM output is not an MT5 risk decision. No dependency or agent execution route added. |
| [TradingView MCP, atilaahmettaner](https://github.com/atilaahmettaner/tradingview-mcp) | Market-analysis tools and context. | Potential auxiliary research data, requiring availability/provenance checks. | The prior chat did not identify the repository: this is a named candidate, not an asserted match. Charts are not broker truth; no installation. |

The implementation decisions in this table are our assessment of applicability.
No claim is made to have audited these entire projects or benchmarked their
financial returns. The adopted techniques improve test validity, not proven win
rate or expected profit.

The corrected legacy OHLC path shares seven of sixteen stage contracts; six
decision stages and three adapter-equivalence gaps remain outside that path.
The recorded-context replay and explicit-quote stateful replay are separate
evidence scopes and must not silently change that legacy inventory to 100%.
Exercise actual stateful callers with matching clocks, metadata and model/config
hashes. Preserve every decision and compare full traces; duplicate component
calls cannot serve as an acceptance gate.

Then evaluate changes against cost-matched baselines, untouched out-of-sample
periods, walk-forward folds, cost stress and seeded Monte Carlo under PROJECT_SPEC
section 12. Record every configuration tried and retain negative results. Tuning
against the final test period invalidates it as holdout evidence.

No strategy was promoted. DEMO_ONLY=True and LIVE_TRADING_APPROVED=False.

Follow-up primary references:

- [NautilusTrader data and venues](https://nautilustrader.io/docs/latest/concepts/backtesting/data-and-venues/):
  bars cannot establish intrabar price order, spread, depth or queue position.
  This supports the explicit quote input contract in our stateful replay; no
  fabricated OHLC path is labelled observed tick data.
- [MQL5 price precision and change steps](https://www.mql5.com/en/book/automation/symbols/symbols_point_tick):
  digits, point and minimum tick increment are distinct metadata. Shared stops
  and fills now respect the tick increment; adverse rounding enters sizing.
  Tick value denomination and historical changes still need broker evidence.
