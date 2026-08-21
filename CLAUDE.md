# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Scope

This repo is the **80T static aluminium melter heating-curve optimizer** (China Steel Aluminium MFA/MFB/MFC,
Mechatherm furnace). A parent-directory instruction file at `Dropbox\Working\CLAUDE.md` also loads in every
session here — it describes an unrelated Cantera / CRN ammonia-combustion project. Nothing in this repo
relates to it; don't go looking for `CRN_NH3.py` or `gri30.yaml`.

`README.md` covers install, entry points, the project tree, and known limitations. This file covers only
what you can't see from any single file.

## Tests

```bash
pytest tests/ -q                     # 41 tests
pytest tests/test_optimizer.py::test_phase1_latent_heat_piecewise_logic -q   # single test
```

**6 of the 41 tests require the gitignored real data files and hard-fail (`FileNotFoundError`) without them
— there are no skip guards.** `115年 MFX生產紀錄.xlsx`, `mfa_20260707-0714_wide.csv`, and
`6月份加料紀錄.xlsx` exist **only at the main checkout root**, never in a worktree (`.gitignore` excludes
`*.xlsx *.csv *.pdf *.jpg`). The same absence blocks `python -m src.calibration`, `src.evaluator`, and
`src.regenerator_model`.

From a worktree, either copy the data files in from the main checkout root, or run the data-independent
subset (verified 35/35 green):

```bash
pytest tests/ -q -k "not data_loader and not real_data and not sensor_week and not health_index"
```

## Architecture

### Data flow

`data_loader` (real Excel + 5-second SCADA CSV → per-heat ground truth: `MF本爐燃耗` gas, yield loss)
→ `calibration` (replays real heats through `simulate_trajectory` under a **fixed assumed** SP policy and
fits `efficiency_scale` / `burnoff_k0`, writing `src/calibrated_constants.json`)
→ `physics_model` + `optimizer.simulate_trajectory` (1-min timestep energy integration; `energy_to_bath_temp`
inverts enthalpy→temperature across the mushy zone)
→ `optimizer.optimize_heating_curve` (brute-force grid over sp_melt × t_switch × sp_soak × sp_hold ×
excess_air, constrained to reach `target_bath_temp_c` by the deadline)
→ `evaluator` (backtests against **real logged** gas/yield loss, deliberately *not* against
`run_baseline_scenario`'s synthetic policy — conflating those two was the original inverted-savings bug)
→ `app.py` / `app_mobile.py`.

`regenerator_model.py` is a standalone side-car (bed-health monitoring from `tt111`–`tt114`); it is not
wired into the cost model.

### Constants resolve through three tiers, and the tiers currently disagree

Read the files rather than trusting these numbers — a re-calibration changes tier 2, and P0 (below) intends
to collapse the divergence.

| Tier | Source | Applies when |
|---|---|---|
| 1 | hardcoded module fallbacks, `src/physics_model.py:32-61,121-132` | nothing else supplies the value |
| 2 | `src/calibrated_constants.json` via `load_calibrated_defaults()` (`physics_model.py:15`) | ctor arg left `None` |
| 3 | `config/furnace_parameters.json` via `src/config_manager.py` | **only `app.py` reads this** |

`app.py:336` `get_optimizer_and_evaluator()` passes config values into the ctor *and then re-forces every
one as an instance attribute* (`app.py:368-394`), overriding both lower tiers. Measured consequence:

```
CLI  (python -m src.optimizer / src.calibration):  LHV 40585   ε 0.45   flow-cap 1300
UI   (streamlit run app.py):                       LHV 37256   ε 0.85   flow-cap 880
```

ε 0.45 → 0.85 is a **1.89× change in radiant flux** (6012 kW vs 11357 kW at roof 1180 °C / bath 700 °C).
`efficiency_scale` has no key in `config/furnace_parameters.json`, so it is the only calibrated value that
survives into the app. **Numbers printed by a CLI entry point are not comparable to numbers shown in the UI.**

### Three independent construction paths, and a `**kwargs` that hides typos

`app.py:344`, `app_mobile.py:224`, `src/calibration.py:77` and `:106` each build `MelterPhysicsModel` +
`HeatingCurveOptimizer` independently. `MelterPhysicsModel.__init__` ends in `**kwargs`
(`physics_model.py:114`), which silently swallows misspelled keyword args:

```python
MelterPhysicsModel(gas_lhv_kj_nm3=37256).GAS_LHV   # -> 40585.0  (swallowed; app_mobile.py:232 does this)
MelterPhysicsModel(gas_lhv=37256).GAS_LHV          # -> 37256.0  (correct kwarg name)
```

So mobile and desktop run different fuel heating values for the same heat. When adding a constant, thread it
through all three paths — and if a kwarg "has no effect", suspect it is being eaten. `app.py` also wraps both
ctors in `try/except TypeError` fallbacks, which will mask a genuine signature error too.

### Landmines

- **`summary['cum_gas_nm3']` changes meaning mid-function.** Net melt gas before `optimizer.py:489`/`:497`,
  net + overhead after. Don't assume one quantity across the dict's lifetime.
- **`residual_error_gj` is algebraically identically zero.** `calculate_sankey_energy_balance`
  (`physics_model.py:317-334`) derives the flue terms from the input/output difference, so
  `test_phase1_sankey_strict_energy_conservation` is a tautology and cannot fail. It is not a real
  conservation guard — don't treat it as one when changing the energy balance.
- **Every `src/` module uses `try: from src.X ... except ImportError: from X ...`** so it runs both as
  `python -m src.foo` and as a bare script. Match this idiom in new modules.
- **Alloy lookup is substring-based** (`get_alloy_props`), so `5083A` / `5052KS` / `5182FA` resolve to their
  family entry. Always go through this function rather than indexing `ALLOY_PROPERTIES` directly.
- **`app.py` is behind a passcode gate** (`check_password`, `app.py:406`), overridable via the
  `MELTER_AUTH_PASSWORD` environment variable.
- **UI strings, phase names, and recipe labels are Traditional Chinese** (`'第1段: 主熔化段 (Melt)'`,
  `'Dual Pair (交替全火)'`). Some are matched on downstream — keep them stable.

## Current state of the work

This branch is mid-audit. **`PHYSICS_AUDIT_2026-08-21_FOLLOWUP.md` is the live defect list and P0 remediation
plan — read it before changing any physics.** Its P0 will unify the three construction paths, remove the
`**kwargs`, resolve an overhead double-count between calibration and the app, and force a single
re-calibration; the two sections above therefore describe a state that is intended to change.

Background reading order: `MELTER_KNOWLEDGE.md` (hardware and manual-derived facts, tag cross-reference)
→ `PLAN.md` (why the tool exists, the original bug) → `PHYSICS_AUDIT_2026-08-20.md` → the follow-up.

## Data handling

The production Excel files, SCADA CSV, the Mechatherm 40522 manual PDF, and the plant record photos are
China Steel Aluminium proprietary production data and manual-copyright content. They are gitignored by
extension. Never commit them, and never paste their raw contents into anything outbound.
