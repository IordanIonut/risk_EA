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

The core Python app uses the standard library; optional direct MT5 terminal access imports the official `MetaTrader5` package at runtime. Keep calculation behavior in the pure engine where practical, and keep UI orchestration and I/O in the app.
- The application auto-saves its current portfolio, contract inputs, quote, and available Yahoo/MT5/API bars in the project-local ignored `data/portfolio.json`, and restores the validated scenario on launch. The previous `%APPDATA%\MT5RiskPlanner\portfolio.json` location is migrated when the new file does not yet exist. Broker REST endpoint configuration is saved separately in ignored `data/broker_api_config.json`; API tokens are never persisted. Portfolio downside suggestions refresh five-year Yahoo daily data for allocations without broker CSV, terminal, or REST history; saved snapshots remain a disclosed offline fallback. The generic REST connector requires HTTPS and a per-symbol JSON response containing `account_currency`, matching `symbol`, `quote`, `contract`, and at least 20 valid daily `bars`; see the README schema. API-specific authentication, formats, contract units, and terms must be verified against the actual broker. When the optional official `MetaTrader5` Python package and a logged-in terminal are available, the **Connect MT5: get specs + 5y D1** action reads CFD contract specs and D1 history directly, without CSV. Manual contract entry and MT5 CSV import remain fallback options.

## Data flow and calculations

Startup schedules a background refresh after the UI and saved portfolio are loaded. Each allocation retains its data source: Yahoo/unknown uses Yahoo (unknown uses the saved REST endpoint when configured), `MT5 terminal` reconnects to the terminal, and `Broker API` uses the saved HTTPS endpoint without a persisted token. Authenticated APIs may require manual token entry and retry. Imported `MT5 CSV` snapshots are retained with a reimport/connect warning, never silently replaced with Yahoo. Source failures retain cached data and are summarized after other allocations finish; startup does not change account currency or automatically generate settings. All network fetches share an indeterminate status-bar activity indicator. A scenario reload drains in-flight startup messages through `startup_done` without applying them.

1. The portfolio screen records account capital, account currency, daily limit (cash or percent), optional remaining daily/overall prop-loss room, and each symbol/robot allocation. New allocations are entered as a percentage of account capital (combined percentage maximum 100%); legacy scenario allocations without a percentage remain fixed cash amounts.
2. The effective portfolio cap is the tightest configured daily limit, remaining daily room, and remaining total-loss room. Each allocation receives a share proportional to its assigned capital. Do not silently infer a firm's rules or reset schedule.
3. Market inputs come from the logged-in MT5 terminal when the optional `MetaTrader5` Python package is available, MT5 contract/history CSV imports, a user-configured HTTPS REST endpoint using the documented normalized JSON schema, or automatically fetched Yahoo Finance daily history as fallback. The app stores the validated portfolio in ignored project-local `data/portfolio.json`; REST URL configuration is stored without credentials in `data/broker_api_config.json`. Yahoo aliases are in `YAHOO_ALIASES`; users can override a ticker. Yahoo's index may not match the broker CFD. Broker-specific CFD contract parameters must come from MT5, a verified broker API response, or explicit user input.
4. History must contain at least 20 valid daily bars. Intraday MT5 rows are aggregated by date using the earliest open, daily high, low, last close, maximum observed spread, and summed spread sample counts where provided. Each close and optional open must lie within its bar's low/high range before aggregation. Broker-imported, terminal, and REST bars are preferred for their broker symbol. The **Fetch Yahoo data for all** workflow intentionally replaces existing history with Yahoo history when available.
5. The stress selector supports target price, manual adverse percent, historical worst daily shock, and historical peak-to-trough drawdown. The aggregated downside suggestion refreshes the latest five years of Yahoo data for allocations without MT5 history, preserving broker-imported history, then chooses peak-to-trough mode and long direction. If online refresh fails, complete cached Yahoo snapshots may be used with explicit report warnings.
6. Peak-to-trough stress tracks the running daily high and the subsequent low across the entire history. For the grid estimate, the resulting percentage move is applied to the current reference price. It assumes the grid starts at the reference/peak and accumulated entries remain open to the trough; no intermediate TP closes are credited.
7. Grid loss is approximated from `point_value_per_lot`, grid step, stress distance, max trades, volume, and execution-cost inputs. The manually configured spread is a floor; where MT5 bars include `spread_max_points`, each bar's stress cost uses the larger of the configured spread and that maximum (legacy `spread` is the fallback). Peak-to-trough sizing uses the maximum spread observed over the imported history. Candidate lot sizing respects optional per-order broker `SYMBOL_VOLUME_MAX`, volume-step rounding, and the minimum volume, uses fixed lots and multiplier `1.0`, and allocates at most 80% of the available risk budget. `SYMBOL_VOLUME_MAX` is a per-order limit, not a cap on total grid exposure. If even the minimum broker lot does not fit, it should report that no safe candidate is available rather than returning an unsafe one. `spread_avg_points` is informational only; `spread_sample_count` records valid Bid/Ask tick updates and does not prove all spikes were captured. Zero samples means the exporter fell back to bar spread.
8. A per-symbol commission override on the broker-contract settings replaces the shared commission fallback for that allocation; an empty override uses the common fallback. Commission is round-turn cash per 1.00 lot and must be user-verified because MT5 symbol properties do not provide broker commission.
9. The aggregate report sizes each allocation against its own historical adverse move and assumes those moves occur simultaneously. This is a conservative portfolio stress convention, not a probability forecast.
10. In peak-to-trough mode the same configured risk allowance is applied to the whole episode; the model does not assume the daily loss allowance resets while the drawdown unfolds.
10a. The combined report labels the portfolio ACCEPTED only when modeled loss is at most 80% of the allocated effective loss allowance and the remaining overall prop-loss room is supplied; results above that buffer are NOT ACCEPTED, above the allocated allowance are REJECTED, and missing market/contract data or overall room yields UNVERIFIED. The accepted report includes per-allocation candidate fixed-lot, Max Trades, Magic Number, and shared Step/Take Profit values. These are planner thresholds, not prop-firm approvals or verified EA presets.
11. When imported MT5 bars and a Take Profit value are available, candidate generation also reports a generic single-campaign chronological grid simulation: it starts at the first daily close and uses open, adverse extreme, favorable extreme, close paths. Market-on-threshold entries fill gaps at the open and reanchor the next step to the fill. An opening gap beyond basket TP closes at the open before intraday moves. Missing opens use the previous close clamped to the bar's range, with a report warning. This is not a pending-order model. Cash and percentage drawdown maxima are tracked independently; dates refer to the cash maximum. Daily loss is measured from the previous close's equity, not firm-specific reset rules. Intraday rows are currently aggregated to daily bars, and the campaign does not restart after TP because EA entry signals are unknown. This output is an OHLC approximation, not an EA backtest.
12. Static grid stress includes transaction costs for entries exactly at the stress endpoint. Flat bars can contribute transaction-cost risk even without a price move.

