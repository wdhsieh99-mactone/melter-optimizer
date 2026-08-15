"""
Tests for the regenerator bed thermal sub-model (src/regenerator_model.py).

Covers: recovering known synthetic parameters (validates the fitting math itself), the
t_high/t_low canonicalization fix, real-data regression guards for the empirical findings that
justify this whole sub-model (pair anti-correlation, ~240s period), and -- most importantly --
that the health index actually flags a degraded regenerator bed against a real calibrated
baseline.
"""

import numpy as np
import pandas as pd
import pytest

from src.regenerator_model import (
    PAIR_1_TAGS, PAIR_2_TAGS, DEFAULT_PERIOD_S, SAMPLE_INTERVAL_S,
    _bed_temp_curve, fit_bed_temperature, fit_window, is_actively_cycling,
    estimate_period, summarize_baseline, scan_healthy_baseline,
    regenerator_health_index, save_baseline, load_baseline,
)
from src.data_loader import load_sensor_csv


def _synthetic_series(t_high, t_low, tau_d, tau_c, phase, period, n_cycles=6, noise=0.5, seed=0):
    rng = np.random.default_rng(seed)
    t = np.arange(0, n_cycles * period, SAMPLE_INTERVAL_S)
    clean = _bed_temp_curve(t, t_high, t_low, tau_d, tau_c, phase, period)
    return t, clean + rng.normal(0.0, noise, size=len(t))


def test_fit_recovers_known_synthetic_parameters():
    t, y = _synthetic_series(t_high=160.0, t_low=90.0, tau_d=50.0, tau_c=60.0, phase=10.0, period=DEFAULT_PERIOD_S)
    fit = fit_bed_temperature(t, y, tag='synthetic')
    assert fit.r_squared > 0.998
    assert fit.t_high_c == pytest.approx(160.0, abs=1.0)
    assert fit.t_low_c == pytest.approx(90.0, abs=1.0)
    assert fit.tau_discharge_s == pytest.approx(50.0, rel=0.05)
    assert fit.tau_charge_s == pytest.approx(60.0, rel=0.05)


def test_canonicalization_always_yields_t_high_above_t_low():
    # Same physical curve, phase-shifted by half a period -- equivalent to the "swapped
    # labeling" case that motivated the canonicalization fix.
    t1, y1 = _synthetic_series(t_high=150.0, t_low=80.0, tau_d=45.0, tau_c=45.0, phase=0.0, period=DEFAULT_PERIOD_S, seed=1)
    t2, y2 = _synthetic_series(t_high=150.0, t_low=80.0, tau_d=45.0, tau_c=45.0, phase=DEFAULT_PERIOD_S / 2.0, period=DEFAULT_PERIOD_S, seed=2)

    fit1 = fit_bed_temperature(t1, y1, tag='a')
    fit2 = fit_bed_temperature(t2, y2, tag='b')

    assert fit1.t_high_c > fit1.t_low_c
    assert fit2.t_high_c > fit2.t_low_c
    assert fit1.amplitude_c > 0
    assert fit2.amplitude_c > 0
    # Both recover the same underlying amplitude regardless of the original phase/labeling.
    assert fit1.amplitude_c == pytest.approx(fit2.amplitude_c, abs=5.0)


def test_real_data_pair_anticorrelation_matches_manual_mechanism():
    # Regression guard for the core empirical finding this whole sub-model is built on: within
    # each burner pair, one bed heats while its twin cools (manual sec. 1.4.56).
    df = load_sensor_csv()
    window = df[(df['mfa_tt201_pv'] > 1000) & (df['mfa_ft211_pv'] > 300)].iloc[:720]
    assert window['mfa_tt111_pv'].corr(window['mfa_tt112_pv']) < -0.8
    assert window['mfa_tt113_pv'].corr(window['mfa_tt114_pv']) < -0.8
    # The two pairs reverse in sync with each other.
    assert window['mfa_tt111_pv'].corr(window['mfa_tt113_pv']) > 0.8


def test_real_data_period_near_240s():
    df = load_sensor_csv()
    window = df[(df['mfa_tt201_pv'] > 1000) & (df['mfa_ft211_pv'] > 300)].iloc[:720]
    period = estimate_period(window['mfa_tt111_pv'].to_numpy())
    assert period is not None
    assert period == pytest.approx(DEFAULT_PERIOD_S, abs=30.0)


def test_is_actively_cycling_threshold():
    df_active = pd.DataFrame({'mfa_ft211_pv': [400.0, 420.0, 410.0]})
    df_idle = pd.DataFrame({'mfa_ft211_pv': [10.0, 5.0, 20.0]})
    assert is_actively_cycling(df_active) is True
    assert is_actively_cycling(df_idle) is False


def test_baseline_save_load_roundtrip(tmp_path):
    baseline = {'mfa_tt111_pv': {'amplitude_mean': 95.6, 'amplitude_std': 13.8, 'n_windows': 210}}
    path = str(tmp_path / 'baseline.json')
    save_baseline(baseline, path=path)
    loaded = load_baseline(path=path)
    assert loaded == baseline
    assert load_baseline(path=str(tmp_path / 'missing.json')) == {}


def test_health_index_flags_synthetic_degraded_bed():
    # Build a "healthy" baseline from a real, actively-firing window, then construct a
    # synthetically DEGRADED version of the same signal (amplitude collapsed to ~30% -- e.g.
    # simulating a blocked/channeled bed that can no longer swing through its normal
    # charge/discharge range) and confirm the health index actually flags it.
    df = load_sensor_csv()
    window = df[df['mfa_ft211_pv'] > 150.0].iloc[2000:2240].reset_index(drop=True)
    healthy_fits = fit_window(window)

    baseline_scan = scan_healthy_baseline(df, max_windows=40)
    baseline = summarize_baseline(baseline_scan, min_r2=0.6)
    assert 'mfa_tt111_pv' in baseline and baseline['mfa_tt111_pv']['n_windows'] >= 3

    healthy_health = regenerator_health_index(healthy_fits, baseline)
    # The window itself is drawn from the same population used to build the baseline, so it
    # should read as broadly normal (not a strict guarantee for every tag, but the point of
    # this test is the CONTRAST with the degraded case below).
    assert healthy_health['mfa_tt111_pv']['status'] in ('OK', 'WATCH')

    degraded_window = window.copy()
    center = degraded_window['mfa_tt111_pv'].mean()
    degraded_window['mfa_tt111_pv'] = center + (degraded_window['mfa_tt111_pv'] - center) * 0.25
    degraded_fits = fit_window(degraded_window)
    degraded_health = regenerator_health_index(degraded_fits, baseline)

    assert degraded_health['mfa_tt111_pv']['status'] == 'ANOMALY'
    assert degraded_health['mfa_tt111_pv']['z_amplitude'] < healthy_health['mfa_tt111_pv']['z_amplitude']
