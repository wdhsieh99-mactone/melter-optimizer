"""
Data Loader Module for 80T Aluminum Melter
Handles loading, cleaning, datetime alignment, heat segmentation, and feature extraction.
"""

import pandas as pd
import numpy as np
import os
from typing import Tuple, Dict, Optional

try:
    from src.physics_model import STOICH_AIR_GAS_RATIO
except ImportError:
    from physics_model import STOICH_AIR_GAS_RATIO

DEFAULT_CSV_PATH = '/Users/mactone/Dropbox (Maestral)/Working/002-Doing/claude/melter2/mfa_20260707-0714_wide.csv'
DEFAULT_EXCEL_PROD_PATH = '/Users/mactone/Dropbox (Maestral)/Working/002-Doing/claude/melter2/115年 MFX生產紀錄.xlsx'
DEFAULT_EXCEL_CHARGE_PATH = '/Users/mactone/Dropbox (Maestral)/Working/002-Doing/claude/melter2/6月份加料紀錄.xlsx'

# Combustion air/gas flow transmitter tags per burner pair (confirmed via magnitude analysis
# of mfa_20260707-0714_wide.csv against Mechatherm manual sec. 1.3.8 burner air/gas ratio loops):
# ft210/ft214 are pair-1/pair-2 combustion AIR flows (mean ~3,950 / ~3,490, fan-flow scale);
# ft211/ft215 are pair-1/pair-2 GAS flows (mean ~259 / ~237; ratio to paired air tag ~15:1).
# The furnace O2 transmitter tag (mfa_ot104_pv / AT104) is logged as all-zero for the full
# week in this dataset, so it cannot be used to derive excess air here -- excess air must be
# derived from these flow tag ratios instead.
AIR_FLOW_TAGS = ['mfa_ft210_pv', 'mfa_ft214_pv']
GAS_FLOW_TAGS = ['mfa_ft211_pv', 'mfa_ft215_pv']


def load_sensor_csv(csv_path: str = DEFAULT_CSV_PATH) -> pd.DataFrame:
    """Loads 5-second interval sensor dataset for MFA furnace."""
    if not os.path.exists(csv_path):
        raise FileNotFoundError(f"Sensor CSV file not found: {csv_path}")
    
    df = pd.read_csv(csv_path)
    df['DateTime_parsed'] = pd.to_datetime(df['DateTime_parsed'])
    df = df.sort_values('DateTime_parsed').reset_index(drop=True)
    return df


def roc_to_dt(roc_date, time_val) -> pd.Timestamp:
    """Converts ROC date string (e.g. 115/07/07) and time string to pandas Timestamp."""
    if pd.isna(roc_date) or pd.isna(time_val):
        return pd.NaT
    parts = str(roc_date).strip().split('/')
    if len(parts) == 3:
        try:
            year = int(parts[0]) + 1911
            month = int(parts[1])
            day = int(parts[2])
            t_str = str(time_val).strip()
            return pd.to_datetime(f"{year:04d}-{month:02d}-{day:02d} {t_str}", errors='coerce')
        except (ValueError, TypeError):
            return pd.NaT
    return pd.NaT


