"""
Unit and Integration Tests for Aluminum Melter Heating Curve Optimizer (Alloy & Air-Fuel Ratio Aware).
"""

import os
import unittest

import pandas as pd
import numpy as np

from src.physics_model import (
    MelterPhysicsModel, get_alloy_props, ALLOY_PROPERTIES,
    load_calibrated_defaults, _CALIBRATED_CONSTANTS_PATH,
)
from src.optimizer import HeatingCurveOptimizer
from src.data_loader import (
    load_sensor_csv, load_production_excel, merge_sensor_and_heats, extract_heat_summaries,
    filter_heat_outliers, compute_heat_yield_loss,
)
from src.evaluator import MelterEvaluator


def test_alloy_properties_and_enthalpy():
    model = MelterPhysicsModel()
    props_5052 = get_alloy_props('5052')
    assert props_5052['dross_mult'] == 1.8

    props_5182 = get_alloy_props('5182')
    assert props_5182['dross_mult'] == 2.2

    res_5052 = model.calculate_theoretical_energy(65000.0, alloy_name='5052')
    res_6061 = model.calculate_theoretical_energy(65000.0, alloy_name='6061')
    assert res_5052['theoretical_gas_nm3'] > 1000.0
    assert res_6061['theoretical_gas_nm3'] > 1000.0


def test_5083_alloy_family_lookup():
    # 5083 is the single most-produced alloy family in the real MFA production log
    # (~31% of heats across 5083A/5083L/5083S) but was previously missing from
    # ALLOY_PROPERTIES and silently fell back to 'DEFAULT'.
    base = get_alloy_props('5083')
    assert base is not ALLOY_PROPERTIES['DEFAULT']
    for variant in ['5083A', '5083L', '5083S']:
        assert get_alloy_props(variant) == base
    # More Mg-rich than 5052, so it should dross faster.
    assert base['dross_mult'] > get_alloy_props('5052')['dross_mult']


def test_air_fuel_ratio_and_flue_o2():
    model = MelterPhysicsModel()
    o2_15 = model.calculate_flue_oxygen_pct(15.0)
    assert 2.0 <= o2_15 <= 3.0

    eff_10 = model.combustion_efficiency(1150.0, excess_air_pct=10.0)
    eff_25 = model.combustion_efficiency(1150.0, excess_air_pct=25.0)
    assert eff_10 > eff_25  # Lower excess air gives higher flame efficiency


def test_calibrated_defaults_respected_and_overridable():
    calibrated = load_calibrated_defaults()  # {} if calibration hasn't been run
    model_default = MelterPhysicsModel()
    if calibrated:
        assert model_default.efficiency_scale == calibrated.get('efficiency_scale', 1.0)
        assert model_default.burnoff_k0 == calibrated.get('burnoff_k0', model_default.burnoff_k0)
    # Explicit constructor args must always win over calibrated/default values.
    model_override = MelterPhysicsModel(efficiency_scale=0.77, burnoff_k0=0.11)
    assert model_override.efficiency_scale == 0.77
    assert model_override.burnoff_k0 == 0.11


def test_optimizer_alloy_and_burner_simulation():
    opt = HeatingCurveOptimizer()
    df_sim, summary = opt.simulate_trajectory(
        charged_weight_kg=65000.0,
        target_duration_hrs=6.0,
        sp_roof_melt=1150.0,
        t_switch_hrs=4.0,
        sp_roof_hold=950.0,
        alloy_name='5052',
        excess_air_pct=12.5
    )
    assert not df_sim.empty
    assert 'burner_mode' in df_sim.columns
    assert 'flue_o2_pct' in df_sim.columns
    assert summary['cum_gas_nm3'] > 1000.0


def test_optimizer_alloy_optimization():
    opt = HeatingCurveOptimizer()
    res_5052 = opt.optimize_heating_curve(65000.0, 6.0, alloy_name='5052')
    assert 'optimal_params' in res_5052
    assert res_5052['optimal_params']['excess_air_pct'] >= 10.0
    assert res_5052['savings']['cost_savings_twd'] > 0.0


