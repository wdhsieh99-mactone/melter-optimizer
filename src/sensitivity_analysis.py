"""
Sensitivity Analysis for the 80T Melter Physics Model & Optimizer.

One-at-a-time (OAT) parameter sweeps that check two things for every tunable parameter the
model exposes:
  1. DIRECTION: does the output move the way physics/field experience says it should?
  2. PLAUSIBILITY: are the resulting magnitudes consistent with the manual and real
     production data (see MELTER_KNOWLEDGE.md, PLAN.md)?

This is a diagnostic/judgment tool, not an auto-fixer: it surfaces findings (including code
issues it uncovers, like a parameter that turns out not to actually affect anything) into
SENSITIVITY_REPORT.md for a human to act on. Run as: `python -m src.sensitivity_analysis`.

Design note on WHY decision variables are swept via simulate_trajectory() directly rather than
re-running optimize_heating_curve() for every level: re-optimizing each time would let the
search re-choose OTHER variables in response, confounding the swept variable's own marginal
effect with the optimizer's re-optimization. That's the wrong experiment for isolating one
variable's effect. max_roof_sp_limit and discharge_deadline_hrs are the exception, since their
effect IS specifically on the optimizer's feasible search space / chosen optimum.
"""

import contextlib
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Sequence

import numpy as np

try:
    import src.physics_model as physics_model
    from src.physics_model import MelterPhysicsModel, get_alloy_props, ALLOY_PROPERTIES
    from src.optimizer import HeatingCurveOptimizer
except ImportError:
    import physics_model
    from physics_model import MelterPhysicsModel, get_alloy_props, ALLOY_PROPERTIES
    from optimizer import HeatingCurveOptimizer

REPORT_PATH = 'SENSITIVITY_REPORT.md'

DT_MINS_FAST = 5.0  # coarse timestep for sweep speed; fine enough for directional checks

# Baseline scenario shared by all decision-variable sweeps (a representative mid-size 5052 heat).
BASELINE_SIM = dict(
    charged_weight_kg=65000.0,
    target_duration_hrs=6.0,
    sp_roof_melt=1150.0,
    t_switch_hrs=4.0,
    sp_roof_hold=950.0,
    alloy_name='5052',
    excess_air_pct=15.0,
    target_bath_temp_c=720.0,
    residual_weight_kg=0.0,
    dt_mins=DT_MINS_FAST,
)
BASELINE_OPT = dict(
    charged_weight_kg=65000.0,
    discharge_deadline_hrs=6.0,
    alloy_name='5052',
    target_bath_temp_c=720.0,
    dt_mins=DT_MINS_FAST,
)

METRICS = ['cum_gas_nm3', 'cum_dross_kg', 'total_cost', 'final_bath_temp_c', 'flue_o2_pct']


@dataclass
class SweepResult:
    name: str
    category: str
    param_desc: str
    levels: List[Any]
    outputs: Dict[str, List[Optional[float]]]
    expected_direction: str
    observed_direction: str
    direction_match: Optional[bool]
    benchmark_note: str
    plausible: Optional[bool]
    notes: str = ""


@contextlib.contextmanager
def _patched_module_constant(attr_name: str, value: float):
    """Temporarily monkeypatches a module-level constant in physics_model (e.g. HEARTH_AREA_M2,
    GAS_LHV), used to test the TRUE physical sensitivity of formulas that read the module
    global directly rather than an instance attribute -- see the HEARTH_AREA_M2 finding in the
    report for why this distinction matters."""
    original = getattr(physics_model, attr_name)
    setattr(physics_model, attr_name, value)
    try:
        yield
    finally:
        setattr(physics_model, attr_name, original)


def _run_sim(model_kwargs=None, sim_overrides=None, instance_attr_overrides=None):
    model = MelterPhysicsModel(**(model_kwargs or {}))
    for attr, val in (instance_attr_overrides or {}).items():
        setattr(model, attr, val)
    opt = HeatingCurveOptimizer(model)
    sim_args = {**BASELINE_SIM, **(sim_overrides or {})}
    _, summary = opt.simulate_trajectory(**sim_args)
    return summary


def _trend(values: List[Optional[float]]) -> str:
    """Classifies a sequence as increasing / decreasing / flat / non-monotonic."""
    vals = [v for v in values if v is not None and np.isfinite(v)]
    if len(vals) < 2:
        return 'insufficient_data'
    diffs = np.diff(vals)
    if np.allclose(diffs, 0.0, atol=1e-6):
        return 'flat'
    if np.all(diffs >= -1e-9):
        return 'increase'
    if np.all(diffs <= 1e-9):
        return 'decrease'
    return 'non_monotonic'