def load_production_excel(excel_path: str = DEFAULT_EXCEL_PROD_PATH, sheet_name: str = 'MFA') -> pd.DataFrame:
    """Loads batch production log Excel sheet and parses datetime intervals for each heat."""
    if not os.path.exists(excel_path):
        raise FileNotFoundError(f"Production Excel file not found: {excel_path}")
    
    df_raw = pd.read_excel(excel_path, sheet_name=sheet_name)
    
    # Filter valid heat entries
    df_valid = df_raw.dropna(subset=['爐號', 'MF加料開始日期']).copy()
    
    records = []
    for _, r in df_valid.iterrows():
        roc_d = str(r['MF加料開始日期']).strip()
        if not (roc_d.startswith('114/') or roc_d.startswith('115/')):
            continue
            
        c_start = roc_to_dt(roc_d, r['MF加料開始時間'])
        c_end = roc_to_dt(roc_d, r['MF加料結束時間'])
        t_start = roc_to_dt(roc_d, r['MF移湯開始時間'])
        t_end = roc_to_dt(roc_d, r['MF移湯結束時間'])
        
        if pd.isna(c_start):
            continue
            
        if not pd.isna(c_end) and c_end < c_start:
            c_end += pd.Timedelta(days=1)
        if not pd.isna(t_start) and t_start < c_start:
            t_start += pd.Timedelta(days=1)
        if not pd.isna(t_end) and not pd.isna(t_start) and t_end < t_start:
            t_end += pd.Timedelta(days=1)
            
        records.append({
            'heat_id': str(r['爐號']).strip(),
            'alloy': str(r['鋁種']).strip(),
            'charged_weight_kg': float(r['MF加料總重']) if not pd.isna(r['MF加料總重']) else np.nan,
            'gas_logged_nm3': float(r['MF本爐燃耗']) if not pd.isna(r['MF本爐燃耗']) else np.nan,
            'melt_duration_hrs': float(r['MF熔化總耗時(時)']) if not pd.isna(r['MF熔化總耗時(時)']) else np.nan,
            'melt_speed_tph': float(r['MF熔解速度(Ton/Hr)']) if not pd.isna(r['MF熔解速度(Ton/Hr)']) else np.nan,
            'tapped_weight_kg': float(r['移湯量']) if '移湯量' in r and not pd.isna(r['移湯量']) else np.nan,
            'carry_in_residual_kg': float(r['前爐餘湯']) if '前爐餘湯' in r and not pd.isna(r['前爐餘湯']) else np.nan,
            'c_start': c_start,
            'c_end': c_end,
            't_start': t_start,
            't_end': t_end,
        })

    df_heats = pd.DataFrame(records)
    return df_heats.sort_values('c_start').reset_index(drop=True)


def compute_heat_yield_loss(
    df_heats: pd.DataFrame,
    min_denom_kg: float = 10000.0,
    plausible_pct_bounds: Tuple[float, float] = (-2.0, 20.0),
) -> pd.DataFrame:
    """Computes real per-heat metal yield loss (kg) from charge/tap/residual weights.

    yield_loss = charged_weight + carry_in_residual (metal already in furnace from the
    previous heat) - tapped_weight - residual_out (metal left in furnace for the next heat,
    read from the *next* heat's carry_in_residual since the sheet is one row per heat in
    furnace sequence). This gives a real, plant-measured melt-loss figure (oxidation/dross)
    to calibrate the physics model's dross burn-off constants against, instead of relying on
    an assumed industrial yield-loss percentage.

    Computed on the FULL (unfiltered) sequence first, since residual_out depends on the next
    row in furnace order -- filtering rows out beforehand would misalign consecutive heats.
    Rows with an implausible denominator (data-entry errors, e.g. charged_weight near 0) or a
    resulting yield_loss_pct outside plausible_pct_bounds are set to NaN rather than dropped,
    since a small negative loss (measurement noise) or values into the low tens of percent do
    occur, but the raw sheet also contains rows as extreme as -99,900%/+99,800% from bad data.
    """
    df = df_heats.copy().reset_index(drop=True)
    df['residual_out_kg'] = df['carry_in_residual_kg'].shift(-1)
    df['yield_loss_kg'] = (
        df['charged_weight_kg'] + df['carry_in_residual_kg'].fillna(0.0)
        - df['tapped_weight_kg'] - df['residual_out_kg']
    )
    denom = df['charged_weight_kg'] + df['carry_in_residual_kg'].fillna(0.0)
    raw_pct = np.where(denom >= min_denom_kg, df['yield_loss_kg'] / denom * 100.0, np.nan)
    plausible = (raw_pct >= plausible_pct_bounds[0]) & (raw_pct <= plausible_pct_bounds[1])
    df['yield_loss_pct'] = np.where(plausible, raw_pct, np.nan)
    return df