def test_residual_heel_reduces_gas_for_same_total_furnace_mass():
    # Field practice: ~5-10t of hot residual metal (前爐殘湯) is left in the furnace from the
    # previous heat on top of the fresh charge. For the SAME total furnace mass, having part
    # of it already hot (near liquidus) should require less new gas than starting it all cold.
    opt = HeatingCurveOptimizer()
    all_cold = opt.optimize_heating_curve(65000.0, 6.0, alloy_name='5052', residual_weight_kg=0.0)
    with_residual = opt.optimize_heating_curve(58000.0, 6.0, alloy_name='5052', residual_weight_kg=7000.0)
    assert with_residual['optimal_summary']['cum_gas_nm3'] < all_cold['optimal_summary']['cum_gas_nm3']
    assert with_residual['deadline_met'] is True

    # A hot residual heel gives the bath a warmer starting point than an all-cold charge.
    df_cold, _ = opt.simulate_trajectory(
        65000.0, 6.0, 1150.0, 4.0, 950.0, alloy_name='5052', excess_air_pct=12.5, residual_weight_kg=0.0,
    )
    df_hot, _ = opt.simulate_trajectory(
        65000.0, 6.0, 1150.0, 4.0, 950.0, alloy_name='5052', excess_air_pct=12.5, residual_weight_kg=7000.0,
    )
    assert df_hot['bath_temp_c'].iloc[0] > df_cold['bath_temp_c'].iloc[0]


def test_deadline_constraint_never_missed_when_feasible():
    # With a generous deadline for a normal charge, the optimizer must return a schedule
    # that actually reaches target temperature by then -- the deadline is a hard constraint,
    # not an incidental filter.
    opt = HeatingCurveOptimizer()
    res = opt.optimize_heating_curve(60000.0, 8.0, alloy_name='6061', target_bath_temp_c=720.0)
    assert res['deadline_met'] is True
    assert res['optimal_summary']['final_bath_temp_c'] >= 720.0 - 5.0
    assert res['discharge_deadline_hrs'] == 8.0


def test_evaluator_optimal_never_worse_than_real_gas_on_sensor_week():
    # Regression test for the core bug found while calibrating this tool: before the fix,
    # the "optimal" schedule used ~75% MORE gas than the real historical heats it was
    # supposedly improving on. Optimal replayed gas usage must not exceed real usage.
    evaluator = MelterEvaluator()
    df_bt, summary = evaluator.run_backtest_on_sensor_week(dt_mins=5.0)
    assert summary['total_heats_analyzed'] > 0
    assert summary['total_opt_gas_nm3'] <= summary['total_real_gas_nm3']
    # Sanity bound on the improvement magnitude -- catches a badly broken calibration in
    # either direction (e.g. near-zero simulated gas, or no improvement at all).
    assert 0.0 <= summary['gas_delta_pct'] <= 70.0


def test_data_loader_real_ground_truth_extraction():
    df_raw = load_production_excel()
    assert len(df_raw) > 100
    assert {'tapped_weight_kg', 'carry_in_residual_kg'}.issubset(df_raw.columns)

    df_filtered = filter_heat_outliers(df_raw)
    assert 0 < len(df_filtered) < len(df_raw)
    assert df_filtered['melt_duration_hrs'].max() <= 24.0

    df_yield = compute_heat_yield_loss(df_raw)
    valid_pct = df_yield['yield_loss_pct'].dropna()
    assert len(valid_pct) > 50
    # Real per-heat yield loss should be a small, physically plausible percentage.
    assert valid_pct.median() < 5.0


def test_data_loader_and_sensor_summaries():
    df_sensor = load_sensor_csv()
    df_heats = load_production_excel()
    df_merged = merge_sensor_and_heats(df_sensor, df_heats)
    summaries = extract_heat_summaries(df_merged)
    assert not summaries.empty
    assert 'gas_integrated_nm3' in summaries.columns
    assert (summaries['gas_integrated_nm3'] > 0).all()