def _verdict(expected: str, observed: str) -> Optional[bool]:
    if expected == 'ambiguous':
        return None
    if expected == 'non_increase':
        return observed in ('decrease', 'flat')
    if expected == 'non_decrease':
        return observed in ('increase', 'flat')
    return expected == observed


def _sweep_generic(
    name: str, category: str, param_desc: str, levels: Sequence[Any],
    run_fn: Callable[[Any], Dict[str, float]], metric: str, expected_direction: str,
    benchmark_note: str, plausible_fn: Optional[Callable[[List[float]], bool]] = None,
    notes: str = "",
) -> SweepResult:
    outputs: Dict[str, List[Optional[float]]] = {m: [] for m in METRICS}
    for lvl in levels:
        summary = run_fn(lvl)
        for m in METRICS:
            outputs[m].append(summary.get(m))
    observed = _trend(outputs[metric])
    plausible = plausible_fn(outputs[metric]) if plausible_fn else None
    return SweepResult(
        name=name, category=category, param_desc=param_desc, levels=list(levels),
        outputs=outputs, expected_direction=expected_direction, observed_direction=observed,
        direction_match=_verdict(expected_direction, observed), benchmark_note=benchmark_note,
        plausible=plausible, notes=notes,
    )


# ---------------------------------------------------------------------------
# Physics constants
# ---------------------------------------------------------------------------

def sweep_gas_lhv() -> SweepResult:
    levels = [30000.0, 36000.0, 40585.0, 45000.0, 50000.0]  # kJ/Nm3; 40585 = calibrated/manual value
    return _sweep_generic(
        'GAS_LHV', 'physics_constant', 'Natural gas heating value (kJ/Nm3), instance-overridable',
        levels, lambda lvl: _run_sim(instance_attr_overrides={'GAS_LHV': lvl}),
        'cum_gas_nm3', 'decrease',
        'Manual sec.1.3.1: 9,700 kcal/Nm3 (~40,585 kJ/Nm3). Higher LHV = same energy from fewer Nm3.',
        plausible_fn=lambda vals: all(500.0 < v < 15000.0 for v in vals if v is not None),
    )


HEARTH_AREA_DIRECTION_NOTE = (
    'IMPORTANT -- initial hypothesis of "larger area -> less gas" was WRONG for this model as '
    'currently structured, confirmed by inspecting final_bath_temp_c across the sweep: at '
    'area=30 the bath only reaches 683.5C (undershoots 720 target, not enough transfer capacity '
    'in the fixed 4h-melt/2h-hold schedule); at area=45 it lands almost exactly on 720C; at '
    'area>=66.15 it OVERSHOOTS to the hardcoded 800C clamp. Because the Melt phase adds heat '
    'unconditionally regardless of current bath temperature (`or phase == "Melt"` in '
    'optimizer.py), a MORE effective transfer geometry just delivers (and burns gas for) MORE '
    'total heat within the fixed melt duration, most of it wasted as overshoot once transfer '
    'capacity exceeds what is needed. So "increase" is the CORRECT expected direction given the '
    'current fixed-duration, non-early-terminating Melt-phase design -- not a bug in itself, but '
    'worth knowing when interpreting sensitivity results for any parameter that boosts heat '
    'transfer rate (see emissivity_eff below, same mechanism).'
)


def sweep_hearth_area_instance() -> SweepResult:
    """Tests HEARTH_AREA_M2 the way a caller would naturally try to customize it: as an
    instance attribute on MelterPhysicsModel. FIXED (see sweep_hearth_area_module_noop() for
    the regression guard): radiant_heat_flux_kw() and dross_burnoff_rate_kg_hr() now read
    self.HEARTH_AREA_M2 instead of the module-level global, so this sweep shows the FULL
    physical effect."""
    levels = [30.0, 45.0, 66.15, 90.0, 120.0]
    return _sweep_generic(
        'HEARTH_AREA_M2 (instance override)', 'physics_constant',
        'Bath radiating surface area (m^2), set via model.HEARTH_AREA_M2 = X',
        levels, lambda lvl: _run_sim(instance_attr_overrides={'HEARTH_AREA_M2': lvl}),
        'cum_gas_nm3', 'increase',
        'Manual sec.1.3.2: bath 10,500x6,300mm = 66.15 m^2. ' + HEARTH_AREA_DIRECTION_NOTE,
        plausible_fn=lambda vals: all(500.0 < v < 15000.0 for v in vals if v is not None),
        notes='FIXED: was previously an ~11x weaker response (only the convective term in '
              'optimizer.py respected this override) -- now spans the full range '
              '(area 30->120 moves cum_gas_nm3 by roughly the same magnitude as the module-level '
              'sweep used to show pre-fix), confirming radiant_heat_flux_kw() and '
              'dross_burnoff_rate_kg_hr() now correctly read self.HEARTH_AREA_M2.',
    )