### Values that are calculated versus strategy inputs

The planner can estimate `Risk` as a fixed lot and `Max Trades` from the risk allowance, history, contract specification, grid step, and configured transaction costs. It can set the multiplier to `1.0` for this conservative sizing model. It does not optimize strategy values such as Step, Take Profit, or RSI thresholds.

Step and Take Profit values, entry-on-price-break choices, RSI oversold/overbought levels and period, and other EA-specific behavior are not derivable from drawdown limits alone. Preserve user values or mark missing strategy values for manual backtesting. For RSI, the grid stress is only a position-sizing approximation; it does not simulate RSI signals or `Close When Overbought`.

## Scenario and export compatibility

- Scenario JSON is version 13, preserving optional daily opens; missing opens in older snapshots remain unknown. Validation/migration for prior versions is implemented in `RiskCalculatorApp._validate_scenario`; preserve backward loading when changing its schema.
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

1. Preserve chronological MT5 M1/M5 bars for the grid campaign replay, then model repeat entries/campaigns with explicit execution-path assumptions. The current implementation only replays one campaign on daily OHLC and cannot rank real EA settings by profit or survival.
2. Settings optimizer: search Step Value, Max Trades, and fixed lot (and optionally multiplier > 1) and rank candidates that pass both daily and overall prop limits by modeled profit / drawdown.
3. Joint portfolio stress using date-aligned history across symbols instead of assuming each symbol's worst episode happens simultaneously; keep the simultaneous mode as a conservative option.
4. Add margin requirements and long/short swap inputs; commission can now be overridden per symbol but margin/swap are not modeled.
5. Export margin per lot and swap long/short and calculate account margin utilization; `SYMBOL_VOLUME_MAX` is exported and enforced per order, but total grid exposure and account leverage/margin remain unmodeled.
6. Separate daily-loss and overall-loss checks for multi-day drawdowns (configurable reset hour and static vs trailing overall rule, entered explicitly by the user).
7. Bootstrap / Monte Carlo of historical episodes to report a probability of breaching the limits rather than a single worst case.
8. Import Strategy Tester reports or MT5 account history for the real robots to calibrate the model against actual EA behavior.

## Safety and modeling limitations to retain in explanations

Historical prices do not predict future moves. OHLC and per-bar spread do not reveal intrabar path, unobserved spread spikes, swap, liquidity, slippage, broker execution, gaps, retained positions before the test starts, or robot decision logic. Peak-to-trough stress is not an equity-curve backtest. A broker's point value, point size, currency conversion, minimum lot and volume step must be correct. No simulated cap prevents losses from exceeding the prop limit in live conditions.
