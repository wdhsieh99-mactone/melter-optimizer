"""
Physics Model Module for 80T Aluminum Static Melting Furnace.
Includes alloy properties, 4-burner 2-pair regenerative switching, air-fuel ratio,
thermodynamic energy balance, and Mg-dross oxidation kinetics.
"""

import json
import os
import numpy as np
from typing import Dict, Optional, Tuple

_CALIBRATED_CONSTANTS_PATH = os.path.join(os.path.dirname(__file__), 'calibrated_constants.json')


def load_calibrated_defaults() -> Dict[str, float]:
    """Loads physics-model constants fitted by src/calibration.py against real production
    data, if available. Returns {} (falling back to the hardcoded engineering-assumption
    defaults below) if no calibration has been run yet."""
    if not os.path.exists(_CALIBRATED_CONSTANTS_PATH):
        return {}
    try:
        with open(_CALIBRATED_CONSTANTS_PATH, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return data.get('params', {})
    except (json.JSONDecodeError, OSError):
        return {}

# Physical & Thermodynamic Constants
# Natural Gas heating value per Mechatherm 40522 O&M Manual sec. 1.3.1 Service
# Requirements: Gross Heating Value 9,700 kcal/Nm3 @ 15.6C, 101.3kPa.
# 9700 kcal/Nm3 * 4.184 kJ/kcal = 40,585 kJ/Nm3.
GAS_LHV = 40585.0              # Natural Gas heating value in kJ/Nm3 (manual sec. 1.3.1)
STOICH_AIR_GAS_RATIO = 9.52    # Nm3 air per Nm3 natural gas
STEFAN_BOLTZMANN = 5.67e-11    # kW / (m^2 * K^4)
# Bath (radiating) surface area per Mechatherm manual sec. 1.3.2: bath dimensions
# 10,500mm x 6,300mm = 66.15 m^2. This is the roof-to-bath radiant view area.
HEARTH_AREA_M2 = 66.15         # 80T Static Furnace bath surface area in m^2 (manual sec. 1.3.2)

# 4-Burner 2-Pair Regenerative Max Gas Flow Rates (Nm3/h). Note: "dual pair" means both pairs
# active, not 4 simultaneous flames -- manual sec.1.4.56 confirms only one burner per pair
# fires at a time (its twin exhausts/preheats), so at most 2 flames burn at once even here.
MAX_GAS_FLOW_DUAL_PAIR = 1300.0  # both pairs active (high fire melt), up to 2 flames at once
MAX_GAS_FLOW_SINGLE_PAIR = 650.0  # one pair active (duty toggle hold), 1 flame at a time

# Default Cost Parameters (TWD)
DEFAULT_GAS_PRICE_PER_NM3 = 15.0     # TWD / Nm3
DEFAULT_ALUMINUM_PRICE_PER_KG = 75.0 # TWD / kg

# Dross burn-off rate ceiling (kg/hr): a physical guardrail, not a fitted value. Found via
# SENSITIVITY_REPORT.md's burnoff_ea sweep that a too-low activation energy (e.g. 15,000 J/mol,
# well below the calibrated 45,000) drives dross_burnoff_rate_kg_hr() to imply >40% of a 65t
# charge lost to oxidation in one heat -- physically impossible, and dross_mult/burnoff_k0/
# burnoff_ea remain free parameters intentionally (src/sensitivity_analysis.py and
# src/calibration.py both need to explore/fit them), so this caps the RATE actually used
# downstream instead of restricting what values those parameters may take. Ceiling derived
# from data_loader.py's own real-data-validated plausible yield-loss bound (<=20% of charge,
# see compute_heat_yield_loss's plausible_pct_bounds) applied to the documented median charge
# (~65t, MELTER_KNOWLEDGE.md) over a median heat duration (~6h, MELTER_KNOWLEDGE.md):
# 65,000kg * 0.20 / 6h ~= 2,167 kg/hr. This still allows ~10x headroom above the calibrated
# baseline's typical ~200-300 kg/hr, room for legitimate "dirty scrap" scenarios.
MAX_PLAUSIBLE_DROSS_RATE_KG_HR = 2167.0

# Alloy Properties Database
ALLOY_PROPERTIES = {
    '5052': {'solidus': 607.0, 'liquidus': 650.0, 'latent_heat': 390.0, 'cp_liquid': 1.08, 'dross_mult': 1.8},
    '5052KS': {'solidus': 607.0, 'liquidus': 650.0, 'latent_heat': 390.0, 'cp_liquid': 1.08, 'dross_mult': 1.8},
    '5052R3': {'solidus': 607.0, 'liquidus': 650.0, 'latent_heat': 390.0, 'cp_liquid': 1.08, 'dross_mult': 1.8},
    '5182': {'solidus': 577.0, 'liquidus': 638.0, 'latent_heat': 380.0, 'cp_liquid': 1.05, 'dross_mult': 2.2},
    '5182FA': {'solidus': 577.0, 'liquidus': 638.0, 'latent_heat': 380.0, 'cp_liquid': 1.05, 'dross_mult': 2.2},
    # 5083 (Mg 4.0-4.9%): most-produced alloy family in MFA production log (~31% of heats,
    # incl. 5083A/5083L/5083S variants matched via substring in get_alloy_props()).
    '5083': {'solidus': 574.0, 'liquidus': 638.0, 'latent_heat': 385.0, 'cp_liquid': 1.06, 'dross_mult': 2.1},
    '6061': {'solidus': 582.0, 'liquidus': 652.0, 'latent_heat': 410.0, 'cp_liquid': 1.10, 'dross_mult': 1.2},
    '6M02': {'solidus': 582.0, 'liquidus': 652.0, 'latent_heat': 410.0, 'cp_liquid': 1.10, 'dross_mult': 1.2},
    '3004': {'solidus': 629.0, 'liquidus': 654.0, 'latent_heat': 400.0, 'cp_liquid': 1.09, 'dross_mult': 1.3},
    '3004R3': {'solidus': 629.0, 'liquidus': 654.0, 'latent_heat': 400.0, 'cp_liquid': 1.09, 'dross_mult': 1.3},
    '5151': {'solidus': 600.0, 'liquidus': 650.0, 'latent_heat': 390.0, 'cp_liquid': 1.08, 'dross_mult': 1.6},
    '99.7': {'solidus': 657.0, 'liquidus': 660.0, 'latent_heat': 397.0, 'cp_liquid': 1.08, 'dross_mult': 1.0},
    'DEFAULT': {'solidus': 600.0, 'liquidus': 650.0, 'latent_heat': 397.0, 'cp_liquid': 1.08, 'dross_mult': 1.4},
}


def get_alloy_props(alloy_name: str) -> Dict[str, float]:
    """Retrieves thermodynamic and dross multiplier properties for a given alloy."""
    name_clean = str(alloy_name).strip().upper()
    for k, props in ALLOY_PROPERTIES.items():
        if k in name_clean:
            return props
    return ALLOY_PROPERTIES['DEFAULT']


class MelterPhysicsModel:
    """Thermodynamic and Yield Loss Model for 80T Static Melter with 2-pair regenerative burners."""

    GAS_LHV = GAS_LHV
    HEARTH_AREA_M2 = HEARTH_AREA_M2
    ALLOY_PROPERTIES = ALLOY_PROPERTIES

    def __init__(
        self,
        gas_price: float = DEFAULT_GAS_PRICE_PER_NM3,
        aluminum_price: float = DEFAULT_ALUMINUM_PRICE_PER_KG,
        wall_loss_kw: Optional[float] = None,
        emissivity_eff: Optional[float] = None,
        burnoff_k0: Optional[float] = None,   # rate-scale, fitted against real per-heat yield loss
        burnoff_ea: Optional[float] = None,   # Activation energy (J/mol)
        efficiency_scale: Optional[float] = None,  # fitted multiplier on combustion_efficiency()
    ):
        # Any constant left as None picks up the value fitted by src/calibration.py against
        # real production data (if calibration has been run), else the hardcoded fallback here.
        calibrated = load_calibrated_defaults()
        self.gas_price = gas_price
        self.aluminum_price = aluminum_price
        self.wall_loss_kw = wall_loss_kw if wall_loss_kw is not None else calibrated.get('wall_loss_kw', 250.0)
        self.emissivity_eff = emissivity_eff if emissivity_eff is not None else calibrated.get('emissivity_eff', 0.45)
        self.burnoff_k0 = burnoff_k0 if burnoff_k0 is not None else calibrated.get('burnoff_k0', 0.45)
        self.burnoff_ea = burnoff_ea if burnoff_ea is not None else calibrated.get('burnoff_ea', 45000.0)
        self.efficiency_scale = efficiency_scale if efficiency_scale is not None else calibrated.get('efficiency_scale', 1.0)

    def calculate_theoretical_energy(
        self,
        weight_kg: float,
        alloy_name: str = '5052',
        initial_temp_c: float = 25.0,
        target_temp_c: float = 720.0
    ) -> Dict[str, float]:
        """Calculates theoretical enthalpy required to melt alloy from initial_temp to target_temp."""
        props = get_alloy_props(alloy_name)
        solidus = props['solidus']
        liquidus = props['liquidus']
        latent_h = props['latent_heat']
        cp_liq = props['cp_liquid']
        
        cp_solid = 0.90 # kJ/kg*°C
        
        delta_t1 = min(solidus, target_temp_c) - initial_temp_c
        sensible_solid = weight_kg * cp_solid * max(0.0, delta_t1) # kJ
        
        latent_heat = weight_kg * latent_h if target_temp_c >= liquidus else weight_kg * latent_h * 0.5 # kJ
        
        delta_t2 = max(0.0, target_temp_c - liquidus)
        sensible_liquid = weight_kg * cp_liq * delta_t2 # kJ
        
        total_energy_kj = sensible_solid + latent_heat + sensible_liquid
        total_energy_kwh = total_energy_kj / 3600.0
        theoretical_gas_nm3 = total_energy_kj / self.GAS_LHV
        
        return {
            'total_energy_kj': total_energy_kj,
            'total_energy_kwh': total_energy_kwh,
            'theoretical_gas_nm3': theoretical_gas_nm3,
            'alloy_props': props,
        }

    def combustion_efficiency(self, roof_temp_c: float, excess_air_pct: float = 15.0) -> float:
        """Estimates thermal efficiency considering roof temperature & excess air ratio."""
        # Baseline efficiency with 70% regenerative waste heat recovery
        base_eff = 0.65 - (roof_temp_c - 700.0) * 0.00025

        # Excess air dilution penalty: higher excess air reduces flame temperature and increases flue gas volume
        excess_air_penalty = (excess_air_pct - 15.0) * 0.004
        eff = (base_eff - excess_air_penalty) * self.efficiency_scale
        return max(0.32, min(0.68, eff))

    def calculate_flue_oxygen_pct(self, excess_air_pct: float = 15.0) -> float:
        """Estimates flue gas oxygen percentage based on excess air ratio."""
        # Approx O2% = (21 * X) / (100 + X * 1.1)
        x_frac = excess_air_pct / 100.0
        return (21.0 * x_frac) / (1.0 + x_frac * 1.05)

    def radiant_heat_flux_kw(self, roof_temp_c: float, bath_temp_c: float, is_flat_bath: bool = False) -> float:
        """Calculates radiant heat transfer rate between roof refractory and bath surface (kW).
        Positive when heat flows roof -> bath; negative when bath radiates out.
        Accounts for dross layer thermal resistance (10-30mm oxide layer) once flat molten bath forms.
        """
        t_roof_k = roof_temp_c + 273.15
        t_bath_k = bath_temp_c + 273.15
        dross_factor = 0.70 if is_flat_bath else 1.0
        return STEFAN_BOLTZMANN * self.emissivity_eff * self.HEARTH_AREA_M2 * (t_roof_k**4 - t_bath_k**4) * dross_factor

    def bath_bottom_loss_kw(self, bath_temp_c: float) -> float:
        """Heat conduction loss from molten bath to furnace hearth bottom refractory & ambient (kW)."""
        if bath_temp_c <= 100.0:
            return 0.0
        return 85.0 * max(0.0, bath_temp_c - 25.0) / (780.0 - 25.0)

    def dross_burnoff_rate_kg_hr(
        self,
        roof_temp_c: float,
        bath_temp_c: float,
        alloy_name: str = '5052',
        excess_air_pct: float = 15.0,
        is_flat_bath: bool = False
    ) -> float:
        """Estimates alloy-specific dross oxidation rate (kg/hr) considering furnace oxygen partial pressure."""
        props = get_alloy_props(alloy_name)
        dross_mult = props['dross_mult']
        
        t_roof_k = roof_temp_c + 273.15
        r_gas = 8.314 # J/mol*K
        
        t_surface_k = 0.6 * t_roof_k + 0.4 * (bath_temp_c + 273.15)
        
        rate_base = self.burnoff_k0 * self.HEARTH_AREA_M2 * np.exp(-self.burnoff_ea / (r_gas * t_surface_k)) * 100.0
        
        # Flue gas oxygen partial pressure oxidation factor (higher O2 = faster Al & Mg oxidation into dross)
        o2_pct = self.calculate_flue_oxygen_pct(excess_air_pct)
        o2_factor = (o2_pct / 2.0) ** 0.5
        
        multiplier = 2.5 if is_flat_bath else 1.0
        rate = rate_base * multiplier * dross_mult * o2_factor
        return min(MAX_PLAUSIBLE_DROSS_RATE_KG_HR, max(0.1, rate))

    def compute_heat_cost(self, gas_nm3: float, dross_kg: float) -> Dict[str, float]:
        """Calculates cost breakdown (TWD)."""
        gas_cost = gas_nm3 * self.gas_price
        dross_cost = dross_kg * self.aluminum_price
        total_cost = gas_cost + dross_cost
        return {
            'gas_cost': gas_cost,
            'dross_cost': dross_cost,
            'total_cost': total_cost
        }

    def calculate_sankey_energy_balance(
        self,
        cum_gas_nm3: float,
        cum_dross_kg: float,
        charged_weight_kg: float,
        residual_weight_kg: float,
        duration_hrs: float,
        final_bath_temp_c: float,
        alloy_name: str = '5052',
        excess_air_pct: float = 15.0,
    ) -> Dict[str, float]:
        """Calculates comprehensive thermodynamic energy balance (GJ) for Sankey diagram.
        Inputs: Fuel combustion enthalpy, Dross oxidation exothermic heat, Regenerator preheated air.
        Outputs: Aluminum melting absorption, Dross sensible heat, Wall & hearth losses, Roof leakage exhaust, Regenerator stack loss.
        """
        props = get_alloy_props(alloy_name)
        solidus = props['solidus']
        liquidus = props['liquidus']
        latent_h = props['latent_heat']
        cp_liq = props['cp_liquid']
        cp_solid = 0.90 # kJ/kg*K
        
        # 1. Inputs
        q_fuel_gj = (cum_gas_nm3 * self.GAS_LHV) / 1e6
        # Dross exothermic oxidation heat (4 Al + 3 O2 -> 2 Al2O3 releases ~31.05 MJ/kg Al oxidized)
        q_ox_gj = (cum_dross_kg * 0.60 * 31.05) / 1000.0
        
        # 2. Output Sinks
        total_metal_kg = charged_weight_kg + residual_weight_kg
        delta_t_solid = min(solidus, final_bath_temp_c) - 25.0
        sensible_solid = total_metal_kg * cp_solid * max(0.0, delta_t_solid)
        latent_melt = total_metal_kg * latent_h if final_bath_temp_c >= liquidus else total_metal_kg * latent_h * 0.5
        delta_t_liq = max(0.0, final_bath_temp_c - liquidus)
        sensible_liquid = total_metal_kg * cp_liq * delta_t_liq
        q_al_absorbed_gj = (sensible_solid + latent_melt + sensible_liquid) / 1e6
        
        # Dross sensible heat absorption (GJ)
        cp_dross = 1.15 # kJ/kg*K
        q_dross_sensible_gj = (cum_dross_kg * cp_dross * max(0.0, final_bath_temp_c - 25.0)) / 1e6
        
        # Wall & hearth losses
        avg_hearth_loss_kw = self.bath_bottom_loss_kw(final_bath_temp_c) * 0.75
        q_wall_hearth_gj = ((self.wall_loss_kw + avg_hearth_loss_kw) * duration_hrs * 3600.0) / 1e6
        
        # 3. Flue Gas Enthalpy Balance & Regenerator Recovery
        net_heat_to_flue_gj = max(1.0, (q_fuel_gj + q_ox_gj) - (q_al_absorbed_gj + q_dross_sensible_gj + q_wall_hearth_gj))
        
        regen_eff = 0.74 - (excess_air_pct - 15.0) * 0.003
        regen_eff = max(0.60, min(0.78, regen_eff))
        
        q_roof_exhaust_gj = net_heat_to_flue_gj * 0.10
        q_bed_flue_in_gj = net_heat_to_flue_gj * 0.90
        q_air_preheat_gj = q_bed_flue_in_gj * regen_eff
        q_stack_loss_gj = q_bed_flue_in_gj * (1.0 - regen_eff)
        
        total_chamber_input_gj = q_fuel_gj + q_ox_gj + q_air_preheat_gj
        total_chamber_output_gj = q_al_absorbed_gj + q_dross_sensible_gj + q_wall_hearth_gj + q_roof_exhaust_gj + q_bed_flue_in_gj
        
        thermal_eff_fuel_pct = (q_al_absorbed_gj / q_fuel_gj) * 100.0 if q_fuel_gj > 0 else 0.0
        thermal_eff_total_pct = (q_al_absorbed_gj / total_chamber_input_gj) * 100.0 if total_chamber_input_gj > 0 else 0.0
        regen_recovery_pct = (q_air_preheat_gj / q_bed_flue_in_gj) * 100.0 if q_bed_flue_in_gj > 0 else 0.0
        total_flue_loss_pct = ((q_roof_exhaust_gj + q_stack_loss_gj) / (q_fuel_gj + q_ox_gj)) * 100.0 if (q_fuel_gj + q_ox_gj) > 0 else 0.0
        
        return {
            'q_fuel_gj': q_fuel_gj,
            'q_ox_gj': q_ox_gj,
            'q_air_preheat_gj': q_air_preheat_gj,
            'total_chamber_input_gj': total_chamber_input_gj,
            'q_al_absorbed_gj': q_al_absorbed_gj,
            'q_dross_sensible_gj': q_dross_sensible_gj,
            'q_wall_hearth_gj': q_wall_hearth_gj,
            'q_roof_exhaust_gj': q_roof_exhaust_gj,
            'q_bed_flue_in_gj': q_bed_flue_in_gj,
            'q_stack_loss_gj': q_stack_loss_gj,
            'total_chamber_output_gj': total_chamber_output_gj,
            'thermal_eff_fuel_pct': thermal_eff_fuel_pct,
            'thermal_eff_total_pct': thermal_eff_total_pct,
            'regen_recovery_pct': regen_recovery_pct,
            'total_flue_loss_pct': total_flue_loss_pct,
        }


if __name__ == '__main__':
    model = MelterPhysicsModel()
    for alloy in ['5052', '6061', '5182', '99.7']:
        res = model.calculate_theoretical_energy(65000.0, alloy_name=alloy)
        dross = model.dross_burnoff_rate_kg_hr(1150.0, 720.0, alloy_name=alloy, is_flat_bath=True)
        print(f"Alloy {alloy}: Req Gas={res['theoretical_gas_nm3']:.1f} Nm3, Dross Rate={dross:.2f} kg/h")