def sweep_hearth_area_module_noop() -> SweepResult:
    """Regression guard for the fixed bug: patching the MODULE-level HEARTH_AREA_M2 constant
    should now have ZERO effect, since radiant_heat_flux_kw()/dross_burnoff_rate_kg_hr() read
    self.HEARTH_AREA_M2 (sourced from the class attribute, frozen at import time) rather than
    re-reading the module global at call time. If this sweep ever shows a non-flat response
    again, the direct-module-read bug has been reintroduced."""
    levels = [30.0, 45.0, 66.15, 90.0, 120.0]

    def run(lvl):
        with _patched_module_constant('HEARTH_AREA_M2', lvl):
            return _run_sim()

    return _sweep_generic(
        'HEARTH_AREA_M2 (module patch, post-fix regression guard)', 'physics_constant',
        'Bath radiating surface area (m^2) patched at module level -- should now be a no-op',
        levels, run, 'cum_gas_nm3', 'flat',
        'Post-fix expectation: formulas no longer read this module global directly, so patching '
        'it should not change simulate_trajectory() output at all.',
        plausible_fn=lambda vals: all(500.0 < v < 15000.0 for v in vals if v is not None),
    )


def sweep_wall_loss_kw() -> SweepResult:
    levels = [50.0, 150.0, 250.0, 400.0, 600.0]
    return _sweep_generic(
        'wall_loss_kw', 'physics_constant', 'Fixed standing refractory/shell heat loss (kW)',
        levels, lambda lvl: _run_sim(model_kwargs={'wall_loss_kw': lvl}),
        'cum_gas_nm3', 'increase',
        'Calibrated value: 250kW (fixed, not fitted -- see PLAN.md). Plausible range for a 66m2 '
        'industrial furnace shell: tens to low hundreds of kW.',
        plausible_fn=lambda vals: all(500.0 < v < 15000.0 for v in vals if v is not None),
    )


def sweep_emissivity_eff() -> SweepResult:
    levels = [0.20, 0.35, 0.45, 0.60, 0.80]
    return _sweep_generic(
        'emissivity_eff', 'physics_constant', 'Effective roof-to-bath radiative emissivity (0-1)',
        levels, lambda lvl: _run_sim(model_kwargs={'emissivity_eff': lvl}),
        'cum_gas_nm3', 'increase',
        'Physically bounded [0,1]; 0.45 default is a plausible mid-range effective value for a '
        'refractory-lined furnace with some view-factor losses. Same "increase" mechanism as '
        'HEARTH_AREA_M2 above: emissivity scales radiant transfer identically to area in '
        'radiant_heat_flux_kw(), so it hits the same fixed-Melt-duration overshoot behavior.',
        plausible_fn=lambda vals: all(500.0 < v < 15000.0 for v in vals if v is not None),
    )


def sweep_efficiency_scale() -> SweepResult:
    levels = [0.5, 0.8, 1.0, 1.25, 1.6]
    return _sweep_generic(
        'efficiency_scale', 'physics_constant', 'Fitted multiplier on combustion_efficiency()',
        levels, lambda lvl: _run_sim(model_kwargs={'efficiency_scale': lvl}),
        'cum_gas_nm3', 'decrease',
        'Calibrated to 1.248 against real gas usage (gas MAPE 17.8%, see calibrated_constants.json).',
        plausible_fn=lambda vals: all(500.0 < v < 15000.0 for v in vals if v is not None),
    )


def sweep_burnoff_k0() -> SweepResult:
    levels = [0.1, 0.3, 0.5, 0.85, 1.5]
    return _sweep_generic(
        'burnoff_k0', 'physics_constant', 'Dross oxidation rate pre-exponential scale',
        levels, lambda lvl: _run_sim(model_kwargs={'burnoff_k0': lvl}),
        'cum_dross_kg', 'increase',
        'Calibrated to 0.8506 against real yield loss (median real loss ~1.2%, mean ~3.5%, see '
        'MELTER_KNOWLEDGE.md sec.8.3). Dross for a 65t heat should stay well under ~10% (~6,500kg).',
        plausible_fn=lambda vals: all(0.0 <= v < 6500.0 for v in vals if v is not None),
    )


