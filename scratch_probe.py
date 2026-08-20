"""Pinned verification probe for PHYSICS_AUDIT_2026-08-20.md. Run at commit 612af99."""
import sys, json
sys.path.insert(0, '.')
import numpy as np, pandas as pd
from src.physics_model import MelterPhysicsModel, MAX_PLAUSIBLE_DROSS_RATE_KG_HR
from src.optimizer import HeatingCurveOptimizer
from src.config_manager import load_app_config

print("="*78); print("A. RUNAWAY: replay policy (1100C melt / 1020C hold, 25% EA), heel 5t, dt=2min")
m = MelterPhysicsModel(); o = HeatingCurveOptimizer(m)
print(f"   model constants: eps={m.emissivity_eff} LHV={m.GAS_LHV} eff_scale={m.efficiency_scale} k0={m.burnoff_k0}")
for w in [55000, 60000, 65000, 70000]:
    df, s = o.simulate_trajectory(float(w), 6.5, sp_roof_melt=1100.0, t_switch_hrs=5.85,
        sp_roof_hold=1020.0, alloy_name='5052', excess_air_pct=25.0, residual_weight_kg=5000.0, dt_mins=2.0)
    qox = s['cum_dross_kg']*0.60*31050/1e6; qf = s['cum_gas_nm3']*m.GAS_LHV/1e6
    print(f"   {w/1000:5.1f}t -> Tbath_end={s['final_bath_temp_c']:7.1f}C  dross={s['cum_dross_kg']:5.0f}kg  "
          f"gas={s['cum_gas_nm3']/(w/1000):5.1f} Nm3/t  q_ox={qox:5.1f}GJ ({qox/qf*100:3.0f}% of q_fuel {qf:.0f}GJ)")

print("\n   65t trace (burner throttled to floor from ~3.5h, bath still climbing):")
df, s = o.simulate_trajectory(65000.0, 6.5, sp_roof_melt=1100.0, t_switch_hrs=5.85, sp_roof_hold=1020.0,
    alloy_name='5052', excess_air_pct=25.0, residual_weight_kg=5000.0, dt_mins=2.0)
print(df[['time_hrs','roof_temp_c','bath_temp_c','gas_flow_nm3h','cum_dross_kg']].iloc[::30].to_string(index=False, float_format=lambda x: f"{x:8.1f}"))

class NoOx(MelterPhysicsModel):
    def dross_burnoff_rate_kg_hr(self, *a, **k): return 0.1
m2 = NoOx(); o2 = HeatingCurveOptimizer(m2)
_, s2 = o2.simulate_trajectory(65000.0, 6.5, sp_roof_melt=1100.0, t_switch_hrs=5.85, sp_roof_hold=1020.0,
    alloy_name='5052', excess_air_pct=25.0, residual_weight_kg=5000.0, dt_mins=2.0)
print(f"\n   counterfactual q_ox=0 : Tbath_end={s2['final_bath_temp_c']:.1f}C  gas={s2['cum_gas_nm3']/65:.1f} Nm3/t")
print(f"   REAL (production log n=318): median 70.0, mean 71.5 Nm3/t | SCADA 20 heats: 65-92 Nm3/t, bath end 709-792C")

print("\n" + "="*78); print("B. LOSS BUDGET (65t charge + 5t heel to 780C, real fuel)")
th = m.calculate_theoretical_energy(70000.0, '5052', 25.0, 780.0)['total_energy_kj']/1e6
real_gj = 65*70.0*m.GAS_LHV/1e6
print(f"   theoretical metal enthalpy       = {th:6.1f} GJ")
print(f"   real fuel in (65t x 70 Nm3/t)    = {real_gj:6.1f} GJ  -> real overall eff = {th/real_gj*100:.0f}%")
print(f"   UNACCOUNTED                      = {real_gj-th:6.1f} GJ over 6.5h = {(real_gj-th)*1e6/(6.5*3600):.0f} kW")
print(f"   model's total modelled loss: wall {m.wall_loss_kw:.0f} kW + hearth {m.bath_bottom_loss_kw(780):.0f} kW = {m.wall_loss_kw+m.bath_bottom_loss_kw(780):.0f} kW")

print("\n" + "="*78); print("C. combustion_efficiency() saturation (eff_scale=1.2353, clamp [0.32,0.78])")
for t in [750, 780, 950, 1000, 1050, 1100, 1180]:
    print(f"   roof {t:5.0f}C : EA10%={m.combustion_efficiency(t,10.0):.4f}  EA15%={m.combustion_efficiency(t,15.0):.4f}  EA25%={m.combustion_efficiency(t,25.0):.4f}  EA40%={m.combustion_efficiency(t,40.0):.4f}")

