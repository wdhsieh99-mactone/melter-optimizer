"""
Calibration Routine for the 80T Aluminum Melter Physics Model.

Fits the physics model's free engineering-assumption constants (wall_loss_kw,
combustion_efficiency's efficiency_scale, burnoff_k0) against real production data from
`115年 MFX生產紀錄.xlsx`, and persists them to calibrated_constants.json so
MelterPhysicsModel picks them up by default (see physics_model.load_calibrated_defaults()).

Scope / honesty note: we do NOT know the real historical roof-setpoint schedule or excess-air
trajectory each heat actually ran (the plant doesn't log that in this data, and the sensor
CSV's flow-tag-derived excess air is directional-only -- see MELTER_KNOWLEDGE.md / PLAN.md
addendum). So calibration replays each real heat's (charged_weight, alloy, real duration)
through simulate_trajectory() using the SAME fixed policy as run_baseline_scenario()
(roof melt SP 1100C -> switch at 90% duration -> roof hold SP 1020C, 25% excess air), and fits
constants so that policy's simulated gas usage matches the real logged gas usage. This is a
reasonable, defensible simplification given the data available, but it means the fitted
constants describe "the furnace under something like this generic policy", not a precise
per-heat replay. burnoff_ea (Arrhenius activation energy) is left at its engineering-assumption
default -- identifying it reliably would need multiple heats spanning distinct temperature
regimes with known trajectories, which this aggregate per-heat data doesn't provide.
"""

import json
import os
import numpy as np
import pandas as pd
from scipy.optimize import least_squares

try:
    from src.data_loader import load_production_excel, filter_heat_outliers, compute_heat_yield_loss
    from src.physics_model import MelterPhysicsModel, _CALIBRATED_CONSTANTS_PATH
    from src.optimizer import HeatingCurveOptimizer
except ImportError:
    from data_loader import load_production_excel, filter_heat_outliers, compute_heat_yield_loss
    from physics_model import MelterPhysicsModel, _CALIBRATED_CONSTANTS_PATH
    from optimizer import HeatingCurveOptimizer

# Fixed replay policy mirroring HeatingCurveOptimizer.run_baseline_scenario() defaults.
REPLAY_ROOF_SP_MELT = 1100.0
REPLAY_ROOF_SP_HOLD = 1020.0
REPLAY_EXCESS_AIR_PCT = 25.0
REPLAY_SWITCH_FRACTION = 0.90

BURNOFF_EA_DEFAULT = 45000.0  # J/mol; not independently identifiable from this dataset


def build_calibration_dataset(sample_n: int = 120, random_state: int = 42) -> pd.DataFrame:
    """Real, outlier-filtered per-heat data (weight/duration/gas/yield-loss) to calibrate
    against. Downsampled (stratified by alloy) to keep the repeated-simulation fit tractable."""
    df_raw = load_production_excel()
    df_yield = compute_heat_yield_loss(df_raw)[['heat_id', 'yield_loss_pct']]

    df = filter_heat_outliers(df_raw)
    df = df.merge(df_yield, on='heat_id', how='left')
    df = df.dropna(subset=['charged_weight_kg', 'melt_duration_hrs', 'alloy'])

    if len(df) > sample_n:
        frac = sample_n / len(df)
        parts = [
            g.sample(max(1, int(round(len(g) * frac))), random_state=random_state)
            for _, g in df.groupby('alloy')
        ]
        df = pd.concat(parts, ignore_index=True)
    return df.reset_index(drop=True)


# wall_loss_kw is held fixed at this engineering-assumption value rather than fitted: a
# 2-parameter fit (wall_loss_kw + efficiency_scale) against 1-D total-gas-per-heat data is
# underdetermined -- many (wall_loss, efficiency_scale) pairs give near-identical totals, and
# an earlier attempt saw wall_loss_kw run straight to its search-bound artifact. Fitting only
# efficiency_scale keeps the calibration to one well-identified free parameter.
FIXED_WALL_LOSS_KW = 250.0


def _simulate_gas_nm3(row: pd.Series, wall_loss_kw: float, efficiency_scale: float, dt_mins: float) -> float:
    duration_hrs = max(float(row['melt_duration_hrs']), 1.5)
    model = MelterPhysicsModel(wall_loss_kw=wall_loss_kw, efficiency_scale=efficiency_scale)
    opt = HeatingCurveOptimizer(model)
    try:
        _, summary = opt.simulate_trajectory(
            charged_weight_kg=float(row['charged_weight_kg']),
            target_duration_hrs=duration_hrs,
            sp_roof_melt=REPLAY_ROOF_SP_MELT,
            t_switch_hrs=duration_hrs * REPLAY_SWITCH_FRACTION,
            sp_roof_hold=REPLAY_ROOF_SP_HOLD,
            alloy_name=str(row['alloy']),
            excess_air_pct=REPLAY_EXCESS_AIR_PCT,
            dt_mins=dt_mins,
        )
        return summary['cum_gas_nm3']
    except Exception:
        return np.nan


def _gas_residuals(params: np.ndarray, df: pd.DataFrame, dt_mins: float) -> np.ndarray:
    (efficiency_scale,) = params
    sims = df.apply(lambda r: _simulate_gas_nm3(r, FIXED_WALL_LOSS_KW, efficiency_scale, dt_mins), axis=1)
    valid = sims.notna() & (df['gas_logged_nm3'] > 0)
    return ((sims[valid] - df.loc[valid, 'gas_logged_nm3']) / df.loc[valid, 'gas_logged_nm3']).to_numpy()