def sweep_burnoff_ea() -> SweepResult:
    """FIXED: dross_burnoff_rate_kg_hr() now caps at MAX_PLAUSIBLE_DROSS_RATE_KG_HR (see
    physics_model.py), so Ea=15000 -- which pre-fix implied 26,809kg (>40% of a 65t charge,
    physically impossible) -- is now clamped to ~19% of charge weight, under the
    data-loader-validated 20% plausible yield-loss bound. Still flagged non-plausible below
    (this sweep's tighter 10%-of-charge bar is intentionally stricter than the hard physical
    ceiling -- 19% dross is still far outside normal operation, just no longer impossible)."""
    levels = [15000.0, 30000.0, 45000.0, 60000.0, 80000.0]
    return _sweep_generic(
        'burnoff_ea', 'physics_constant', 'Dross Arrhenius activation energy (J/mol)',
        levels, lambda lvl: _run_sim(model_kwargs={'burnoff_ea': lvl}),
        'cum_dross_kg', 'decrease',
        'exp(-Ea/RT) is strictly decreasing in Ea for any finite T>0 with k0 fixed, so dross '
        'should monotonically DECREASE as Ea rises (not "become more sensitive" -- that would '
        'need k0 re-scaled too). Calibrated default Ea=45,000 gives ~1,299kg (~2%, plausible); '
        'Ea=15,000 now caps at ~12,412kg (~19% of a 65t charge) instead of the pre-fix 26,809kg.',
        plausible_fn=lambda vals: all(0.0 <= v < 6500.0 for v in vals if v is not None),
        notes='Physical ceiling now enforced (MAX_PLAUSIBLE_DROSS_RATE_KG_HR, derived from '
              "data_loader.py's own real-data 20%-of-charge plausible yield-loss bound) -- "
              'nonsensical (>charge-weight) dross is no longer possible regardless of burnoff_ea/'
              'k0. This sweep still flags low-Ea as non-plausible against its own tighter 10% '
              'bar, which is a separate, intentionally-stricter "normal operation" check, not a '
              'sign the physical guardrail is missing.',
    )


def sweep_stoich_air_gas_ratio() -> SweepResult:
    """FIXED: the dead unused import in optimizer.py has been removed (it never affected
    simulate_trajectory's logic). The constant itself remains defined in physics_model.py and
    is genuinely used by data_loader.py's directional excess-air estimate. This sweep is now a
    regression guard confirming it's still correctly a no-op for the cost/gas model."""
    levels = [7.0, 8.5, 9.52, 11.0, 13.0]

    def run(lvl):
        with _patched_module_constant('STOICH_AIR_GAS_RATIO', lvl):
            return _run_sim()

    return _sweep_generic(
        'STOICH_AIR_GAS_RATIO', 'physics_constant', 'Stoichiometric Nm3 air per Nm3 gas',
        levels, run, 'cum_gas_nm3', 'flat',
        'Correctly has NO effect on cost/gas outputs -- it is not (and should not be) part of '
        'simulate_trajectory()\'s combustion model; it only feeds data_loader.py\'s separate, '
        'already-caveated directional excess-air estimate from real sensor flow tags.',
    )


# ---------------------------------------------------------------------------
# Alloy properties
# ---------------------------------------------------------------------------

def sweep_alloy_dross() -> SweepResult:
    alloys = ['99.7', '6061', '5052', '5083', '5182']  # ascending Mg content per the manual
    return _sweep_generic(
        'alloy_name (dross ordering)', 'alloy',
        'Alloy choice, ascending Mg content: pure Al -> 6xxx -> 5052 -> 5083 -> 5182',
        alloys, lambda lvl: _run_sim(sim_overrides={'alloy_name': lvl}),
        'cum_dross_kg', 'increase',
        'Manual: Mg alloys (5052/5182/5083) dross 1.8-2.2x pure Al; ALLOY_PROPERTIES dross_mult '
        'table: 99.7=1.0, 6061=1.2, 5052=1.8, 5083=2.1, 5182=2.2.',
        plausible_fn=lambda vals: all(0.0 <= v < 6500.0 for v in vals if v is not None),
    )


# ---------------------------------------------------------------------------
# Decision variables
# ---------------------------------------------------------------------------

def sweep_excess_air_gas() -> SweepResult:
    levels = [5.0, 10.0, 15.0, 22.5, 30.0]
    return _sweep_generic(
        'excess_air_pct -> gas', 'decision_variable', 'Excess combustion air (%)',
        levels, lambda lvl: _run_sim(sim_overrides={'excess_air_pct': lvl}),
        'cum_gas_nm3', 'increase',
        'Manual sec.1.3.8: 15% max excess air at high fire (HMI range 0-30%).',
        plausible_fn=lambda vals: all(500.0 < v < 15000.0 for v in vals if v is not None),
    )


def sweep_excess_air_o2() -> SweepResult:
    levels = [5.0, 10.0, 15.0, 22.5, 30.0]
    return _sweep_generic(
        'excess_air_pct -> flue O2%', 'decision_variable', 'Excess combustion air (%)',
        levels, lambda lvl: _run_sim(sim_overrides={'excess_air_pct': lvl}),
        'flue_o2_pct', 'increase',
        'Manual sec.1.4.20/21 (AT104): practical O2 target 1-3%, HMI setpoint range 1-5%, default '
        '3%. Model formula at 15% excess air should land near the low end of that band.',
        plausible_fn=lambda vals: all(0.0 <= v <= 10.0 for v in vals if v is not None),
    )


