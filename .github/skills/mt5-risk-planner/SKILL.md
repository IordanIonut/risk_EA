---
name: mt5-risk-planner
description: "Use when working on or answering questions about the risk_EA MT5 Portfolio Risk Planner: its desktop UI, DCA/RSI candidate settings, prop-firm drawdown budgets, MT5/Yahoo market data, scenarios, .set templates, or equity guard. Triggers include risk_EA, calcul risc MT5, setări DCA/RSI, drawdown prop, scădere index, DCA grid risk, RSI robot settings, peak-to-trough drawdown, and portfolio risk planner."
---

# MT5 Portfolio Risk Planner

Use this skill to understand the existing application before changing code or explaining what its recommendations mean. The project is a Python/Tkinter desktop planner for estimating cash-risk budgets and candidate settings for third-party MT5 DCA/RSI robots. It does not contain the robots' source code and is not an EA backtester.

## Product purpose and boundaries

- The user allocates total account capital and a daily cash or percentage loss limit across index/robot allocations.
- The tool estimates a per-allocation risk allowance, reads broker contract data and price history, and suggests fixed-lot grid parameters intended to keep a modeled adverse move within that allowance.
- The intended use is conservative planning for prop-account limits, especially a long grid through a large correction in an otherwise bullish market.
- State conclusions as estimates under stated assumptions. Never promise that a setting will prevent a drawdown, preserve a prop account, or cap live losses.
- The EA source and verified `.set` files are unavailable. The planner cannot know actual entry logic, current positions, trade sequencing, real TP behavior, or whether an EA obeys a guard lock. Do not claim generated `.set` names/enums match an unknown EA.

## Architecture and source of truth

- [`risk_calculator_app.pyw`](../../../risk_calculator_app.pyw): Tkinter UI, allocation and scenario workflows, Yahoo and MT5 imports, candidate-setting generation, combined portfolio report, `.set` template generation.
- [`risk_calculator.py`](../../../risk_calculator.py): Decimal-based calculation engine for allocation budgets, daily OHLC stress, peak-to-trough moves, grid losses, and candidate lot/Max Trades.
- [`test_risk_calculator.py`](../../../test_risk_calculator.py): risk math, grid loss, budget constraints, historical stress and replay tests.
- [`test_risk_calculator_app.py`](../../../test_risk_calculator_app.py): CSV import, `.set` template and scenario migration/validation tests.
- [`ExportMT5ContractSpecs.mq5`](../../../ExportMT5ContractSpecs.mq5): exports symbol point/tick values, volume min/step/max, and account currency to Common Files CSV.
- [`ExportMT5History.mq5`](../../../ExportMT5History.mq5): exports OHLC bars to Common Files CSV; daily bars are preferred.
- [`MT5EquityRiskGuard.mq5`](../../../MT5EquityRiskGuard.mq5): standalone timer-driven daily/overall equity guard; separate from the planner and not integrated into unknown robots.
- [`README.md`](../../../README.md): user workflow, assumptions, exports, and warnings.

The Python app uses the standard library only. Keep calculation behavior in the pure engine where practical, and keep UI orchestration and I/O in the app.

## Data flow and calculations

1. The portfolio screen records account capital, account currency, daily limit (cash or percent), optional remaining daily/overall prop-loss room, and each symbol/robot/capital allocation.
2. The effective portfolio cap is the tightest configured daily limit, remaining daily room, and remaining total-loss room. Each allocation receives a share proportional to its assigned capital. Do not silently infer a firm's rules or reset schedule.
3. Market inputs come from the broker's MT5 contract CSV and history CSV, or Yahoo Finance as fallback. Yahoo aliases are in `YAHOO_ALIASES`; users can override a ticker. Yahoo's index may not match the broker CFD.
4. History must contain at least 20 valid daily bars. Intraday MT5 rows are aggregated by date using daily high, low, last close, maximum observed spread, and summed spread sample counts where provided. MT5 bars are preferred for their broker symbol. The **Fetch Yahoo data for all** workflow intentionally replaces existing history with Yahoo history when available.
5. The stress selector supports target price, manual adverse percent, historical worst daily shock, and historical peak-to-trough drawdown. The aggregated downside suggestion chooses the peak-to-trough mode and long direction.
6. Peak-to-trough stress tracks the running daily high and the subsequent low across the entire history. For the grid estimate, the resulting percentage move is applied to the current reference price. It assumes the grid starts at the reference/peak and accumulated entries remain open to the trough; no intermediate TP closes are credited.
7. Grid loss is approximated from `point_value_per_lot`, grid step, stress distance, max trades, volume, and execution-cost inputs. The manually configured spread is a floor; where MT5 bars include `spread_max_points`, each bar's stress cost uses the larger of the configured spread and that maximum (legacy `spread` is the fallback). Peak-to-trough sizing uses the maximum spread observed over the imported history. Candidate lot sizing respects optional per-order broker `SYMBOL_VOLUME_MAX`, volume-step rounding, and the minimum volume, uses fixed lots and multiplier `1.0`, and allocates at most 80% of the available risk budget. `SYMBOL_VOLUME_MAX` is a per-order limit, not a cap on total grid exposure. If even the minimum broker lot does not fit, it should report that no safe candidate is available rather than returning an unsafe one. `spread_avg_points` is informational only; `spread_sample_count` records valid Bid/Ask tick updates and does not prove all spikes were captured. Zero samples means the exporter fell back to bar spread.
8. A per-symbol commission override on the broker-contract settings replaces the shared commission fallback for that allocation; an empty override uses the common fallback. Commission is round-turn cash per 1.00 lot and must be user-verified because MT5 symbol properties do not provide broker commission.
9. The aggregate report sizes each allocation against its own historical adverse move and assumes those moves occur simultaneously. This is a conservative portfolio stress convention, not a probability forecast.
10. In peak-to-trough mode the same configured risk allowance is applied to the whole episode; the model does not assume the daily loss allowance resets while the drawdown unfolds.

