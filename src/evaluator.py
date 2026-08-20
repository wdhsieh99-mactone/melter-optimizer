"""
Evaluator Module for 80T Aluminum Melter Heating Curve Optimizer.
Backtests the (calibrated) optimizer against REAL historical performance -- real logged gas
usage and real metal yield loss -- rather than against a synthetic, uncalibrated baseline.

Two backtests are provided:
- run_backtest_on_sensor_week(): the ~20 heats covered by the 5-second MFA sensor CSV, using
  real integrated gas flow from both burner pairs as ground truth. Fast (small N), and the
  most trustworthy real-gas figure available (direct flow-meter integration).
- run_backtest_on_production_log(): a larger, outlier-filtered sample from the full
  115年 MFX生產紀錄.xlsx production log, using the logged MF本爐燃耗 gas figure and real
  per-heat yield loss (see data_loader.compute_heat_yield_loss) as ground truth. Broader
  statistical coverage, coarser data.

Both compare the optimizer's recommendation against REAL historical totals, not against
optimizer.run_baseline_scenario()'s synthetic fixed-policy simulation -- conflating those two
was the root cause of the tool previously reporting large "savings" while its own "optimal"
schedule actually used MORE gas than the real heats it was supposedly improving on.
"""

import pandas as pd
import numpy as np
from typing import Dict, Tuple, Optional

try:
    from src.data_loader import (
        load_sensor_csv, load_production_excel, merge_sensor_and_heats, extract_heat_summaries,
        filter_heat_outliers, compute_heat_yield_loss,
    )
    from src.optimizer import HeatingCurveOptimizer
except ImportError:
    from data_loader import (
        load_sensor_csv, load_production_excel, merge_sensor_and_heats, extract_heat_summaries,
        filter_heat_outliers, compute_heat_yield_loss,
    )
    from optimizer import HeatingCurveOptimizer