def sweep_target_bath_temp() -> SweepResult:
    """Verified via final_bath_temp_c: at this baseline's fixed schedule (sp_roof_melt=1150C
    for 4h), the bath overshoots to the hardcoded 800C clamp for EVERY tested target (690-750C)
    -- so target_bath_temp_c has no room to matter here. This is a property of
    simulate_trajectory() run with a manually-fixed, non-optimized schedule; the deployed
    optimizer separately REJECTS any candidate schedule that doesn't land within 5C of target
    (optimize_heating_curve's deadline constraint), so this finding does NOT mean the operator
    tool ignores the target -- it means an isolated simulate_trajectory() call with an
    aggressive/mismatched roof schedule can silently overshoot well past whatever target was
    requested, worth knowing if simulate_trajectory() is ever used directly outside the
    optimizer's search."""
    levels = [690.0, 705.0, 720.0, 735.0, 750.0]
    return _sweep_generic(
        'target_bath_temp_c', 'decision_variable', 'Target tap-out metal temperature (C)',
        levels, lambda lvl: _run_sim(sim_overrides={'target_bath_temp_c': lvl}),
        'cum_gas_nm3', 'increase',
        'Manual sec.1.3.2: metal temperature range 690-750C in service.',
        plausible_fn=lambda vals: all(500.0 < v < 15000.0 for v in vals if v is not None),
        notes='final_bath_temp_c is pegged at the 800C hard clamp for ALL 5 levels with this '
              'baseline schedule (sp_roof_melt=1150C, 4h melt phase) -- the schedule overshoots '
              'every tested target, so target_bath_temp_c cannot influence cum_gas_nm3 here. Not '
              'a flaw in the optimizer (which rejects overshooting/undershooting candidates), but '
              'shows simulate_trajectory() itself has no target-aware early throttling during the '
              'Melt phase -- it always burns to the commanded roof setpoint regardless of bath state.',
    )


def sweep_sp_roof_melt() -> SweepResult:
    """Direction NOT assumed: raising roof melt setpoint lowers combustion_efficiency() (per its
    formula) but delivers heat faster via the T^4 radiant term -- report which effect wins for
    total cumulative gas over a FIXED 6h duration."""
    levels = [1120.0, 1150.0, 1180.0, 1210.0, 1240.0]
    return _sweep_generic(
        'sp_roof_melt', 'decision_variable', 'Melt-phase roof temperature setpoint (C)',
        levels, lambda lvl: _run_sim(sim_overrides={'sp_roof_melt': lvl}),
        'cum_gas_nm3', 'ambiguous',
        'Manual: "higher roof temp = quicker melt rate but greater refractory strain"; ceiling '
        'commonly set near 1200C (app.py default). Effect on TOTAL gas over a fixed duration is '
        'not obvious a priori -- efficiency drops but heat delivery speeds up.',
        plausible_fn=lambda vals: all(500.0 < v < 15000.0 for v in vals if v is not None),
    )


def sweep_charged_weight() -> SweepResult:
    levels = [40000.0, 55000.0, 65000.0, 75000.0, 85000.0]
    return _sweep_generic(
        'charged_weight_kg', 'furnace_input', 'Fresh charge weight (kg)',
        levels, lambda lvl: _run_sim(sim_overrides={'charged_weight_kg': lvl}),
        'cum_gas_nm3', 'increase',
        'Real production median charge ~65.5t (25th-75th pct ~55.8-70.9t); furnace nameplate 80t.',
        plausible_fn=lambda vals: all(500.0 < v < 15000.0 for v in vals if v is not None),
    )


def sweep_charged_weight_per_tonne() -> SweepResult:
    """Economies-of-scale check: gas PER TONNE should decrease as charge weight grows, since
    wall_loss_kw is a fixed loss independent of mass."""
    levels = [40000.0, 55000.0, 65000.0, 75000.0, 85000.0]

    def run(lvl):
        summary = _run_sim(sim_overrides={'charged_weight_kg': lvl})
        summary = dict(summary)
        summary['cum_gas_nm3'] = summary['cum_gas_nm3'] / (lvl / 1000.0)  # Nm3 per tonne
        return summary

    return _sweep_generic(
        'charged_weight_kg -> gas/tonne', 'furnace_input', 'Fresh charge weight (kg), gas per tonne',
        levels, run, 'cum_gas_nm3', 'decrease',
        'Economies of scale: fixed wall_loss_kw spread over more mass at higher charge weight.',
    )


