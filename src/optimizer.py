"""
Heating Curve Optimizer Module for 80T Aluminum Static Melter.
Incorporates Alloy Property Database, Air-Fuel Excess Ratio, and 4-Burner 2-Pair Regenerative Switching.
"""

import numpy as np
import pandas as pd
from typing import Dict, Tuple, List, Optional

try:
    from src.physics_model import (
        MelterPhysicsModel,
        get_alloy_props,
        MAX_GAS_FLOW_DUAL_PAIR,
        MAX_GAS_FLOW_SINGLE_PAIR,
    )
except ImportError:
    from physics_model import (
        MelterPhysicsModel,
        get_alloy_props,
        MAX_GAS_FLOW_DUAL_PAIR,
        MAX_GAS_FLOW_SINGLE_PAIR,
    )


def format_hours_to_hhmm(hours: float) -> str:
    """Converts decimal hours (e.g. 2.4) to string format '02:24'."""
    total_mins = int(round(max(0.0, float(hours)) * 60))
    h = total_mins // 60
    m = total_mins % 60
    return f"{h:02d}:{m:02d}"


def parse_hhmm_to_hours(val, default: float = 0.0) -> float:
    """Converts hh:mm string (e.g. '04:00') or float to decimal hours."""
    if val is None:
        return default
    try:
        val_str = str(val).strip()
        if ':' in val_str:
            parts = val_str.split(':')
            h = int(parts[0])
            m = int(parts[1])
            return max(0.0, h + m / 60.0)
        else:
            return max(0.0, float(val_str))
    except Exception:
        return default