### Values that are calculated versus strategy inputs

The planner can estimate `Risk` as a fixed lot and `Max Trades` from the risk allowance, history, contract specification, grid step, and configured transaction costs. It can set the multiplier to `1.0` for this conservative sizing model.

Step and Take Profit values, entry-on-price-break choices, RSI oversold/overbought levels and period, and other EA-specific behavior are not derivable from drawdown limits alone. Preserve user values or mark missing strategy values for manual backtesting. For RSI, the grid stress is only a position-sizing approximation; it does not simulate RSI signals or `Close When Overbought`.

## Scenario and export compatibility

- Scenario JSON is version 12. Validation/migration for prior versions is implemented in `RiskCalculatorApp._validate_scenario`; preserve backward loading when changing its schema.
- Historical Yahoo snapshots persist calculated stress statistics. Imported MT5 bars, including optional maximum spread and tick sample counts, are saved with their source, validated, and used to recompute peak-to-trough statistics on load. Old scenarios without peak-to-trough statistics cannot support the new drawdown mode until history is refreshed.
- Per-symbol round-turn commission overrides are optional contract fields; the shared commission setting is the fallback. MT5 cannot export broker commission as a symbol property, so users must verify and enter it from their account's fee schedule.
- `.set` output is explicitly a draft. Enum ordinals and input identifiers in `build_mt5_set_template` are inferred from the user's parameter list, not verified against an EA. Do not label export as confirmed compatible.
- When adding a setting to scenario persistence or output generation, update the corresponding validation, migration, UI, and tests together.

## Equity guard constraints

The guard compares live equity with user-supplied daily starting equity and optional initial balance/overall loss limit. It can close configured positions and pending orders and publish a terminal global lock variable. It cannot stop a non-cooperating EA from reopening trades. Missing/invalid baselines, terminal downtime, broker failures, gaps and slippage are material risks. Any MQL5 changes require MetaEditor compilation where available and demo testing; do not test on a live prop account.

## Working procedure for future requests

1. Identify whether the request concerns risk math, UI, history/contract import, scenarios, `.set` output, or the MQL5 guard. Read the relevant implementation and tests before proposing behavior.
2. Clarify whether a requested rule is a firm rule or a user-configured assumption when that distinction changes the result. Do not invent trailing-drawdown semantics, trading-session resets, contract multipliers, or EA inputs.
3. Make the smallest complete change, preserving the existing scenario migration path and explicit error reporting. Avoid treating missing market/contract data as zero or returning a success-shaped partial recommendation.
4. Test the exact behavior, including boundary cases such as minimum volume, insufficient risk budget, invalid/missing history, and multi-allocation totals when relevant.
5. Run the narrowest applicable validation, then broader tests if needed:
   - `py -m unittest -v`
   - `py -m py_compile risk_calculator.py risk_calculator_app.pyw test_risk_calculator.py test_risk_calculator_app.py`
   - `git diff --check`
6. For MQL5 changes, compile the changed file in MetaEditor if available and clearly state if compilation or demo execution could not be performed.
7. Update [`README.md`](../../../README.md) when a user workflow or model assumption changes. Report test results and remaining limits without implying live safety.

## Accuracy roadmap (not implemented yet)

Ordered by expected impact on recommendation quality. Move an item out of this list when it is implemented.

1. Chronological grid backtest on MT5 bars (preferably M1/M5): open entries at each Step, close at TP, carry positions across days, and report max equity drawdown, worst daily loss, TP count, and profit. This is required before the tool can rank settings by profit as well as by survival.
2. Settings optimizer: search Step Value, Max Trades, and fixed lot (and optionally multiplier > 1) and rank candidates that pass both daily and overall prop limits by modeled profit / drawdown.
3. Joint portfolio stress using date-aligned history across symbols instead of assuming each symbol's worst episode happens simultaneously; keep the simultaneous mode as a conservative option.
4. Add margin requirements and long/short swap inputs; commission can now be overridden per symbol but margin/swap are not modeled.
5. Export margin per lot and swap long/short and calculate account margin utilization; `SYMBOL_VOLUME_MAX` is exported and enforced per order, but total grid exposure and account leverage/margin remain unmodeled.
6. Separate daily-loss and overall-loss checks for multi-day drawdowns (configurable reset hour and static vs trailing overall rule, entered explicitly by the user).
7. Bootstrap / Monte Carlo of historical episodes to report a probability of breaching the limits rather than a single worst case.
8. Import Strategy Tester reports or MT5 account history for the real robots to calibrate the model against actual EA behavior.

## Safety and modeling limitations to retain in explanations

Historical prices do not predict future moves. OHLC and per-bar spread do not reveal intrabar path, unobserved spread spikes, swap, liquidity, slippage, broker execution, gaps, retained positions before the test starts, or robot decision logic. Peak-to-trough stress is not an equity-curve backtest. A broker's point value, point size, currency conversion, minimum lot and volume step must be correct. No simulated cap prevents losses from exceeding the prop limit in live conditions.