def sweep_residual_marginal_cost() -> SweepResult:
    """Marginal gas cost per kg of ADDED residual (fixed charged_weight_kg, residual on top)
    should be lower than the marginal gas cost per kg of added fresh charge -- the residual
    arrives partially pre-heated."""
    base = _run_sim()
    plus_residual = _run_sim(sim_overrides={'residual_weight_kg': 5000.0})
    plus_charge = _run_sim(sim_overrides={'charged_weight_kg': 70000.0})

    marginal_residual = (plus_residual['cum_gas_nm3'] - base['cum_gas_nm3']) / 5000.0
    marginal_charge = (plus_charge['cum_gas_nm3'] - base['cum_gas_nm3']) / 5000.0

    match = marginal_residual < marginal_charge
    return SweepResult(
        name='residual_weight_kg (marginal cost)', category='furnace_input',
        param_desc='Marginal Nm3 gas per kg: +5t residual (on top) vs. +5t fresh charge',
        levels=['+5t residual', '+5t fresh charge'],
        outputs={'cum_gas_nm3': [marginal_residual, marginal_charge], 'cum_dross_kg': [None, None],
                 'total_cost': [None, None], 'final_bath_temp_c': [None, None], 'flue_o2_pct': [None, None]},
        expected_direction='residual < fresh charge (per kg)',
        observed_direction=f'residual={marginal_residual:.5f}, fresh={marginal_charge:.5f} Nm3/kg',
        direction_match=match,
        benchmark_note='Residual arrives already near liquidus; should need less new gas per kg '
                        'than cold fresh scrap starting at 25C.',
        plausible=None,
    )


def sweep_residual_same_total() -> SweepResult:
    """Reuses the invariant already covered by
    tests/test_optimizer.py::test_residual_heel_reduces_gas_for_same_total_furnace_mass --
    included here too so the report's parameter list is self-contained."""
    all_cold = _run_sim(sim_overrides={'charged_weight_kg': 65000.0, 'residual_weight_kg': 0.0})
    with_residual = _run_sim(sim_overrides={'charged_weight_kg': 58000.0, 'residual_weight_kg': 7000.0})
    match = with_residual['cum_gas_nm3'] < all_cold['cum_gas_nm3']
    return SweepResult(
        name='residual_weight_kg (fixed total mass)', category='furnace_input',
        param_desc='65t all-cold vs. 58t fresh + 7t hot residual (same 65t total)',
        levels=['all_cold_65t', '58t_charge_plus_7t_residual'],
        outputs={'cum_gas_nm3': [all_cold['cum_gas_nm3'], with_residual['cum_gas_nm3']],
                 'cum_dross_kg': [all_cold['cum_dross_kg'], with_residual['cum_dross_kg']],
                 'total_cost': [all_cold['total_cost'], with_residual['total_cost']],
                 'final_bath_temp_c': [all_cold['final_bath_temp_c'], with_residual['final_bath_temp_c']],
                 'flue_o2_pct': [all_cold['flue_o2_pct'], with_residual['flue_o2_pct']]},
        expected_direction='with_residual < all_cold', observed_direction=str(match),
        direction_match=match,
        benchmark_note='Field practice: ~5-10t hot residual heel typically left in furnace '
                        '(MELTER_KNOWLEDGE.md addendum). Also covered by a pytest regression test.',
        plausible=None,
    )


def sweep_max_roof_sp_limit() -> SweepResult:
    """Larger search space can only produce an equal-or-lower optimal cost -- must be
    monotonic non-increasing as the ceiling rises."""
    levels = [1150.0, 1180.0, 1200.0, 1220.0, 1250.0]

    def run(lvl):
        opt = HeatingCurveOptimizer()
        res = opt.optimize_heating_curve(**{**BASELINE_OPT, 'max_roof_sp_limit': lvl})
        return res['optimal_summary']

    return _sweep_generic(
        'max_roof_sp_limit', 'optimizer_search', 'Roof temperature safety ceiling (C)',
        levels, run, 'total_cost', 'non_increase',
        'Manual: roof commonly set to a high fixed value, "may be 1200C". A wider search space '
        'can never make the found optimum WORSE (non-increasing cost) -- flat is a valid outcome '
        'if the true cost-minimizing sp_roof_melt already sits below the search grid\'s lower '
        'bound (1120C) and raising the ceiling only extends the unused upper end.',
    )


