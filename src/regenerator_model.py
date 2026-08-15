"""
Regenerator Bed Thermal Sub-Model for the 80T Melter's 4-Burner 2-Pair Regenerative
Combustion System.

Grounding (see REGENERATIVE_SYSTEM_ANALYSIS.md for full derivation):
- Manual sec. 1.4.56 (C 151, 152 Regenerative Cycle Loop): "Only one burner will fire at any
  one time, its twin will be in exhaust mode drawing the furnace exhaust products through its
  regenerative bed recharging the temperature of bed media." Max firing cycle timer is
  HMI-adjustable 80-120s per half-cycle.
- The sensor CSV's mfa_tt111_pv..mfa_tt114_pv tags (previously unused, unconfirmed meaning) were
  confirmed empirically to be per-burner regenerator-bed-related temperatures: tt111/tt112 are
  anti-correlated (r=-0.96, one pair's two burners), tt113/tt114 anti-correlated (r=-0.927, the
  other pair), and tt111/tt113 positively correlated (r=+0.96, the two pairs reverse in sync).
- Across 119 clean (actively-firing) 1-hour windows spanning the full week, the full reversal
  period is extremely stable: median 240.0s, std 3.9s -- consistent with this furnace's max
  firing cycle timer being commissioned near the HMI's 120s ceiling and running on an
  effectively FIXED timer rather than the temperature-adaptive early-reversal path, at least
  under normal (non-idle) firing conditions in the observed week.
- Bed mass figures (3,680kg total, ~1,600kg media per bed) are from the manual's burner/
  regenerator description.

This module fits a periodic relay-thermal-capacitance model directly to real tt11x data: each
burner's bed temperature decays toward a "cold" asymptote while firing (giving up stored heat
to preheat combustion air) and rises toward a "hot" asymptote while exhausting (absorbing heat
from furnace exhaust gas), reversing every half-period. It is intentionally phenomenological
(fit T_high/T_low/tau directly from data) rather than deriving them from first-principles heat
transfer coefficients, which aren't independently known for this furnace.
"""

import json
import os
import numpy as np
import pandas as pd
from dataclasses import dataclass
from typing import Dict, Optional, Tuple
from scipy.optimize import curve_fit

_BASELINE_PATH = os.path.join(os.path.dirname(__file__), 'regenerator_baseline.json')

try:
    from src.data_loader import load_sensor_csv
except ImportError:
    from data_loader import load_sensor_csv

# Burner pair tag mapping confirmed via correlation analysis (see module docstring).
PAIR_1_TAGS = ('mfa_tt111_pv', 'mfa_tt112_pv')
PAIR_2_TAGS = ('mfa_tt113_pv', 'mfa_tt114_pv')
SAMPLE_INTERVAL_S = 5.0

DEFAULT_PERIOD_S = 240.0
BED_TOTAL_MASS_KG = 3680.0
BED_MEDIA_MASS_KG = 1600.0

# A window is excluded from "normal cycling" fits/health checks if the furnace isn't actively
# firing enough to produce a clean regenerative cycle (see validation: 13/132 windows with avg
# gas flow well below this were spurious/undefined, not real 240s cycling).
MIN_ACTIVE_GAS_FLOW_NM3H = 150.0

# Recommended fit window length: long enough for several full cycles (robust fit), short
# enough to stay roughly stationary (roof/bath temperature drifts over a full melt profile,
# which biases a periodic-steady-state model if the window is too long). Empirically: a 2-hour
# window gave R^2 only ~0.38-0.43 (non-stationarity dominates); a 20-minute window (~5 cycles)
# gave R^2 0.88-0.97 across all 4 beds. Use ~20-30 min windows for calibration/health checks.
RECOMMENDED_FIT_WINDOW_S = 1200.0  # 20 minutes ~= 5 cycles at the empirical 240s period


@dataclass
class RegeneratorBedFit:
    """Fitted periodic relay-thermal-capacitance parameters for one burner's bed."""
    tag: str
    t_high_c: float
    t_low_c: float
    tau_discharge_s: float
    tau_charge_s: float
    phase_s: float
    period_s: float
    r_squared: float
    n_samples: int

    @property
    def amplitude_c(self) -> float:
        return self.t_high_c - self.t_low_c


def _bed_temp_curve(t, t_high, t_low, tau_discharge, tau_charge, phase, period):
    """Periodic relay model: firing half-cycle decays T_high->T_low, exhaust half-cycle rises
    T_low->T_high, reversing every period/2."""
    local_t = np.mod(t - phase, period)
    half = period / 2.0
    firing = local_t < half
    discharge_val = t_low + (t_high - t_low) * np.exp(-local_t / tau_discharge)
    charge_val = t_high - (t_high - t_low) * np.exp(-(local_t - half) / tau_charge)
    return np.where(firing, discharge_val, charge_val)