class HeatingCurveOptimizer:
    """Simulates and optimizes heating curves for aluminum melting furnaces."""

    def __init__(
        self,
        physics_model: Optional[MelterPhysicsModel] = None,
        max_gas_flow_dual_pair: float = MAX_GAS_FLOW_DUAL_PAIR,
        max_gas_flow_single_pair: float = MAX_GAS_FLOW_SINGLE_PAIR,
        min_gas_flow_nm3h: float = 50.0,
        **kwargs
    ):
        self.model = physics_model if physics_model is not None else MelterPhysicsModel()
        self.max_gas_flow_dual_pair = max_gas_flow_dual_pair
        self.max_gas_flow_single_pair = max_gas_flow_single_pair
        self.min_gas_flow_nm3h = min_gas_flow_nm3h

    def simulate_trajectory(
        self,
        charged_weight_kg: float,
        target_duration_hrs: float,
        sp_roof_melt: float,
        t_switch_hrs: float,
        sp_roof_hold: float = 780.0,
        alloy_name: str = '5052',
        excess_air_pct: float = 15.0,
        initial_bath_temp_c: float = 25.0,
        initial_roof_temp_c: float = 850.0,
        target_bath_temp_c: float = 780.0,
        dt_mins: float = 1.0,
        residual_weight_kg: float = 0.0,
        residual_temp_c: Optional[float] = None,
        sp_roof_soak: Optional[float] = None,
        t_soak_end_hrs: Optional[float] = None,
    ) -> Tuple[pd.DataFrame, Dict[str, float]]:
        """Simulates time-step thermodynamic progression with alloy properties & 4-burner 2-pair states."""
        dt_hrs = dt_mins / 60.0
        n_steps = int(np.round(target_duration_hrs / dt_hrs))

        props = get_alloy_props(alloy_name)
        solidus = props['solidus']
        liquidus = props['liquidus']
        latent_h = props['latent_heat']
        cp_liq = props['cp_liquid']
        cp_solid = 0.90

        if residual_temp_c is None:
            residual_temp_c = liquidus

        total_weight_kg = charged_weight_kg + residual_weight_kg
        cap_solid_kj = total_weight_kg * cp_solid * (solidus - initial_bath_temp_c)
        cap_latent_kj = total_weight_kg * latent_h

        def energy_to_bath_temp(energy_kj: float) -> float:
            if energy_kj < cap_solid_kj:
                return initial_bath_temp_c + (energy_kj / cap_solid_kj) * (solidus - initial_bath_temp_c)
            elif energy_kj < (cap_solid_kj + cap_latent_kj):
                frac = (energy_kj - cap_solid_kj) / cap_latent_kj
                return solidus + frac * (liquidus - solidus)
            else:
                liquid_energy_kj = energy_kj - cap_solid_kj - cap_latent_kj
                return liquidus + liquid_energy_kj / (total_weight_kg * cp_liq)

        if residual_weight_kg > 0:
            current_energy_kj = self.model.calculate_theoretical_energy(
                weight_kg=residual_weight_kg,
                alloy_name=alloy_name,
                initial_temp_c=initial_bath_temp_c,
                target_temp_c=residual_temp_c,
            )['total_energy_kj']
        else:
            current_energy_kj = 0.0

        current_roof_temp = initial_roof_temp_c
        current_bath_temp = energy_to_bath_temp(current_energy_kj)

        cumulative_gas_nm3 = 0.0
        cumulative_dross_kg = 0.0
        
        times = []
        sp_roofs = []
        roof_temps = []
        bath_temps = []
        gas_flows = []
        cum_gases = []
        cum_drosses = []
        phases = []
        burner_modes = []
        flue_o2_pcts = []
        
        flue_o2 = self.model.calculate_flue_oxygen_pct(excess_air_pct)
        
        for step in range(n_steps):
            t_hr = step * dt_hrs
            times.append(t_hr)
            
            # Stepwise Discrete Multi-Step Setpoint Profile
            # Step 1 (Main Melt): 0 <= t < t_switch_hrs -> sp_roof_melt (Constant SP)
            # Step 2 (Flat Bath): t_switch_hrs <= t < t_soak_end_hrs -> sp_roof_soak (Constant SP)
            # Step 3 (Hold & Tap): t >= t_soak_end_hrs -> sp_roof_hold (Constant SP)
            if t_hr < t_switch_hrs:
                sp_roof = sp_roof_melt
                phase = '第1段: 主熔化段 (Melt)'
                burner_mode = 'Dual Pair (交替全火)'
                max_gas_limit = self.max_gas_flow_dual_pair
            elif t_soak_end_hrs is not None and sp_roof_soak is not None and t_hr < t_soak_end_hrs:
                sp_roof = sp_roof_soak
                phase = '第2段: 平湯昇溫段 (Flat Bath)'
                burner_mode = 'Dual Pair (交替中火)'
                max_gas_limit = self.max_gas_flow_dual_pair
            else:
                sp_roof = sp_roof_hold
                phase = '第3段: 出湯保溫段 (Hold & Tap)' if (t_soak_end_hrs is not None and sp_roof_soak is not None) else '第2段: 出湯保溫段 (Hold & Tap)'
                burner_mode = 'Single Pair (交替微火)'
                max_gas_limit = self.max_gas_flow_single_pair

            sp_roofs.append(sp_roof)
            burner_modes.append(burner_mode)
            flue_o2_pcts.append(flue_o2)
            
            # Roof temperature response
            k_roof_response = 15.0 # °C/min max response rate
            roof_err = sp_roof - current_roof_temp
            current_roof_temp += np.clip(roof_err * 0.25, -k_roof_response, k_roof_response)
            roof_temps.append(current_roof_temp)
            
            is_flat_bath = (current_bath_temp >= liquidus)

            # Heat transfer between roof/combustion space and bath (Radiant + Convection - Hearth Loss)
            q_rad_kw = self.model.radiant_heat_flux_kw(current_roof_temp, current_bath_temp, is_flat_bath=is_flat_bath)
            q_conv_kw = 1.2 * self.model.HEARTH_AREA_M2 * (current_roof_temp - current_bath_temp) * (0.010 if is_flat_bath else 0.015)
            q_hearth_loss_kw = self.model.bath_bottom_loss_kw(current_bath_temp)
            q_net_to_bath_kw = q_rad_kw + q_conv_kw - q_hearth_loss_kw
            
            # Combustion efficiency considering excess air ratio
            eff = self.model.combustion_efficiency(current_roof_temp, excess_air_pct=excess_air_pct)
            
            # DCS PID / High-Limit Throttle Behavior:
            # When bath reaches target_bath_temp_c (e.g. 780°C) or roof setpoint is reached:
            # Burners throttle down to maintain heat balance rather than forcing runaway overheating.
            if current_bath_temp >= (target_bath_temp_c + 2.0):
                # Molten bath is at or above target tap temperature -> throttle burners to holding
                q_hold_needed_kw = self.model.wall_loss_kw + q_hearth_loss_kw
                gas_flow_unclamp = (q_hold_needed_kw * 3600.0) / self.model.GAS_LHV if self.model.GAS_LHV > 0 else 0.0
                gas_flow_nm3h = max(self.min_gas_flow_nm3h, min(self.max_gas_flow_single_pair, gas_flow_unclamp))
                q_combustion_actual_kw = (gas_flow_nm3h * self.model.GAS_LHV) / 3600.0 if self.model.GAS_LHV > 0 else 0.0
                # Bath temperature is gently clamped to maintain target
                q_bath_actual_kw = max(-30.0, min(30.0, (q_combustion_actual_kw - self.model.wall_loss_kw) * eff - q_hearth_loss_kw))
            elif q_net_to_bath_kw > 0:
                q_combustion_needed_kw = (q_rad_kw + q_conv_kw) / eff + self.model.wall_loss_kw
                gas_flow_unclamp = (q_combustion_needed_kw * 3600.0) / self.model.GAS_LHV if self.model.GAS_LHV > 0 else 0.0
                gas_flow_nm3h = min(max_gas_limit, gas_flow_unclamp)
                
                q_combustion_actual_kw = (gas_flow_nm3h * self.model.GAS_LHV) / 3600.0 if self.model.GAS_LHV > 0 else 0.0
                q_bath_max_kw = max(0.0, (q_combustion_actual_kw - self.model.wall_loss_kw) * eff)
                q_bath_actual_kw = min(q_net_to_bath_kw, q_bath_max_kw - q_hearth_loss_kw)
            else:
                # Bath is hotter than roof/loss -> cool down
                q_combustion_needed_kw = self.model.wall_loss_kw
                gas_flow_unclamp = (q_combustion_needed_kw * 3600.0) / self.model.GAS_LHV if self.model.GAS_LHV > 0 else 0.0
                gas_flow_nm3h = min(max_gas_limit, max(self.min_gas_flow_nm3h, gas_flow_unclamp))
                q_bath_actual_kw = q_net_to_bath_kw

            q_step_kj = q_bath_actual_kw * (dt_mins * 60.0)
            gas_step_nm3 = gas_flow_nm3h * dt_hrs
            cumulative_gas_nm3 += gas_step_nm3
            
            # Alloy-specific dross oxidation burnoff
            dross_rate_kghr = self.model.dross_burnoff_rate_kg_hr(
                roof_temp_c=current_roof_temp,
                bath_temp_c=current_bath_temp,
                alloy_name=alloy_name,
                excess_air_pct=excess_air_pct,
                is_flat_bath=is_flat_bath
            )
            dross_step_kg = dross_rate_kghr * dt_hrs
            cumulative_dross_kg += dross_step_kg
            
            # Bath state progression (dynamic energy accumulation and dissipation)
            current_energy_kj += q_step_kj
            current_bath_temp = energy_to_bath_temp(current_energy_kj)

            bath_temps.append(current_bath_temp)
            gas_flows.append(gas_flow_nm3h)
            cum_gases.append(cumulative_gas_nm3)
            cum_drosses.append(cumulative_dross_kg)
            phases.append(phase)

        df_sim = pd.DataFrame({
            'time_hrs': times,
            'sp_roof_c': sp_roofs,
            'roof_temp_c': roof_temps,
            'bath_temp_c': bath_temps,
            'gas_flow_nm3h': gas_flows,
            'cum_gas_nm3': cum_gases,
            'cum_dross_kg': cum_drosses,
            'phase': phases,
            'burner_mode': burner_modes,
            'flue_o2_pct': flue_o2_pcts,
        })
        
        cost_breakdown = self.model.compute_heat_cost(cumulative_gas_nm3, cumulative_dross_kg)
        cost_breakdown['final_bath_temp_c'] = current_bath_temp
        cost_breakdown['cum_gas_nm3'] = cumulative_gas_nm3
        cost_breakdown['cum_dross_kg'] = cumulative_dross_kg
        cost_breakdown['alloy_name'] = alloy_name
        cost_breakdown['excess_air_pct'] = excess_air_pct
        cost_breakdown['flue_o2_pct'] = flue_o2
        
        return df_sim, cost_breakdown

    def run_baseline_scenario(
        self,
        charged_weight_kg: float,
        target_duration_hrs: float,
        alloy_name: str = '5052',
        baseline_roof_sp: float = 1180.0,
        baseline_switch_hrs: Optional[float] = None,
        baseline_excess_air_pct: float = 25.0,
        target_bath_temp_c: float = 780.0,
        dt_mins: float = 1.0,
        residual_weight_kg: float = 0.0,
        residual_temp_c: Optional[float] = None,
        baseline_dur_melt_hrs: Optional[float] = None,
        baseline_sp_soak: Optional[float] = None,
        baseline_dur_soak_hrs: Optional[float] = 0.0,
        baseline_sp_hold: float = 780.0,
    ) -> Tuple[pd.DataFrame, Dict[str, float]]:
        """Simulates baseline plant practice:
        Step 1: 0 to baseline_dur_melt_hrs (Default: target_duration_hrs, 1180°C continuous to end).
        Step 2: (optional) Flat bath soak mode.
        Step 3: Bath mode holding SP ~780°C (Single Pair holding fire).
        """
        dur_melt = baseline_dur_melt_hrs if baseline_dur_melt_hrs is not None else (baseline_switch_hrs if baseline_switch_hrs is not None else target_duration_hrs)
        dur_soak = baseline_dur_soak_hrs if baseline_dur_soak_hrs is not None else 0.0

        if dur_soak > 0.05 and baseline_sp_soak is not None:
            t_sw1 = min(target_duration_hrs, dur_melt)
            t_sw2 = min(target_duration_hrs, dur_melt + dur_soak)
            return self.simulate_trajectory(
                charged_weight_kg=charged_weight_kg,
                target_duration_hrs=target_duration_hrs,
                sp_roof_melt=baseline_roof_sp,
                t_switch_hrs=t_sw1,
                sp_roof_soak=baseline_sp_soak,
                t_soak_end_hrs=t_sw2,
                sp_roof_hold=baseline_sp_hold,
                alloy_name=alloy_name,
                excess_air_pct=baseline_excess_air_pct,
                target_bath_temp_c=target_bath_temp_c,
                dt_mins=dt_mins,
                residual_weight_kg=residual_weight_kg,
                residual_temp_c=residual_temp_c,
            )
        else:
            return self.simulate_trajectory(
                charged_weight_kg=charged_weight_kg,
                target_duration_hrs=target_duration_hrs,
                sp_roof_melt=baseline_roof_sp,
                t_switch_hrs=min(target_duration_hrs, dur_melt),
                sp_roof_hold=baseline_sp_hold,
                alloy_name=alloy_name,
                excess_air_pct=baseline_excess_air_pct,
                target_bath_temp_c=target_bath_temp_c,
                dt_mins=dt_mins,
                residual_weight_kg=residual_weight_kg,
                residual_temp_c=residual_temp_c,
            )

    def optimize_heating_curve(
        self,
        charged_weight_kg: float,
        discharge_deadline_hrs: float,
        alloy_name: str = '5052',
        baseline_roof_sp: float = 1180.0,
        baseline_switch_hrs: Optional[float] = None,
        baseline_excess_air_pct: float = 20.0,
        target_bath_temp_c: float = 780.0,
        max_roof_sp_limit: float = 1200.0,
        dt_mins: float = 1.0,
        residual_weight_kg: float = 0.0,
        residual_temp_c: Optional[float] = None,
        baseline_dur_melt_hrs: Optional[float] = None,
        baseline_sp_soak: Optional[float] = None,
        baseline_dur_soak_hrs: Optional[float] = 0.0,
        baseline_sp_hold: float = 780.0,
        enable_overhead: bool = True,
        charge_door_open_mins: float = 60.0,
        dross_door_open_mins: float = 20.0,
        reversal_loss_pct: float = 4.0,
        refractory_reheat_gj: float = 7.0,
        actual_total_duration_hrs: Optional[float] = None,
        **kwargs
    ) -> Dict:
        """Finds the optimal discrete multi-step schedule (Step 1 Melt -> Step 2 Flat -> Step 3 Hold)
        that minimizes gas + dross cost, SUBJECT TO reaching target_bath_temp_c by discharge_deadline_hrs.
        Also computes field dynamic operational overhead losses for full-cycle plant alignment.
        """
        best_cost = float('inf')
        best_params = None
        best_df_sim = None
        best_summary = None

        candidate_sp_melts = [1100.0, 1120.0, 1140.0, 1150.0, 1160.0, 1180.0, 1200.0, 1220.0, 1250.0]
        sp_melts = [sp for sp in candidate_sp_melts if sp <= max_roof_sp_limit]
        if max_roof_sp_limit not in sp_melts:
            sp_melts.append(max_roof_sp_limit)
        sp_melts = sorted(list(set(sp_melts)))
        
        t_sw1_grid = np.linspace(discharge_deadline_hrs * 0.40, discharge_deadline_hrs * 0.70, 5)
        sp_soaks = [950.0, 1000.0, 1050.0]
        sp_holds = [750.0, 780.0]
        excess_airs = [10.0, 12.5, 15.0, baseline_excess_air_pct]

        for sp_m in sp_melts:
            for t_sw1 in t_sw1_grid:
                for sp_soak in sp_soaks:
                    t_sw2 = min(discharge_deadline_hrs * 0.88, t_sw1 + 1.2)
                    for sp_h in sp_holds:
                        for ex_air in excess_airs:
                            df_sim, summary = self.simulate_trajectory(
                                charged_weight_kg=charged_weight_kg,
                                target_duration_hrs=discharge_deadline_hrs,
                                sp_roof_melt=sp_m,
                                t_switch_hrs=t_sw1,
                                sp_roof_soak=sp_soak,
                                t_soak_end_hrs=t_sw2,
                                sp_roof_hold=sp_h,
                                alloy_name=alloy_name,
                                residual_weight_kg=residual_weight_kg,
                                residual_temp_c=residual_temp_c,
                                excess_air_pct=ex_air,
                                dt_mins=dt_mins,
                            )
                            # Primary constraint: must reach target bath temp within deadline
                            if summary['final_bath_temp_c'] >= (target_bath_temp_c - 2.0):
                                if summary['total_cost'] < best_cost:
                                    best_cost = summary['total_cost']
                                    best_params = (sp_m, t_sw1, sp_soak, t_sw2, sp_h, ex_air)
                                    best_df_sim = df_sim
                                    best_summary = summary

        # Fallback if no solution reaches target bath temp
        if best_params is None:
            df_sim, summary = self.simulate_trajectory(
                charged_weight_kg=charged_weight_kg,
                target_duration_hrs=discharge_deadline_hrs,
                sp_roof_melt=max_roof_sp_limit,
                t_switch_hrs=discharge_deadline_hrs * 0.60,
                sp_roof_soak=1000.0,
                t_soak_end_hrs=discharge_deadline_hrs * 0.85,
                sp_roof_hold=780.0,
                alloy_name=alloy_name,
                residual_weight_kg=residual_weight_kg,
                residual_temp_c=residual_temp_c,
                excess_air_pct=baseline_excess_air_pct,
                dt_mins=dt_mins,
            )
            best_params = (max_roof_sp_limit, discharge_deadline_hrs * 0.60, 1000.0, discharge_deadline_hrs * 0.85, 780.0, baseline_excess_air_pct)
            best_df_sim = df_sim
            best_summary = summary

        # Baseline simulation
        df_base, summary_base = self.run_baseline_scenario(
            charged_weight_kg=charged_weight_kg,
            target_duration_hrs=discharge_deadline_hrs,
            alloy_name=alloy_name,
            baseline_roof_sp=baseline_roof_sp,
            baseline_switch_hrs=baseline_switch_hrs,
            baseline_excess_air_pct=baseline_excess_air_pct,
            dt_mins=dt_mins,
            residual_weight_kg=residual_weight_kg,
            residual_temp_c=residual_temp_c,
            baseline_dur_melt_hrs=baseline_dur_melt_hrs,
            baseline_sp_soak=baseline_sp_soak,
            baseline_dur_soak_hrs=baseline_dur_soak_hrs,
            baseline_sp_hold=baseline_sp_hold,
            target_bath_temp_c=target_bath_temp_c,
        )

        # Field Operational Overhead Losses Calculation
        overhead_base = self.model.calculate_field_overhead_losses(
            charged_weight_kg=charged_weight_kg,
            net_melt_gas_nm3=summary_base['cum_gas_nm3'],
            target_duration_hrs=discharge_deadline_hrs,
            actual_total_duration_hrs=actual_total_duration_hrs,
            charge_door_open_mins=charge_door_open_mins,
            dross_door_open_mins=dross_door_open_mins,
            reversal_loss_pct=reversal_loss_pct,
            refractory_reheat_gj=refractory_reheat_gj,
            enable_overhead=enable_overhead,
        )
        overhead_opt = self.model.calculate_field_overhead_losses(
            charged_weight_kg=charged_weight_kg,
            net_melt_gas_nm3=best_summary['cum_gas_nm3'],
            target_duration_hrs=discharge_deadline_hrs,
            actual_total_duration_hrs=actual_total_duration_hrs,
            charge_door_open_mins=charge_door_open_mins,
            dross_door_open_mins=dross_door_open_mins,
            reversal_loss_pct=reversal_loss_pct,
            refractory_reheat_gj=refractory_reheat_gj,
            enable_overhead=enable_overhead,
        )

        # Attach overhead breakdown and full total gas
        summary_base['overhead'] = overhead_base
        summary_base['net_gas_nm3'] = summary_base['cum_gas_nm3']
        summary_base['overhead_gas_nm3'] = overhead_base['total_overhead_gas_nm3']
        summary_base['total_gas_nm3'] = summary_base['net_gas_nm3'] + overhead_base['total_overhead_gas_nm3']
        summary_base['cum_gas_nm3'] = summary_base['total_gas_nm3'] if enable_overhead else summary_base['net_gas_nm3']
        summary_base['gas_cost'] = summary_base['cum_gas_nm3'] * self.model.gas_price
        summary_base['total_cost'] = summary_base['gas_cost'] + summary_base['dross_cost']

        best_summary['overhead'] = overhead_opt
        best_summary['net_gas_nm3'] = best_summary['cum_gas_nm3']
        best_summary['overhead_gas_nm3'] = overhead_opt['total_overhead_gas_nm3']
        best_summary['total_gas_nm3'] = best_summary['net_gas_nm3'] + overhead_opt['total_overhead_gas_nm3']
        best_summary['cum_gas_nm3'] = best_summary['total_gas_nm3'] if enable_overhead else best_summary['net_gas_nm3']
        best_summary['gas_cost'] = best_summary['cum_gas_nm3'] * self.model.gas_price
        best_summary['total_cost'] = best_summary['gas_cost'] + best_summary['dross_cost']

        # Sankey diagrams calculation
        sankey_opt = self.model.calculate_sankey_energy_balance(
            cum_gas_nm3=best_summary['cum_gas_nm3'],
            cum_dross_kg=best_summary['cum_dross_kg'],
            charged_weight_kg=charged_weight_kg,
            residual_weight_kg=residual_weight_kg,
            duration_hrs=discharge_deadline_hrs,
            final_bath_temp_c=best_summary['final_bath_temp_c'],
            alloy_name=alloy_name,
            excess_air_pct=float(best_params[5]),
        )
        best_summary['sankey_balance'] = sankey_opt

        sankey_base = self.model.calculate_sankey_energy_balance(
            cum_gas_nm3=summary_base['cum_gas_nm3'],
            cum_dross_kg=summary_base['cum_dross_kg'],
            charged_weight_kg=charged_weight_kg,
            residual_weight_kg=residual_weight_kg,
            duration_hrs=discharge_deadline_hrs,
            final_bath_temp_c=summary_base['final_bath_temp_c'],
            alloy_name=alloy_name,
            excess_air_pct=baseline_excess_air_pct,
        )
        summary_base['sankey_balance'] = sankey_base
        
        cost_savings_twd = summary_base['total_cost'] - best_summary['total_cost']
        cost_savings_pct = (cost_savings_twd / summary_base['total_cost']) * 100.0 if summary_base['total_cost'] > 0 else 0.0
        gas_savings_nm3 = summary_base['cum_gas_nm3'] - best_summary['cum_gas_nm3']
        net_gas_savings_nm3 = summary_base['net_gas_nm3'] - best_summary['net_gas_nm3']
        dross_savings_kg = summary_base['cum_dross_kg'] - best_summary['cum_dross_kg']
        deadline_met = best_summary['final_bath_temp_c'] >= (target_bath_temp_c - 5.0)

        t_sw1_val = float(best_params[1])
        t_sw2_val = float(best_params[3])
        dur1_val = t_sw1_val
        dur2_val = max(0.0, t_sw2_val - t_sw1_val)
        dur3_val = max(0.0, discharge_deadline_hrs - t_sw2_val)

        recipe_steps = [
            {
                'step': 1,
                'mode_name': '主融化模式 (Melt Mode)',
                'sp_roof_c': float(best_params[0]),
                'duration_hrs': round(dur1_val, 2),
                'duration_hhmm': format_hours_to_hhmm(dur1_val),
                'interval_hhmm': f"00:00 ~ {format_hours_to_hhmm(t_sw1_val)}",
                'burner_mode': '雙對燒嘴交替大火 (Dual Pair)',
                'goal': '高功率全火快速熔解固態料堆'
            },
            {
                'step': 2,
                'mode_name': '平湯昇溫模式 (Flat Bath Mode)',
                'sp_roof_c': float(best_params[2]),
                'duration_hrs': round(dur2_val, 2),
                'duration_hhmm': format_hours_to_hhmm(dur2_val),
                'interval_hhmm': f"{format_hours_to_hhmm(t_sw1_val)} ~ {format_hours_to_hhmm(t_sw2_val)}",
                'burner_mode': '雙對燒嘴交替中火',
                'goal': '全融平湯及時降溫，抑止鋁液高溫氧化燒損'
            },
            {
                'step': 3,
                'mode_name': '湯溫保溫模式 (Bath Mode)',
                'sp_roof_c': float(best_params[4]),
                'duration_hrs': round(dur3_val, 2),
                'duration_hhmm': format_hours_to_hhmm(dur3_val),
                'interval_hhmm': f"{format_hours_to_hhmm(t_sw2_val)} ~ {format_hours_to_hhmm(discharge_deadline_hrs)}",
                'burner_mode': '單對燒嘴交替微火 (Single Pair)',
                'goal': f'維持出湯目標湯溫 {target_bath_temp_c:.0f}°C，熱平衡待出湯'
            }
        ]

        return {
            'optimal_params': {
                'sp_roof_melt': float(best_params[0]),
                't_switch_hrs': round(float(best_params[1]), 2),
                'sp_roof_soak': float(best_params[2]),
                't_soak_end_hrs': round(float(best_params[3]), 2),
                'sp_roof_hold': float(best_params[4]),
                'excess_air_pct': float(best_params[5]),
                'flue_o2_pct': round(self.model.calculate_flue_oxygen_pct(best_params[5]), 2),
            },
            'recipe_steps': recipe_steps,
            'discharge_deadline_hrs': discharge_deadline_hrs,
            'deadline_met': bool(deadline_met),
            'optimal_summary': best_summary,
            'optimal_trajectory': best_df_sim,
            'baseline_summary': summary_base,
            'baseline_trajectory': df_base,
            'sankey_optimal': sankey_opt,
            'sankey_baseline': sankey_base,
            'savings': {
                'cost_savings_twd': round(float(cost_savings_twd), 1),
                'cost_savings_pct': round(float(cost_savings_pct), 2),
                'gas_savings_nm3': round(float(gas_savings_nm3), 1),
                'net_gas_savings_nm3': round(float(net_gas_savings_nm3), 1),
                'dross_savings_kg': round(float(dross_savings_kg), 2),
            }
        }


if __name__ == '__main__':
    opt = HeatingCurveOptimizer()
    res = opt.optimize_heating_curve(65000.0, 6.0, alloy_name='5052')
    print("Optimal Params (5052):", res['optimal_params'])
    print("Savings (5052):", res['savings'])
    print("Baseline Gas Total:", res['baseline_summary']['total_gas_nm3'], "Net:", res['baseline_summary']['net_gas_nm3'])
    print("Optimal Gas Total:", res['optimal_summary']['total_gas_nm3'], "Net:", res['optimal_summary']['net_gas_nm3'])