def sweep_discharge_deadline_feasibility() -> SweepResult:
    """Finds the feasibility boundary: shorter deadlines should eventually become infeasible
    for a representative charge at the default roof ceiling."""
    levels = [2.0, 3.0, 4.0, 6.0, 9.0]
    outputs = {m: [] for m in METRICS}
    deadline_met = []
    for lvl in levels:
        opt = HeatingCurveOptimizer()
        res = opt.optimize_heating_curve(**{**BASELINE_OPT, 'discharge_deadline_hrs': lvl})
        summary = res['optimal_summary']
        for m in METRICS:
            outputs[m].append(summary.get(m))
        deadline_met.append(res['deadline_met'])
    infeasible_found = not all(deadline_met)
    return SweepResult(
        name='discharge_deadline_hrs (feasibility)', category='optimizer_search',
        param_desc='Required discharge deadline (hrs) for a 65t 5052 charge',
        levels=levels, outputs=outputs, expected_direction='infeasible regime exists at short deadlines',
        observed_direction=str(list(zip(levels, deadline_met))),
        direction_match=infeasible_found if levels[0] < 3.0 else None,
        benchmark_note='Real median melt duration ~5.9hrs (production log); a very short deadline '
                        '(e.g. 2hrs) for a 65t charge should be infeasible at reasonable roof limits.',
        plausible=None,
        notes=f'deadline_met per level: {dict(zip(levels, deadline_met))}',
    )


def sweep_price_responsiveness() -> SweepResult:
    """Checks whether raising aluminum_price (relative to gas_price) shifts the optimizer
    toward a lower-dross (lower excess-air) schedule, i.e. whether the cost search is genuinely
    price-responsive rather than dominated by one cost term."""
    al_prices = [50.0, 75.0, 120.0, 200.0]
    chosen_excess_air = []
    for al_price in al_prices:
        model = MelterPhysicsModel(gas_price=15.0, aluminum_price=al_price)
        opt = HeatingCurveOptimizer(model)
        res = opt.optimize_heating_curve(**BASELINE_OPT)
        chosen_excess_air.append(res['optimal_params']['excess_air_pct'])
    observed = _trend(chosen_excess_air)
    match = _verdict('non_increase', observed)
    pinned_at_floor = all(v == min(chosen_excess_air) for v in chosen_excess_air)
    notes = f'chosen excess_air_pct per aluminum_price: {dict(zip(al_prices, chosen_excess_air))}.'
    if pinned_at_floor:
        notes += (
            ' Pinned at the search grid\'s lowest candidate (10%) for EVERY price tested. This '
            'is expected, not a bug: in the current model, lower excess air simultaneously '
            'improves combustion_efficiency() AND reduces dross_burnoff_rate_kg_hr() (via its '
            'o2_factor) -- there is no genuine trade-off surface where a higher metal price '
            'would justify MORE excess air for some offsetting gas benefit. Excess air reduction '
            'is a dominant strategy regardless of price ratio here, so price-responsiveness '
            'cannot be observed on this particular decision variable with this cost structure.'
        )
    return SweepResult(
        name='aluminum_price -> chosen excess_air_pct', category='price_responsiveness',
        param_desc='aluminum_price (TWD/kg), gas_price fixed at 15',
        levels=al_prices, outputs={m: [] for m in METRICS},
        expected_direction='non_increase', observed_direction=observed,
        direction_match=match,
        benchmark_note='Higher metal price should bias the search toward less dross (lower '
                        'excess air) even at a modest gas premium, IF gas and dross present a '
                        'genuine trade-off in the model -- see notes for whether that holds.',
        plausible=None,
        notes=notes,
    )


# ---------------------------------------------------------------------------
# Report generation
# ---------------------------------------------------------------------------

SWEEP_FUNCS = [
    sweep_gas_lhv, sweep_hearth_area_instance, sweep_hearth_area_module_noop, sweep_wall_loss_kw,
    sweep_emissivity_eff, sweep_efficiency_scale, sweep_burnoff_k0, sweep_burnoff_ea,
    sweep_stoich_air_gas_ratio, sweep_alloy_dross, sweep_excess_air_gas, sweep_excess_air_o2,
    sweep_target_bath_temp, sweep_sp_roof_melt, sweep_charged_weight, sweep_charged_weight_per_tonne,
    sweep_residual_marginal_cost, sweep_residual_same_total, sweep_max_roof_sp_limit,
    sweep_discharge_deadline_feasibility, sweep_price_responsiveness,
]


def _verdict_symbol(v: Optional[bool]) -> str:
    if v is None:
        return '➖ (context-dependent, see notes)'
    return '✅ matches' if v else '❌ MISMATCH'


def _fmt_row(levels, values):
    cells = []
    for lvl, val in zip(levels, values):
        lvl_s = f'{lvl:.1f}' if isinstance(lvl, float) else str(lvl)
        val_s = f'{val:.2f}' if isinstance(val, (int, float)) and val is not None else 'n/a'
        cells.append(f'{lvl_s} -> {val_s}')
    return ' | '.join(cells)