def _simulate_dross_pct(
    row: pd.Series, burnoff_k0: float, wall_loss_kw: float, efficiency_scale: float, dt_mins: float
) -> float:
    duration_hrs = max(float(row['melt_duration_hrs']), 1.5)
    model = MelterPhysicsModel(
        wall_loss_kw=wall_loss_kw,
        efficiency_scale=efficiency_scale,
        burnoff_k0=burnoff_k0,
        burnoff_ea=BURNOFF_EA_DEFAULT,
    )
    opt = HeatingCurveOptimizer(model)
    try:
        _, summary = opt.simulate_trajectory(
            charged_weight_kg=float(row['charged_weight_kg']),
            target_duration_hrs=duration_hrs,
            sp_roof_melt=REPLAY_ROOF_SP_MELT,
            t_switch_hrs=duration_hrs * REPLAY_SWITCH_FRACTION,
            sp_roof_hold=REPLAY_ROOF_SP_HOLD,
            alloy_name=str(row['alloy']),
            excess_air_pct=REPLAY_EXCESS_AIR_PCT,
            dt_mins=dt_mins,
        )
        return summary['cum_dross_kg'] / float(row['charged_weight_kg']) * 100.0
    except Exception:
        return np.nan


def _dross_residuals(
    params: np.ndarray, df: pd.DataFrame, wall_loss_kw: float, efficiency_scale: float, dt_mins: float
) -> np.ndarray:
    burnoff_k0 = params[0]
    sims = df.apply(lambda r: _simulate_dross_pct(r, burnoff_k0, wall_loss_kw, efficiency_scale, dt_mins), axis=1)
    valid = sims.notna() & df['yield_loss_pct'].notna()
    # Absolute (percentage-point) residual, not relative -- yield_loss_pct can be near zero,
    # which would blow up a relative residual.
    return (sims[valid] - df.loc[valid, 'yield_loss_pct']).to_numpy()


def run_calibration(sample_n: int = 120, dt_mins: float = 5.0, random_state: int = 42) -> dict:
    """Fits wall_loss_kw, efficiency_scale, burnoff_k0 against real production data and
    writes calibrated_constants.json. Returns the same dict that's written to disk."""
    df = build_calibration_dataset(sample_n=sample_n, random_state=random_state)

    gas_df = df.dropna(subset=['gas_logged_nm3'])
    gas_fit = least_squares(
        _gas_residuals, x0=[1.0],
        bounds=([0.3], [2.0]),
        args=(gas_df, dt_mins),
    )
    wall_loss_kw, efficiency_scale = FIXED_WALL_LOSS_KW, float(gas_fit.x[0])

    dross_df = df.dropna(subset=['yield_loss_pct'])
    dross_fit = least_squares(
        _dross_residuals, x0=[0.45],
        bounds=([0.02], [3.0]),
        args=(dross_df, wall_loss_kw, efficiency_scale, dt_mins),
    )
    burnoff_k0 = float(dross_fit.x[0])

    sims_gas = gas_df.apply(lambda r: _simulate_gas_nm3(r, wall_loss_kw, efficiency_scale, dt_mins), axis=1)
    gas_mape_pct = float(np.mean(np.abs((sims_gas - gas_df['gas_logged_nm3']) / gas_df['gas_logged_nm3'])) * 100.0)

    sims_dross = dross_df.apply(
        lambda r: _simulate_dross_pct(r, burnoff_k0, wall_loss_kw, efficiency_scale, dt_mins), axis=1
    )
    dross_mae_pct_points = float(np.mean(np.abs(sims_dross - dross_df['yield_loss_pct'])))

    result = {
        'params': {
            'wall_loss_kw': round(wall_loss_kw, 2),  # fixed, not fitted -- see FIXED_WALL_LOSS_KW note
            'emissivity_eff': 0.45,  # not independently identifiable from aggregate gas totals alone
            'efficiency_scale': round(efficiency_scale, 4),  # fitted
            'burnoff_k0': round(burnoff_k0, 4),  # fitted
            'burnoff_ea': BURNOFF_EA_DEFAULT,
        },
        'meta': {
            'n_heats_gas_fit': int(len(gas_df)),
            'n_heats_dross_fit': int(len(dross_df)),
            'gas_mape_pct': round(gas_mape_pct, 2),
            'dross_mae_pct_points': round(dross_mae_pct_points, 2),
            'assumed_replay_policy': (
                f'roof_melt={REPLAY_ROOF_SP_MELT}C, switch={REPLAY_SWITCH_FRACTION}*duration, '
                f'roof_hold={REPLAY_ROOF_SP_HOLD}C, excess_air={REPLAY_EXCESS_AIR_PCT}% '
                '(matches run_baseline_scenario defaults; real historical SP schedules are not logged)'
            ),
            'caveat': (
                'excess-air trajectory is NOT calibrated against real data -- the sensor CSV flow-tag-'
                'derived excess air is directional-only (unusable O2 tag); see PLAN.md addendum.'
            ),
        },
    }

    with open(_CALIBRATED_CONSTANTS_PATH, 'w') as f:
        json.dump(result, f, indent=2)

    return result


if __name__ == '__main__':
    out = run_calibration()
    print(json.dumps(out, indent=2))