def fit_bed_temperature(
    t_seconds: np.ndarray, temps_c: np.ndarray, tag: str = '', period_s: float = DEFAULT_PERIOD_S,
) -> RegeneratorBedFit:
    """Fits the periodic relay-thermal-capacitance model to one burner's real temperature
    series. period_s is held fixed (empirically confirmed stable, see module docstring) to
    keep the fit well-conditioned; t_high/t_low/tau_discharge/tau_charge/phase are free.

    Multi-start: (t_high, t_low, tau, phase) are only weakly identifiable from a single
    ~120s-per-half-cycle exponential segment -- a single curve_fit call can converge to a
    plausible-looking but wrong local optimum (verified: on noise-free synthetic data with
    known tau=50s, a single-start fit landed on tau=66s at R^2=0.984 instead of the true
    generator at R^2=1.0). Retrying from a small grid of phase/tau initial guesses and keeping
    the best-R^2 result fixes this without materially changing per-fit cost (still <200ms)."""
    t_seconds = np.asarray(t_seconds, dtype=float)
    temps_c = np.asarray(temps_c, dtype=float)

    t_high0 = float(np.percentile(temps_c, 95))
    t_low0 = float(np.percentile(temps_c, 5))
    bounds = (
        [t_low0 - 5.0, t_low0 - 50.0, 5.0, 5.0, -period_s],
        [t_high0 + 50.0, t_high0 + 5.0, period_s, period_s, period_s],
    )

    def model(t, t_high, t_low, tau_d, tau_c, phase):
        return _bed_temp_curve(t, t_high, t_low, tau_d, tau_c, phase, period_s)

    best_popt, best_r2 = None, -np.inf
    for phase0 in (0.0, period_s / 2.0):
        for tau0 in (20.0, 60.0, 100.0):
            p0 = [t_high0, t_low0, tau0, tau0, phase0]
            try:
                popt, _ = curve_fit(model, t_seconds, temps_c, p0=p0, bounds=bounds, maxfev=20000)
            except RuntimeError:
                continue
            pred = model(t_seconds, *popt)
            ss_res = float(np.sum((temps_c - pred) ** 2))
            ss_tot = float(np.sum((temps_c - temps_c.mean()) ** 2))
            r2_try = 1.0 - ss_res / ss_tot if ss_tot > 0 else 0.0
            if r2_try > best_r2:
                best_r2, best_popt = r2_try, popt

    if best_popt is None:
        raise RuntimeError(f"fit_bed_temperature: all multi-start attempts failed to converge for tag={tag!r}")

    popt, r2 = best_popt, best_r2
    t_high, t_low, tau_d, tau_c, phase = popt

    # Canonicalize: curve_fit's bounds don't force t_high > t_low, so the optimizer can
    # converge to the "swapped" labeling on different windows (same curve shape, but firing/
    # exhausting roles and tau_discharge/tau_charge get flipped) -- left uncorrected, this
    # mixes positive- and negative-amplitude fits across windows and badly inflates the
    # apparent variance of amplitude/tau when aggregating for a baseline. Swapping
    # (t_high<->t_low, tau_d<->tau_c, phase+=period/2) yields an identical fitted curve (same
    # R^2) under a consistent t_high > t_low convention.
    if t_high < t_low:
        t_high, t_low = t_low, t_high
        tau_d, tau_c = tau_c, tau_d
        phase = phase + period_s / 2.0

    return RegeneratorBedFit(
        tag=tag, t_high_c=float(t_high), t_low_c=float(t_low),
        tau_discharge_s=float(tau_d), tau_charge_s=float(tau_c),
        phase_s=float(phase % period_s), period_s=period_s,
        r_squared=r2, n_samples=len(t_seconds),
    )


def is_actively_cycling(df_window: pd.DataFrame, gas_tag: str = 'mfa_ft211_pv') -> bool:
    """True if the window's average gas flow is high enough to expect a clean regenerative
    cycle (see MIN_ACTIVE_GAS_FLOW_NM3H derivation in module docstring)."""
    return bool(df_window[gas_tag].mean() >= MIN_ACTIVE_GAS_FLOW_NM3H)


def estimate_period(temps_c: np.ndarray, min_amplitude: float = 5.0) -> Optional[float]:
    """Formalizes the peak-detection method used to empirically confirm DEFAULT_PERIOD_S: a
    long (10-minute) rolling-mean detrend followed by local-maxima detection, returning the
    median peak-to-peak spacing in seconds. Returns None if fewer than 3 clean peaks are found
    (e.g. an idle/low-fire window with no real cycling -- see is_actively_cycling)."""
    x = np.asarray(temps_c, dtype=float)
    long_ma = pd.Series(x).rolling(120, center=True, min_periods=1).mean().to_numpy()
    xd = x - long_ma
    peaks = []
    for i in range(2, len(xd) - 2):
        if xd[i] > xd[i - 1] and xd[i] > xd[i - 2] and xd[i] > xd[i + 1] and xd[i] > xd[i + 2] and xd[i] > min_amplitude:
            peaks.append(i)
    clean = []
    for p in peaks:
        if not clean or p - clean[-1] > 4:
            clean.append(p)
    if len(clean) < 3:
        return None
    return float(np.median(np.diff(clean)) * SAMPLE_INTERVAL_S)