def generate_report(results: List[SweepResult]) -> str:
    lines = [
        '# Sensitivity Analysis Report',
        '',
        'Generated by `python -m src.sensitivity_analysis`. One-at-a-time parameter sweeps',
        'checking output DIRECTION (physically expected?) and PLAUSIBILITY (consistent with',
        'the Mechatherm manual / real production data documented in MELTER_KNOWLEDGE.md and',
        'PLAN.md). This is a diagnostic pass -- findings are surfaced, not auto-fixed.',
        '',
        '## Summary table',
        '',
        '| Parameter | Category | Expected | Observed | Direction | Plausible |',
        '|---|---|---|---|---|---|',
    ]
    for r in results:
        plaus = '✅' if r.plausible else ('❌' if r.plausible is False else '➖')
        lines.append(
            f'| {r.name} | {r.category} | {r.expected_direction} | {r.observed_direction} | '
            f'{_verdict_symbol(r.direction_match)} | {plaus} |'
        )

    lines += ['', '## Per-parameter detail', '']
    for r in results:
        lines.append(f'### {r.name}')
        lines.append(f'- **What**: {r.param_desc}')
        lines.append(f'- **Expected direction**: {r.expected_direction}')
        lines.append(f'- **Observed**: {r.observed_direction}  -> {_verdict_symbol(r.direction_match)}')
        lines.append(f'- **Benchmark**: {r.benchmark_note}')
        if r.plausible is not None:
            lines.append(f'- **Plausible magnitude**: {"✅ yes" if r.plausible else "❌ NO"}')
        primary_metric = next((m for m in METRICS if any(v is not None for v in r.outputs.get(m, []))), None)
        if primary_metric and any(v is not None for v in r.outputs[primary_metric]):
            lines.append(f'- **{primary_metric} by level**: {_fmt_row(r.levels, r.outputs[primary_metric])}')
        if r.notes:
            lines.append(f'- **Notes**: {r.notes}')
        lines.append('')

    anomalies = [r for r in results if r.direction_match is False or r.plausible is False]
    lines += ['## Anomalies found', '']
    if not anomalies:
        lines.append('None -- all directional checks matched expectations and all magnitudes '
                      'fell within their benchmark ranges.')
    else:
        for r in anomalies:
            lines.append(f'- **{r.name}**: {r.notes or r.benchmark_note}')
    lines += [
        '',
        '### Known findings from code inspection (independent of the numeric sweep)',
        '',
        '- **`STOICH_AIR_GAS_RATIO` dead import -- FIXED.** It was imported into `optimizer.py` '
        'but never referenced there; the unused import (both the try and except branches) has '
        'been removed. The constant itself is unchanged in `physics_model.py` and remains '
        'genuinely used by `data_loader.py`\'s already-caveated directional excess-air estimate '
        '-- it was never wired into the combustion model, and this fix does not change that, '
        'only removes the misleading unused import that implied otherwise.',
        '- **`HEARTH_AREA_M2` instance override -- FIXED.** Previously `radiant_heat_flux_kw()` '
        'and `dross_burnoff_rate_kg_hr()` in `physics_model.py` read the module-level '
        '`HEARTH_AREA_M2` constant directly instead of `self.HEARTH_AREA_M2`, so a caller '
        'customizing hearth area via `model.HEARTH_AREA_M2 = X` got only ~1/11th the intended '
        'effect (instance-override sweep moved cum_gas_nm3 by only +12% across area 30->120 vs. '
        'the true +131% from the formulas that actually mattered). Both call sites now read '
        '`self.HEARTH_AREA_M2`; the instance-override sweep above now shows the full effect, and '
        'the "module patch" sweep is repurposed as a regression guard confirming module-level '
        'patching is correctly a no-op post-fix.',
        '- **`calculate_theoretical_energy()`\'s `theoretical_gas_nm3` field -- FIXED.** Was '
        'dividing by module-level `GAS_LHV` instead of `self.GAS_LHV`, inconsistent with the '
        'main simulation loop (`optimizer.py`, which already correctly used '
        '`self.model.GAS_LHV`). Now reads `self.GAS_LHV`, so an instance-level override is '
        'respected for this field too. Impact was low (informational/reference output only, '
        'never used in the cost calculation itself), but the fix is free and removes a latent '
        'trap for anyone reading this field directly.',
        '- **`burnoff_ea` direction is not simply "more sensitivity"**: `exp(-Ea/(R*T))` is '
        'strictly decreasing in Ea for any finite T, so raising Ea with k0 held fixed should '
        'monotonically REDUCE predicted dross at all practically-reached temperatures, not '
        'change how "sensitive" the rate is to temperature without also re-scaling k0.',
    ]
    return '\n'.join(lines)


def run_sensitivity_analysis() -> str:
    results = [f() for f in SWEEP_FUNCS]
    report = generate_report(results)
    with open(REPORT_PATH, 'w', encoding='utf-8') as f:
        f.write(report)
    return report


if __name__ == '__main__':
    report = run_sensitivity_analysis()
    print(f"Wrote {REPORT_PATH} ({len(report)} chars).")