print("\n" + "="*78); print("D. dross kinetics: surface temperature proxy and Ea sensitivity")
for roof, bath in [(1180,700),(1180,730),(1050,730),(900,760)]:
    print(f"   roof {roof}C bath {bath}C -> Arrhenius T_surface = {0.6*(roof+273.15)+0.4*(bath+273.15)-273.15:.0f}C")
print("   rate(roof 1250C)/rate(roof 1050C) at bath 730C, flat:")
for ea in [45000., 80000., 120000., 200000.]:
    mm = MelterPhysicsModel(burnoff_ea=ea, burnoff_k0=0.8583*np.exp((ea-45000.)/(8.314*1250.)))
    r1 = mm.dross_burnoff_rate_kg_hr(1050., 730., '5052', 15., True)
    r2 = mm.dross_burnoff_rate_kg_hr(1250., 730., '5052', 15., True)
    print(f"     Ea={ea/1000:5.0f} kJ/mol -> {r2/r1:5.2f}x")
print("   is_flat_bath binary switch (2.5x multiplier) at liquidus crossing:")
print(f"     bath 649.9C (mushy) = {m.dross_burnoff_rate_kg_hr(1100.,649.9,'5052',25.,False):7.1f} kg/h")
print(f"     bath 650.1C (flat)  = {m.dross_burnoff_rate_kg_hr(1100.,650.1,'5052',25.,True):7.1f} kg/h")

print("\n" + "="*78); print("E. FULL APP PIPELINE (config/furnace_parameters.json values as the UI runs it)")
cfg = load_app_config(); p = cfg['physics']; pr = cfg['process']
ma = MelterPhysicsModel(gas_price=15., aluminum_price=75., wall_loss_kw=p['wall_loss_kw'],
    emissivity_eff=p['emissivity_eff'], burnoff_k0=p['burnoff_k0'], burnoff_ea=p['burnoff_ea'],
    hearth_area_m2=p['hearth_area_m2'], hearth_loss_ref_kw=p['hearth_loss_ref_kw'],
    dross_factor_flat=p['dross_factor_flat'], dross_net_loss_factor=pr['dross_net_loss_factor'],
    gas_lhv=p['gas_lhv_kj_nm3'], regen_base_eff=p['regen_base_eff'])
print(f"   config: eps={ma.emissivity_eff} (calibrated 0.45), LHV={ma.GAS_LHV} (calibrated 40585), "
      f"eff_scale={ma.efficiency_scale} (inherited from calibration, NOT in config)")
oa = HeatingCurveOptimizer(ma, max_gas_flow_dual_pair=p['max_gas_flow_dual_pair'],
    max_gas_flow_single_pair=p['max_gas_flow_single_pair'], min_gas_flow_nm3h=p['min_gas_flow_nm3h'])
res = oa.optimize_heating_curve(65000.0, 6.5, alloy_name='5052', residual_weight_kg=5000.0,
    target_bath_temp_c=780.0, baseline_roof_sp=1180.0, baseline_dur_melt_hrs=4.5, baseline_sp_soak=800.0,
    baseline_dur_soak_hrs=2.0, baseline_sp_hold=780.0, baseline_excess_air_pct=40.0,
    max_roof_sp_limit=1200.0, dt_mins=2.0, enable_overhead=True, actual_total_duration_hrs=5.87)
for tag in ['baseline','optimal']:
    sk = res[f'sankey_{tag}']; sm = res[f'{tag}_summary']
    ea_pct = 40.0 if tag=='baseline' else res['optimal_params']['excess_air_pct']
    air = sm['cum_gas_nm3']*9.52*(1+ea_pct/100.)
    dT = sk['q_air_preheat_gj']*1e6/(air*1.35)
    print(f"   [{tag}] gas={sm['cum_gas_nm3']:.0f} Nm3 ({sm['cum_gas_nm3']/65:.1f} Nm3/t)  dross={sm['cum_dross_kg']:.0f}kg  Tbath_end={sm['final_bath_temp_c']:.0f}C")
    print(f"        q_fuel={sk['q_fuel_gj']:.1f} q_ox={sk['q_ox_gj']:.1f} q_air_preheat={sk['q_air_preheat_gj']:.1f} GJ "
          f"-> implied air preheat dT={dT:.0f}C  (flue source ~roof temp)")
    print(f"        q_al={sk['q_al_absorbed_gj']:.1f} GJ -> thermal_eff_fuel={sk['thermal_eff_fuel_pct']:.1f}%")
print(f"   optimal params: {res['optimal_params']}")
print(f"   claimed savings: {res['savings']}")
print(f"   excess-air grid was [10.0, 12.5, 15.0, 40.0] -> chose {res['optimal_params']['excess_air_pct']} (grid minimum)")