class MelterEvaluator:
    """Historical backtester: optimizer recommendation vs. real plant performance."""

    def __init__(self, optimizer: Optional[HeatingCurveOptimizer] = None):
        self.optimizer = optimizer if optimizer is not None else HeatingCurveOptimizer()

    def run_backtest_on_sensor_week(
        self, target_bath_temp_c: float = 720.0, dt_mins: float = 1.0,
    ) -> Tuple[pd.DataFrame, Dict[str, float]]:
        """Backtests against the ~20 real heats covered by the 5-second MFA sensor CSV, using
        real integrated gas flow (both burner pairs) as ground truth."""
        df_sensor = load_sensor_csv()
        df_heats = load_production_excel()
        df_merged = merge_sensor_and_heats(df_sensor, df_heats)
        heat_summaries = extract_heat_summaries(df_merged)

        return self._backtest(
            heat_summaries.rename(columns={'gas_integrated_nm3': 'real_gas_nm3'}),
            target_bath_temp_c=target_bath_temp_c,
            weight_col='charged_weight_kg',
            duration_col='duration_hrs',
            real_gas_col='real_gas_nm3',
            real_dross_kg_col=None,
            dt_mins=dt_mins,
        )

    def run_backtest_on_production_log(
        self, sample_n: int = 40, random_state: int = 7, target_bath_temp_c: float = 720.0, dt_mins: float = 3.0,
    ) -> Tuple[pd.DataFrame, Dict[str, float]]:
        """Backtests against a larger, outlier-filtered sample of the full production log,
        using logged actual gas (MF本爐燃耗) and real per-heat yield loss as ground truth."""
        df_raw = load_production_excel()
        df_yield = compute_heat_yield_loss(df_raw)[['heat_id', 'yield_loss_kg', 'yield_loss_pct']]
        df = filter_heat_outliers(df_raw).merge(df_yield, on='heat_id', how='left')

        if len(df) > sample_n:
            df = df.sample(sample_n, random_state=random_state).reset_index(drop=True)

        return self._backtest(
            df,
            target_bath_temp_c=target_bath_temp_c,
            weight_col='charged_weight_kg',
            duration_col='melt_duration_hrs',
            real_gas_col='gas_logged_nm3',
            real_dross_kg_col='yield_loss_kg',
            dt_mins=dt_mins,
        )

    def _backtest(
        self,
        df_heats: pd.DataFrame,
        target_bath_temp_c: float,
        weight_col: str,
        duration_col: str,
        real_gas_col: str,
        real_dross_kg_col: Optional[str],
        dt_mins: float,
    ) -> Tuple[pd.DataFrame, Dict[str, float]]:
        optimizer = self.optimizer
        model = optimizer.model  # for real-vs-optimal cost pricing consistency (gas_price/aluminum_price)

        results = []
        for _, heat in df_heats.iterrows():
            weight_kg = heat[weight_col]
            duration_hrs = heat[duration_col]
            real_gas = heat[real_gas_col]
            alloy_name = str(heat['alloy']).strip()

            if pd.isna(weight_kg) or weight_kg <= 0 or pd.isna(duration_hrs) or duration_hrs <= 1.0 or pd.isna(real_gas):
                continue

            opt_res = optimizer.optimize_heating_curve(
                charged_weight_kg=float(weight_kg),
                discharge_deadline_hrs=float(duration_hrs),
                alloy_name=alloy_name,
                target_bath_temp_c=target_bath_temp_c,
                dt_mins=dt_mins,
            )
            opt_params = opt_res['optimal_params']
            opt_summary = opt_res['optimal_summary']

            real_dross_kg = heat[real_dross_kg_col] if real_dross_kg_col else np.nan
            has_real_dross = pd.notna(real_dross_kg)
            if has_real_dross:
                # Fair like-for-like: both sides include gas + dross cost.
                real_cost = real_gas * model.gas_price + real_dross_kg * model.aluminum_price
                opt_cost = opt_summary['total_cost']
            else:
                # No real dross ground truth for this dataset -- compare gas cost only on
                # both sides, rather than real(gas-only) vs. optimal(gas+dross), which would
                # unfairly penalize the optimizer for a cost component we can't verify here.
                real_cost = real_gas * model.gas_price
                opt_cost = opt_summary['gas_cost']

            results.append({
                'heat_id': heat.get('heat_id', '?'),
                'alloy': alloy_name,
                'charged_weight_kg': weight_kg,
                'duration_hrs': round(float(duration_hrs), 2),
                'real_gas_nm3': round(float(real_gas), 1),
                'opt_gas_nm3': round(opt_summary['cum_gas_nm3'], 1),
                'real_dross_kg': round(float(real_dross_kg), 2) if pd.notna(real_dross_kg) else np.nan,
                'opt_dross_kg': round(opt_summary['cum_dross_kg'], 2),
                'deadline_met': opt_res['deadline_met'],
                'opt_sp_roof_melt': opt_params['sp_roof_melt'],
                'opt_t_switch_hrs': opt_params['t_switch_hrs'],
                'opt_sp_roof_hold': opt_params['sp_roof_hold'],
                'opt_excess_air_pct': opt_params['excess_air_pct'],
                'opt_flue_o2_pct': opt_params['flue_o2_pct'],
                'real_cost_twd': round(float(real_cost), 1),
                'opt_cost_twd': round(float(opt_cost), 1),
                'cost_savings_twd': round(float(real_cost - opt_cost), 1),
            })

        df_bt = pd.DataFrame(results)
        if df_bt.empty:
            return df_bt, {'total_heats_analyzed': 0}

        total_real_gas = df_bt['real_gas_nm3'].sum()
        total_opt_gas = df_bt['opt_gas_nm3'].sum()
        total_real_cost = df_bt['real_cost_twd'].sum()
        total_opt_cost = df_bt['opt_cost_twd'].sum()

        overall = {
            'total_heats_analyzed': int(len(df_bt)),
            'total_real_gas_nm3': round(float(total_real_gas), 1),
            'total_opt_gas_nm3': round(float(total_opt_gas), 1),
            'gas_delta_nm3': round(float(total_real_gas - total_opt_gas), 1),
            'gas_delta_pct': round(float((total_real_gas - total_opt_gas) / total_real_gas * 100.0), 2) if total_real_gas > 0 else 0.0,
            'total_real_cost_twd': round(float(total_real_cost), 1),
            'total_opt_cost_twd': round(float(total_opt_cost), 1),
            'total_cost_savings_twd': round(float(total_real_cost - total_opt_cost), 1),
            'pct_heats_deadline_met': round(float(df_bt['deadline_met'].mean() * 100.0), 1),
        }
        return df_bt, overall


if __name__ == '__main__':
    evaluator = MelterEvaluator()

    print("=== Backtest vs. real sensor-week gas usage (MFA, ~20 heats) ===")
    df_sensor_bt, sensor_summary = evaluator.run_backtest_on_sensor_week()
    for k, v in sensor_summary.items():
        print(f"{k}: {v}")
    print()

    print("=== Backtest vs. real production-log gas + yield loss (sampled) ===")
    df_log_bt, log_summary = evaluator.run_backtest_on_production_log()
    for k, v in log_summary.items():
        print(f"{k}: {v}")
    print("\nSample heat results:")
    print(df_log_bt[['heat_id', 'alloy', 'real_gas_nm3', 'opt_gas_nm3', 'real_dross_kg', 'opt_dross_kg', 'deadline_met']].head(8))