def save_baseline(baseline_stats: Dict[str, Dict[str, float]], path: str = _BASELINE_PATH) -> None:
    with open(path, 'w') as f:
        json.dump(baseline_stats, f, indent=2)


def load_baseline(path: str = _BASELINE_PATH) -> Dict[str, Dict[str, float]]:
    """Returns {} if no baseline has been calibrated yet (run `python -m src.regenerator_model`)."""
    if not os.path.exists(path):
        return {}
    try:
        with open(path, 'r') as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def fit_window(df_window: pd.DataFrame, period_s: float = DEFAULT_PERIOD_S) -> Dict[str, RegeneratorBedFit]:
    """Fits all 4 burner beds (mfa_tt111_pv..mfa_tt114_pv) over a given sensor data window.
    df_window must have a 'DateTime_parsed' column and the 4 tt11x tag columns."""
    t0 = df_window['DateTime_parsed'].iloc[0]
    t_seconds = (df_window['DateTime_parsed'] - t0).dt.total_seconds().to_numpy()

    fits = {}
    for tag in [*PAIR_1_TAGS, *PAIR_2_TAGS]:
        fits[tag] = fit_bed_temperature(t_seconds, df_window[tag].to_numpy(), tag=tag, period_s=period_s)
    return fits


def pair_symmetry_error(fit_a: RegeneratorBedFit, fit_b: RegeneratorBedFit) -> Dict[str, float]:
    """Quantifies how symmetric a pair's two burners are. CAVEAT from the baseline scan: real
    "healthy" pairs are NOT perfectly symmetric -- across the full week, tt111 (amplitude
    ~95.6C) consistently ran a noticeably larger swing than its twin tt112 (~76.2C), likely
    as-built asymmetry (piping/orientation/sensor placement), not a fault. So this raw
    difference is NOT by itself a reliable anomaly signal -- use regenerator_health_index()
    (which compares each burner against ITS OWN calibrated baseline) for anomaly detection;
    this function is a supplementary diagnostic, best read as a trend (has the gap changed from
    its own historical norm?) rather than an absolute "should be ~0" expectation."""
    return {
        'amplitude_diff_c': abs(fit_a.amplitude_c - fit_b.amplitude_c),
        'tau_discharge_diff_s': abs(fit_a.tau_discharge_s - fit_b.tau_discharge_s),
        'tau_charge_diff_s': abs(fit_a.tau_charge_s - fit_b.tau_charge_s),
        'mean_level_diff_c': abs(
            (fit_a.t_high_c + fit_a.t_low_c) / 2.0 - (fit_b.t_high_c + fit_b.t_low_c) / 2.0
        ),
    }


def scan_healthy_baseline(
    df: Optional[pd.DataFrame] = None,
    window_s: float = RECOMMENDED_FIT_WINDOW_S,
    max_windows: Optional[int] = None,
) -> pd.DataFrame:
    """Slides non-overlapping windows across the full sensor CSV, fits every actively-firing
    window, and returns one row per (window, tag) fit. This is the calibration pass that
    establishes what "healthy" cycling looks like -- aggregate statistics from this become the
    baseline that regenerator_health_index() compares live/new data against."""
    if df is None:
        df = load_sensor_csv()

    win_samples = int(round(window_s / SAMPLE_INTERVAL_S))
    rows = []
    n_windows = 0
    for start in range(0, len(df) - win_samples, win_samples):
        seg = df.iloc[start:start + win_samples].reset_index(drop=True)
        if not is_actively_cycling(seg):
            continue
        try:
            fits = fit_window(seg)
        except RuntimeError:
            continue  # curve_fit failed to converge on this window -- skip, don't crash the scan
        for tag, f in fits.items():
            rows.append({
                'window_start': seg['DateTime_parsed'].iloc[0], 'tag': tag,
                'amplitude_c': f.amplitude_c, 'tau_discharge_s': f.tau_discharge_s,
                'tau_charge_s': f.tau_charge_s, 'r_squared': f.r_squared,
                'mean_level_c': (f.t_high_c + f.t_low_c) / 2.0,
            })
        n_windows += 1
        if max_windows is not None and n_windows >= max_windows:
            break

    return pd.DataFrame(rows)