def filter_heat_outliers(
    df_heats: pd.DataFrame,
    weight_bounds: Tuple[float, float] = (10000.0, 90000.0),
    duration_bounds: Tuple[float, float] = (1.0, 24.0),
    gas_iqr_k: float = 3.0,
) -> pd.DataFrame:
    """Removes clearly-invalid rows (bad data entry, not real heats) before using the
    production log for calibration/backtesting. The raw sheet contains rows such as a
    2,178-hour 'duration' and a 54.7 t/hr 'melt rate' that are not physically real heats.
    Weight/duration use plant-plausible absolute bounds (furnace nameplate is 80T);
    gas usage uses an IQR-based bound since 'reasonable gas usage' scales with weight/alloy.
    """
    df = df_heats.copy()
    mask = (
        df['charged_weight_kg'].between(*weight_bounds)
        & df['melt_duration_hrs'].between(*duration_bounds)
    )
    df = df[mask]

    gas = df['gas_logged_nm3'].dropna()
    if len(gas) >= 4:
        q1, q3 = gas.quantile(0.25), gas.quantile(0.75)
        iqr = q3 - q1
        low, high = q1 - gas_iqr_k * iqr, q3 + gas_iqr_k * iqr
        df = df[df['gas_logged_nm3'].isna() | df['gas_logged_nm3'].between(low, high)]

    return df.reset_index(drop=True)


def compute_actual_excess_air_pct(df_sensor: pd.DataFrame) -> pd.Series:
    """Best-effort, DIRECTIONAL-ONLY estimate of excess-air % from combustion air/gas flow
    transmitter tags (see AIR_FLOW_TAGS/GAS_FLOW_TAGS above).

    CAVEAT (do not treat this as a calibrated absolute value): even during confirmed
    high-fire periods (top quartile of gas flow) this formula yields ~35-50% excess air
    against these tags, well above the manual's ~15-17% design/setpoint range (15% max at
    high fire; the default 3% O2 trim setpoint implies ~17% via
    physics_model.calculate_flue_oxygen_pct's inverse). This mismatch could mean the
    ft210/ft214-vs-ft211/ft215 pairing assumed here is wrong, the air/gas meters aren't on a
    directly comparable basis, or some other scaling issue -- it cannot be resolved from this
    CSV alone because the furnace O2 transmitter (mfa_ot104_pv / AT104) is logged as constant
    zero for the whole week, so there is no ground truth to cross-check against.

    Given this, callers should use this series only as a *relative/trend* signal (e.g. did the
    ratio go up or down between two periods), never as an absolute excess-air % for cost or O2
    calculations -- those should keep using excess_air_pct as a physics-model decision
    variable/search input, not this derived estimate.
    """
    air_flow = df_sensor[AIR_FLOW_TAGS].sum(axis=1)
    gas_flow = df_sensor[GAS_FLOW_TAGS].sum(axis=1)
    ratio = np.where(gas_flow > 1.0, air_flow / gas_flow, np.nan)
    return pd.Series((ratio / STOICH_AIR_GAS_RATIO - 1.0) * 100.0, index=df_sensor.index)


