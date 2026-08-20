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
        hearth_area_m2: Optional[float] = None,
        hearth_loss_ref_kw: Optional[float] = None,
        dross_factor_flat: Optional[float] = None,
        dross_net_loss_factor: Optional[float] = None,
        gas_lhv: Optional[float] = None,
        regen_base_eff: Optional[float] = None,
        **kwargs
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
        self.HEARTH_AREA_M2 = hearth_area_m2 if hearth_area_m2 is not None else calibrated.get('hearth_area_m2', HEARTH_AREA_M2)
        self.hearth_loss_ref_kw = hearth_loss_ref_kw if hearth_loss_ref_kw is not None else 85.0
        self.dross_factor_flat = dross_factor_flat if dross_factor_flat is not None else 0.70
        self.dross_net_loss_factor = dross_net_loss_factor if dross_net_loss_factor is not None else calibrated.get('dross_net_loss_factor', 0.40)
        if gas_lhv is not None:
            self.GAS_LHV = gas_lhv
        self.regen_base_eff = regen_base_eff if regen_base_eff is not None else 0.74

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
        
        # Sensible heat solid
        delta_t_solid = max(0.0, min(solidus, target_temp_c) - initial_temp_c)
        sensible_solid = weight_kg * cp_solid * delta_t_solid # kJ
        
        # Latent heat with mushy zone linear lever rule
        if target_temp_c <= solidus:
            latent_heat = 0.0
        elif target_temp_c >= liquidus:
            latent_heat = weight_kg * latent_h
        else:
            f_liquid = (target_temp_c - solidus) / (liquidus - solidus)
            latent_heat = weight_kg * latent_h * f_liquid
        
        # Sensible heat liquid
        delta_t_liq = max(0.0, target_temp_c - liquidus)
        sensible_liquid = weight_kg * cp_liq * delta_t_liq # kJ
        
        total_energy_kj = sensible_solid + latent_heat + sensible_liquid
        total_energy_kwh = total_energy_kj / 3600.0
        theoretical_gas_nm3 = total_energy_kj / self.GAS_LHV
        
        return {
            'total_energy_kj': total_energy_kj,
            'total_theoretical_energy_kj': total_energy_kj,
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
        base_net = max(0.35, min(0.75, base_eff - excess_air_penalty))
        eff = base_net * self.efficiency_scale
        return max(0.32, min(0.78, eff))

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
        dross_factor = self.dross_factor_flat if is_flat_bath else 1.0
        return STEFAN_BOLTZMANN * self.emissivity_eff * self.HEARTH_AREA_M2 * (t_roof_k**4 - t_bath_k**4) * dross_factor

    def bath_bottom_loss_kw(self, bath_temp_c: float) -> float:
        """Heat conduction loss from molten bath to furnace hearth bottom refractory & ambient (kW)."""
        if bath_temp_c <= 100.0:
            return 0.0
        return self.hearth_loss_ref_kw * max(0.0, bath_temp_c - 25.0) / (780.0 - 25.0)

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
        """Calculates cost breakdown (TWD) accounting for metal recovery from dross."""
        gas_cost = gas_nm3 * self.gas_price
        dross_cost = dross_kg * self.aluminum_price * self.dross_net_loss_factor
        total_cost = gas_cost + dross_cost
        return {
            'gas_cost': gas_cost,
            'dross_cost': dross_cost,
            'dross_cost_gross': dross_kg * self.aluminum_price,
            'dross_net_loss_factor': self.dross_net_loss_factor,
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
        overhead_dict: Optional[Dict[str, float]] = None,
    ) -> Dict[str, float]:
        """Calculates comprehensive thermodynamic energy balance (GJ) for Sankey diagram.
        Inputs: Fuel combustion enthalpy, Dross oxidation exothermic heat, Regenerator preheated air.
        Outputs: Aluminum melting absorption, Dross sensible heat, Wall & hearth losses, Overhead losses, Roof leakage exhaust, Regenerator stack loss.
        """
        props = get_alloy_props(alloy_name)
        solidus = props['solidus']
        liquidus = props['liquidus']
        latent_h = props['latent_heat']
        cp_liq = props['cp_liquid']
        cp_solid = 0.90 # kJ/kg*K
        
        # 1. Primary Chemical & Exothermic Inputs
        q_fuel_gj = (cum_gas_nm3 * self.GAS_LHV) / 1e6
        # Dross exothermic oxidation heat (4 Al + 3 O2 -> 2 Al2O3 releases ~31.05 MJ/kg Al oxidized)
        q_ox_gj = (cum_dross_kg * 0.60 * 31.05) / 1000.0
        
        # 2. Output Sinks (Metal & Furnace Enthalpy Sinks)
        total_metal_kg = charged_weight_kg + residual_weight_kg
        delta_t_solid = max(0.0, min(solidus, final_bath_temp_c) - 25.0)
        sensible_solid = total_metal_kg * cp_solid * delta_t_solid
        
        if final_bath_temp_c <= solidus:
            latent_melt = 0.0
        elif final_bath_temp_c >= liquidus:
            latent_melt = total_metal_kg * latent_h
        else:
            f_liq = (final_bath_temp_c - solidus) / (liquidus - solidus)
            latent_melt = total_metal_kg * latent_h * f_liq
            
        delta_t_liq = max(0.0, final_bath_temp_c - liquidus)
        sensible_liquid = total_metal_kg * cp_liq * delta_t_liq
        q_al_absorbed_gj = (sensible_solid + latent_melt + sensible_liquid) / 1e6
        
        # Dross sensible heat absorption (GJ)
        cp_dross = 1.15 # kJ/kg*K
        q_dross_sensible_gj = (cum_dross_kg * cp_dross * max(0.0, final_bath_temp_c - 25.0)) / 1e6
        
        # Wall & hearth losses
        avg_hearth_loss_kw = self.bath_bottom_loss_kw(final_bath_temp_c) * 0.75
        q_wall_hearth_gj = ((self.wall_loss_kw + avg_hearth_loss_kw) * duration_hrs * 3600.0) / 1e6
        
        # Field Operational Overhead Thermal Loss (Door radiation, refractory reheat, reversal purge)
        if overhead_dict:
            q_door_charge = overhead_dict.get('q_door_charge_gj', 0.0)
            q_door_dross = overhead_dict.get('q_door_dross_gj', 0.0)
            q_refractory_reheat = overhead_dict.get('q_refractory_reheat_gj', 0.0)
            q_reversal_purge = (overhead_dict.get('gas_reversal_purge_nm3', 0.0) * self.GAS_LHV) / 1e6
            q_overhead_thermal_gj = q_door_charge + q_door_dross + q_refractory_reheat + q_reversal_purge
        else:
            q_overhead_thermal_gj = 0.0
        
        # 3. Flue Gas Enthalpy Balance & Regenerator Recovery (Closed-Loop Thermal Balance)
        q_absorbed_total_gj = q_al_absorbed_gj + q_dross_sensible_gj + q_wall_hearth_gj + q_overhead_thermal_gj
        q_net_primary_gj = max(0.1, (q_fuel_gj + q_ox_gj) - q_absorbed_total_gj)
        
        regen_eff = self.regen_base_eff - (excess_air_pct - 15.0) * 0.003
        regen_eff = max(0.60, min(0.78, regen_eff))
        
        # Flue gas leaving chamber: Q_flue = Q_net_primary / (1 - 0.90 * regen_eff)
        # Preheated air recycling: Q_air = 0.90 * regen_eff * Q_flue
        q_flue_chamber_out_gj = q_net_primary_gj / (1.0 - 0.90 * regen_eff)
        q_roof_exhaust_gj = q_flue_chamber_out_gj * 0.10
        q_bed_flue_in_gj = q_flue_chamber_out_gj * 0.90
        q_air_preheat_gj = q_bed_flue_in_gj * regen_eff
        q_stack_loss_gj = q_bed_flue_in_gj * (1.0 - regen_eff)
        
        total_chamber_input_gj = q_fuel_gj + q_ox_gj + q_air_preheat_gj
        total_chamber_output_gj = q_absorbed_total_gj + q_roof_exhaust_gj + q_bed_flue_in_gj
        
        total_system_input_gj = q_fuel_gj + q_ox_gj
        total_system_output_gj = q_absorbed_total_gj + q_roof_exhaust_gj + q_stack_loss_gj
        
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
            'q_overhead_thermal_gj': q_overhead_thermal_gj,
            'q_roof_exhaust_gj': q_roof_exhaust_gj,
            'q_bed_flue_in_gj': q_bed_flue_in_gj,
            'q_stack_loss_gj': q_stack_loss_gj,
            'total_chamber_output_gj': total_chamber_output_gj,
            'total_system_input_gj': total_system_input_gj,
            'total_system_output_gj': total_system_output_gj,
            'residual_error_gj': abs(total_chamber_input_gj - total_chamber_output_gj),
            'thermal_eff_fuel_pct': thermal_eff_fuel_pct,
            'thermal_eff_total_pct': thermal_eff_total_pct,
            'regen_recovery_pct': regen_recovery_pct,
            'total_flue_loss_pct': total_flue_loss_pct,
        }

    def calculate_field_overhead_losses(
        self,
        charged_weight_kg: float,
        net_melt_gas_nm3: float,
        target_duration_hrs: float = 5.0,
        actual_total_duration_hrs: Optional[float] = None,
        charge_door_open_mins: float = 60.0,
        dross_door_open_mins: float = 20.0,
        reversal_loss_pct: float = 4.0,
        refractory_reheat_gj: float = 7.0,
        door_area_m2: float = 7.0,
        chamber_temp_c: float = 1000.0,
        ambient_temp_c: float = 30.0,
        enable_overhead: bool = True,
    ) -> Dict[str, float]:
        """Computes field dynamic operational overhead losses (door open radiation, refractory transient
        reheat, burner reversal purging, drossing door open, and extended holding waiting for caster).
        Aligns the thermodynamic model with China Steel Aluminium plant records (115年 MFX ~72 Nm³/t).
        """
        if not enable_overhead:
            return {
                'q_door_charge_gj': 0.0,
                'gas_door_charge_nm3': 0.0,
                'q_door_dross_gj': 0.0,
                'gas_door_dross_nm3': 0.0,
                'q_refractory_reheat_gj': 0.0,
                'gas_refractory_nm3': 0.0,
                'gas_reversal_purge_nm3': 0.0,
                'gas_holding_extended_nm3': 0.0,
                'total_overhead_gas_nm3': 0.0,
                'total_overhead_gj': 0.0,
                'specific_overhead_nm3_t': 0.0,
            }
        
        sigma = 5.670374e-8  # W / (m^2 * K^4)
        t_furnace_k = chamber_temp_c + 273.15
        t_amb_k = ambient_temp_c + 273.15
        emissivity = 0.85
        
        # 1. Charging door open radiation loss (GJ & Nm³)
        q_rad_w_m2 = sigma * emissivity * (t_furnace_k**4 - t_amb_k**4)
        q_door_charge_watts = q_rad_w_m2 * door_area_m2
        q_door_charge_gj = (q_door_charge_watts * (charge_door_open_mins * 60.0)) / 1e9
        gas_door_charge_nm3 = (q_door_charge_gj * 1e6) / self.GAS_LHV
        
        # 2. Drossing / fluxing / sampling door open loss (GJ & Nm³)
        dross_door_area_m2 = min(2.5, door_area_m2 * 0.35)
        q_door_dross_watts = q_rad_w_m2 * dross_door_area_m2
        q_door_dross_gj = (q_door_dross_watts * (dross_door_open_mins * 60.0)) / 1e9
        gas_door_dross_nm3 = (q_door_dross_gj * 1e6) / self.GAS_LHV
        
        # 3. Refractory transient storage reheat (GJ & Nm³)
        gas_refractory_nm3 = (refractory_reheat_gj * 1e6) / self.GAS_LHV
        
        # 4. Burner reversal valve switching purge unburnt gas loss (Nm³)
        gas_reversal_purge_nm3 = net_melt_gas_nm3 * (reversal_loss_pct / 100.0)
        
        # 5. Extended holding waiting for caster (Nm³)
        act_dur = actual_total_duration_hrs if actual_total_duration_hrs is not None else target_duration_hrs
        extra_hold_hrs = max(0.0, act_dur - target_duration_hrs)
        # Physical holding power: maintains steady-state wall loss and draft opening at holding temperature
        holding_eff = self.combustion_efficiency(780.0, excess_air_pct=15.0)
        holding_kw = self.wall_loss_kw + 20.0  # steady-state wall loss + draft loss
        holding_gas_rate_nm3h = (holding_kw * 3600.0) / (holding_eff * self.GAS_LHV) if self.GAS_LHV > 0 else 40.0
        gas_holding_extended_nm3 = extra_hold_hrs * holding_gas_rate_nm3h
        
        total_overhead_gas_nm3 = (
            gas_door_charge_nm3 + gas_door_dross_nm3 + gas_refractory_nm3
            + gas_reversal_purge_nm3 + gas_holding_extended_nm3
        )
        total_overhead_gj = (total_overhead_gas_nm3 * self.GAS_LHV) / 1e6
        
        charged_t = max(0.01, charged_weight_kg / 1000.0)
        specific_overhead_nm3_t = total_overhead_gas_nm3 / charged_t
        
        return {
            'q_door_charge_gj': q_door_charge_gj,
            'gas_door_charge_nm3': gas_door_charge_nm3,
            'q_door_dross_gj': q_door_dross_gj,
            'gas_door_dross_nm3': gas_door_dross_nm3,
            'q_refractory_reheat_gj': refractory_reheat_gj,
            'gas_refractory_nm3': gas_refractory_nm3,
            'gas_reversal_purge_nm3': gas_reversal_purge_nm3,
            'gas_holding_extended_nm3': gas_holding_extended_nm3,
            'total_overhead_gas_nm3': total_overhead_gas_nm3,
            'total_overhead_gj': total_overhead_gj,
            'specific_overhead_nm3_t': specific_overhead_nm3_t,
        }


if __name__ == '__main__':
    model = MelterPhysicsModel()
    for alloy in ['5052', '6061', '5182', '99.7']:
        res = model.calculate_theoretical_energy(65000.0, alloy_name=alloy)
        dross = model.dross_burnoff_rate_kg_hr(1150.0, 720.0, alloy_name=alloy, is_flat_bath=True)
        print(f"Alloy {alloy}: Req Gas={res['theoretical_gas_nm3']:.1f} Nm3, Dross Rate={dross:.2f} kg/h")