def summarize_baseline(df_scan: pd.DataFrame, min_r2: float = 0.7) -> Dict[str, Dict[str, float]]:
    """Aggregates a scan_healthy_baseline() result into per-tag mean/std reference stats, only
    using well-fit windows (r_squared >= min_r2) so poor fits don't pollute the baseline."""
    good = df_scan[df_scan['r_squared'] >= min_r2]
    stats = {}
    for tag, g in good.groupby('tag'):
        stats[tag] = {
            'amplitude_mean': float(g['amplitude_c'].mean()), 'amplitude_std': float(g['amplitude_c'].std()),
            'tau_discharge_mean': float(g['tau_discharge_s'].mean()), 'tau_discharge_std': float(g['tau_discharge_s'].std()),
            'tau_charge_mean': float(g['tau_charge_s'].mean()), 'tau_charge_std': float(g['tau_charge_s'].std()),
            'mean_level_mean': float(g['mean_level_c'].mean()), 'mean_level_std': float(g['mean_level_c'].std()),
            'n_windows': int(len(g)),
        }
    return stats


def regenerator_health_index(
    current_fits: Dict[str, RegeneratorBedFit], baseline_stats: Dict[str, Dict[str, float]],
) -> Dict[str, Dict[str, float]]:
    """Compares a live/new window's fit against the calibrated healthy baseline. Returns a
    z-score-like deviation per tag per metric; |z| > ~2-3 flags a candidate anomaly (e.g. bed
    media degraded/blocked -> reduced amplitude and/or shifted tau on one specific burner,
    consistent with the manual's channeling/fouling failure mode -- see
    REGENERATIVE_SYSTEM_ANALYSIS.md sec.3 for the field symptom list this is meant to catch)."""
    result = {}
    for tag, fit in current_fits.items():
        base = baseline_stats.get(tag)
        if base is None:
            result[tag] = {'status': 'no_baseline'}
            continue

        def z(value, mean_key, std_key):
            std = base[std_key]
            return (value - base[mean_key]) / std if std > 1e-6 else 0.0

        mean_level_c = (fit.t_high_c + fit.t_low_c) / 2.0
        z_amp = z(fit.amplitude_c, 'amplitude_mean', 'amplitude_std')
        z_tau_d = z(fit.tau_discharge_s, 'tau_discharge_mean', 'tau_discharge_std')
        z_tau_c = z(fit.tau_charge_s, 'tau_charge_mean', 'tau_charge_std')
        z_level = z(mean_level_c, 'mean_level_mean', 'mean_level_std')
        max_abs_z = max(abs(z_amp), abs(z_tau_d), abs(z_tau_c), abs(z_level))
        result[tag] = {
            'z_amplitude': round(z_amp, 2), 'z_tau_discharge': round(z_tau_d, 2),
            'z_tau_charge': round(z_tau_c, 2), 'z_mean_level': round(z_level, 2),
            'max_abs_z': round(max_abs_z, 2),
            'status': 'ANOMALY' if max_abs_z > 3.0 else ('WATCH' if max_abs_z > 2.0 else 'OK'),
        }
    return result


if __name__ == '__main__':
    df = load_sensor_csv()

    print(f"=== Scanning full week for healthy baseline ({RECOMMENDED_FIT_WINDOW_S:.0f}s windows) ===")
    scan = scan_healthy_baseline(df)
    print(f"{len(scan) // 4} actively-cycling windows fit ({(scan['r_squared'] >= 0.7).sum()} tag-fits with R2>=0.7 of {len(scan)} total)")
    baseline = summarize_baseline(scan)
    for tag, stats in baseline.items():
        print(f"{tag}: amplitude={stats['amplitude_mean']:.1f}+/-{stats['amplitude_std']:.1f}C, "
              f"tau_discharge={stats['tau_discharge_mean']:.1f}+/-{stats['tau_discharge_std']:.1f}s, "
              f"tau_charge={stats['tau_charge_mean']:.1f}+/-{stats['tau_charge_std']:.1f}s, "
              f"n={stats['n_windows']}")
    save_baseline(baseline)
    print(f"Saved baseline to {_BASELINE_PATH}")

    print()
    print("=== Demo: health check on a single representative window against this baseline ===")
    demo_seg = df[df['mfa_ft211_pv'] > MIN_ACTIVE_GAS_FLOW_NM3H].iloc[2000:2240].reset_index(drop=True)
    demo_fits = fit_window(demo_seg)
    health = regenerator_health_index(demo_fits, baseline)
    for tag, h in health.items():
        print(tag, h)
    print()
    print("Pair 1 (111 vs 112) symmetry:", pair_symmetry_error(demo_fits[PAIR_1_TAGS[0]], demo_fits[PAIR_1_TAGS[1]]))
    print("Pair 2 (113 vs 114) symmetry:", pair_symmetry_error(demo_fits[PAIR_2_TAGS[0]], demo_fits[PAIR_2_TAGS[1]]))