def merge_sensor_and_heats(df_sensor: pd.DataFrame, df_heats: pd.DataFrame) -> pd.DataFrame:
    """Annotates sensor DataFrame with heat ID and operational phase."""
    df_merged = df_sensor.copy()
    df_merged['heat_id'] = pd.Series(dtype='object')
    df_merged['alloy'] = pd.Series(dtype='object')
    df_merged['charged_weight_kg'] = pd.Series(dtype='float64')
    df_merged['phase'] = 'Idle'
    df_merged['excess_air_pct_actual'] = compute_actual_excess_air_pct(df_merged)
    
    for _, heat in df_heats.iterrows():
        c_start = heat['c_start']
        c_end = heat['c_end']
        t_start = heat['t_start']
        t_end = heat['t_end']
        
        if pd.isna(c_start) or pd.isna(t_end):
            continue
            
        mask_heat = (df_merged['DateTime_parsed'] >= c_start) & (df_merged['DateTime_parsed'] <= t_end)
        df_merged.loc[mask_heat, 'heat_id'] = heat['heat_id']
        df_merged.loc[mask_heat, 'alloy'] = heat['alloy']
        df_merged.loc[mask_heat, 'charged_weight_kg'] = heat['charged_weight_kg']
        
        # Segment phases
        if not pd.isna(c_end):
            mask_charge = (df_merged['DateTime_parsed'] >= c_start) & (df_merged['DateTime_parsed'] < c_end)
            df_merged.loc[mask_charge, 'phase'] = 'Charging'
            
        if not pd.isna(c_end) and not pd.isna(t_start):
            mask_melt = (df_merged['DateTime_parsed'] >= c_end) & (df_merged['DateTime_parsed'] < t_start)
            df_merged.loc[mask_melt, 'phase'] = 'Melt'
            
        if not pd.isna(t_start) and not pd.isna(t_end):
            mask_tap = (df_merged['DateTime_parsed'] >= t_start) & (df_merged['DateTime_parsed'] <= t_end)
            df_merged.loc[mask_tap, 'phase'] = 'TapOut'
            
    return df_merged


def extract_heat_summaries(df_merged: pd.DataFrame) -> pd.DataFrame:
    """Aggregates metrics for each heat from the merged sensor dataset."""
    valid_merged = df_merged.dropna(subset=['heat_id']).copy()
    
    summaries = []
    for heat_id, group in valid_merged.groupby('heat_id'):
        start_time = group['DateTime_parsed'].min()
        end_time = group['DateTime_parsed'].max()
        duration_hrs = (end_time - start_time).total_seconds() / 3600.0
        
        melt_group = group[group['phase'] == 'Melt']
        if melt_group.empty:
            melt_group = group
            
        # Both burner pairs' gas transmitters (ft211 + ft215), see GAS_FLOW_TAGS.
        gas_integrated = group[GAS_FLOW_TAGS].sum(axis=1).sum() * 5.0 / 3600.0  # Nm3, 5s interval
        peak_roof_temp = group['mfa_tt201_pv'].max()
        avg_roof_temp = melt_group['mfa_tt201_pv'].mean()
        max_bath_temp = group['mfa_tt200_pv'].max()
        avg_pressure = group['mfa_pt209_pv'].mean()
        avg_excess_air_pct_actual = melt_group['excess_air_pct_actual'].mean()

        summaries.append({
            'heat_id': heat_id,
            'alloy': group['alloy'].iloc[0],
            'charged_weight_kg': group['charged_weight_kg'].iloc[0],
            'start_time': start_time,
            'end_time': end_time,
            'duration_hrs': round(duration_hrs, 2),
            'gas_integrated_nm3': round(gas_integrated, 1),
            'peak_roof_temp_c': round(peak_roof_temp, 1),
            'avg_melt_roof_temp_c': round(avg_roof_temp, 1),
            'max_bath_temp_c': round(max_bath_temp, 1),
            'avg_pressure_mbar': round(avg_pressure, 3),
            'avg_excess_air_pct_actual': round(avg_excess_air_pct_actual, 2) if pd.notna(avg_excess_air_pct_actual) else np.nan,
        })
        
    return pd.DataFrame(summaries)


if __name__ == '__main__':
    print("Testing data_loader.py...")
    df_sensor = load_sensor_csv()
    df_heats = load_production_excel()
    df_merged = merge_sensor_and_heats(df_sensor, df_heats)
    summaries = extract_heat_summaries(df_merged)
    print(f"Loaded {len(df_sensor)} sensor rows, {len(df_heats)} heats, {len(summaries)} heat summaries.")
    print(summaries.head())
