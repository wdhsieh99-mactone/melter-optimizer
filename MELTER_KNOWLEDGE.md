# 80T Aluminum Static Melting Furnace — Knowledge Base

Compiled from the Mechatherm O&M manual (`40522-Melting Furnace Manual.pdf`), production/sensor
data files, paper operation-record forms, and the existing `melter2` codebase. Purpose: ground
truth reference for building the heating-curve optimizer (`src/`, `app.py`).

## 1. Plant identity

- **OEM**: Mechatherm International Ltd (UK), Contract No. 40522.
- **Owner/site**: China Steel Aluminium Corporation (CSAC), Taiwan.
- **Equipment refs**: MFA, MFB, MFC — three (structurally identical) 80T static melting furnaces.
  The production log workbook also carries heats for MFQ and MF7 (likely other furnaces/lines in
  the same family, same 52-column schema).
- **Design duty**: continuous operation, 325 days/yr, 24 h/day.
- **Sensor dataset in this repo** (`mfa_20260707-0714_wide.csv`) is 5-second-interval tag data for
  **MFA only**, covering 2026-07-07 → 2026-07-14 (ROC year 115).
- **Furnace role**: melts scrap/ingot charge, holds it at a metal-transfer temperature, then taps
  molten aluminum out to a downstream holding furnace (HF) → casting machine.

## 2. Physical / thermal construction

- **Casing**: 16 mm mild steel plate, tank-like, welded lattice hearth structure, FEA-verified (ANSYS).
- **Bath**: 10,500 mm wide × 6,300 mm long → **bath area 66.15 m²**. Depth 535 mm at cill,
  610 mm at tap-out. Hearth sloped 35° toward the door for cleaning; drain slope toward tap-out block.
- **Capacity**: 80 tonnes liquid aluminum in the main chamber (density 2,323 kg/m³).
- **Charging door**: single opening, 10,500 mm wide × 1,800 mm high, hydraulic lift (2 cylinders),
  pneumatic clamp, door weight 20 t, lift time < 20 s.
- **Refractory**: castable monolithic, hot-face freeze plane designed at **650°C** with metal at
  **750°C**. Layer stack varies by zone (hearth 495 mm total, roof 350 mm, door 325 mm, etc. — see
  manual §1.1.2.1 for full material/thickness table per zone: Albond, Standard Castable, Block 607,
  Midcast/Insulite/Calcium-Silica board on upper sidewalls, Mulcast/Coolcast/Rerablanket on roof/door).
- **Metal temperature range in service**: **690–750°C**.
- **Stack**: 1,500 mm × 25 m high, shared with the corresponding holding furnace (e.g. MFA shares
  with HFA).

`src/physics_model.py`'s `HEARTH_AREA_M2 = 45.0` does **not** match the manual's bath area of
66.15 m² — worth reconciling (45 m² may be an intentional "effective radiating area" assumption,
but it isn't documented as such in the code).

## 3. Burner / combustion system

- **Type**: Bloom **LumiFlame 1150-200-300**, ultra-low-NOx **regenerative** burners.
- **Configuration**: **4 burners in 2 pairs** (Pair A / Pair B). Within a pair, one burner fires
  while its partner exhausts waste gas down through its own regenerator bed of alumina/ceramic
  packing to preheat it; roles reverse on a cycle (~60–90 s per manual's rule of thumb in the
  existing Streamlit copy — the manual itself doesn't state an exact reversal period but describes
  the mechanism in §1.1 "Regenerative Combustion System"). Regenerative heat recovery is high
  (Streamlit tab cites 70%+, consistent with regenerative burner practice, though not an explicit
  manual figure).
- **Total burner capacity**: **13,760,000 kcal/hr (55,000,000 Btu/hr)**.
- **Burner exit velocity**: ~75 m/s (LumiFlame 1150), designed to re-entrain furnace gases and
  boost circulation/melt rate without excessive burner-port velocity.
- **Regenerator beds**: ~3,680 kg per bed, ~1,600 kg of bed media (ceramic balls). Expected media
  change interval: **12–16 weeks**; cooled with combustion air for ~15 min before servicing; change
  both pairs' packing together to avoid asymmetric air distribution.
- **Turndown**: at low-fire/holding conditions, one burner pair can be switched off automatically
  to save fuel; duty burner within the firing pair toggles automatically. This matches the code's
  "Dual Pair (up to 2 Flames Alternating)" vs "Single Pair (1 Flame Alternating)" modeling in
  `optimizer.py` — corrected from an earlier "(4 burners)"/"(2 burners)" labeling that implied
  simultaneous firing counts; manual sec. 1.4.56 is explicit that only one burner per pair fires
  at any one time (its twin exhausts/preheats), so at most 2 flames burn at once even at full
  dual-pair firing. See `REGENERATIVE_SYSTEM_ANALYSIS.md` sec. 3 for the full derivation,
  including empirical confirmation via the `tt111-114` sensor tags (full reversal period ~240s).
- **Combustion air fan**: 1 centrifugal fan, 17,200 Nm³/hr @ 90 mbar, 75 kW motor.
- **Exhaust/waste-gas fan**: 1 centrifugal fan, 32,000 Am³/hr @ 200°C, 59 mbar, 132 kW motor
  (VSD-controlled per tag `VSD 006`).
- **Roof/exhaust split**: ~80–90% of exhaust drawn through the regenerative beds; ~10–20% via a
  refractory-lined bypass stack (used when both burners are off, damper opens).
- **Motors, total installed power**: 313.5 kW nominal (burner system, hydraulic packs, filtration).

## 4. Fuel & air-fuel ratio control

- **Fuel**: Natural gas. Methane ≥85 mol%, ≤2.0 mol% butane+heavier, ≤1.0 mol% N₂,
  ≤35 mg/Nm³ sulphur.
- **Gross heating value: 9,700 kcal/Nm³** (≈ 40,600 kJ/Nm³ using 4.184 kJ/kcal). **This differs
  from `physics_model.py`'s `GAS_LHV = 36000.0 kJ/Nm3` (≈8,600 kcal/Nm³) by ~11%** — the code's
  constant is lower than the manual's *gross* value (some of that gap is expected since gross ≠
  net/LHV, but the code should confirm it's using a genuine LHV figure appropriate for this gas
  composition rather than an arbitrary round number).
- **Peak gas demand**: 1,700 Nm³/hr (service design figure — higher than the burner nameplate
  capacity of ~1,418 Nm³/hr implied by 13.76M kcal/hr ÷ 9,700 kcal/Nm³, suggesting some margin/
  simultaneity allowance in the service sizing).
- **Air-fuel control philosophy**: "air-lead" system — air is set first, fuel trimmed to ratio,
  but the fuel/air ratio (RT 104 loop) is continuously monitored and will override the separate
  air control in gas-rich or air-rich excursions.
  - `Fuel/Air Ratio = R + (R × X / 100)` where R = stoichiometric ratio setpoint, X = excess air
    setpoint (%). This is exactly the form the manual documents (not necessarily an oxidizer
    stoichiometry the code needs to re-derive — R is an HMI-settable parameter, not hardcoded).
  - `physics_model.py`'s `STOICH_AIR_GAS_RATIO = 9.52 Nm3 air / Nm3 gas` is a reasonable
    stoichiometric ratio for ~85–95% methane NG and is consistent with (though not literally
    stated as a number in) the manual.
- **Excess air**: HMI-adjustable 0–30%. **Design/nameplate maximum excess air is 15% at high
  fire.** "Dirty scrap mode" or very low furnace-temperature setpoints trigger a higher excess-air
  selection automatically.
- **Oxygen trim control (AC 104 / AT 104)**: closed loop on flue O₂, active only while burners are
  at high fire.
  - O₂ setpoint HMI range: 1–5%, **default 3%**.
  - Target/practical band described elsewhere in the manual: **1–3% O₂**.
  - Trim logic: if O₂ stays below setpoint for a timer period, excess-air setpoint is bumped
    **+0.5%** and the timer resets (repeats until at setpoint or max excess-air reached); mirror
    logic decreases by 0.5% when O₂ is persistently above setpoint.
  - `physics_model.py`'s `calculate_flue_oxygen_pct()` approximation
    `O2% = 21·X / (1 + 1.05·X)` (X = excess air fraction) is a standalone empirical fit, not from
    the manual, but its output (e.g. ~2.5% O₂ at 15% excess air) lands inside the manual's stated
    1–3% target band, so it's a reasonable proxy.
- **Furnace pressure**: PID-controlled, setpoint range −0.5 to +0.5 mbar, **default +0.05 mbar**
  (slightly positive, to limit cold-air ingress). Controlled via the ZV 209 exhaust damper; below
  20% damper opening, the air-curtain combustion air also participates in pressure control. Sensor
  tag `mfa_pt209_pv` in the CSV corresponds directly to this loop.

## 5. Temperature control architecture

Two independent PID loops, cascaded:

- **TC 200 – Bath Temperature Control**: PV = bath thermocouple (`TT 200` → CSV `mfa_tt200_pv`).
  Setpoint is alloy/transfer-distance dependent, operator-entered (and in production, driven from
  a higher-level APICS system). Output of this loop becomes the **setpoint** for the roof loop
  when in Bath Hold mode (see cascade curve below) — it does not directly command burner firing
  rate.
- **TC 201 – Roof Temperature Control**: PV = hottest of two roof thermocouples per chamber
  (`TT 201AB/BB` → CSV `mfa_tt201_pv`), because the manual explicitly uses the max of the two, not
  an average, to protect refractory while still allowing full melt capacity. Output drives burner
  firing rate. Manual states this is typically set to a high fixed value — **"may be 1200°C"** —
  and left alone during production melting for minimum melt time / max efficiency. This matches
  the Streamlit slider's default ceiling of 1200°C.
- **Cascade curve (Bath Hold mode → roof setpoint)**: bath error (bath SP − bath PV), clamped to a
  max of 10°C, is scaled between **"roof setpoint minimum"** and **"roof setpoint maximum"** to
  produce the working roof setpoint. The manual includes an illustrative chart: roof max-setpoint
  ramps from ~700°C at zero bath error up to ~1100°C at 10°C+ bath error. **This is a real,
  documented, nonlinear cascade — the current `optimizer.py` `simulate_trajectory()` instead uses
  two flat setpoints (`sp_roof_melt`, `sp_roof_hold`) with a hard time-based switch
  (`t_switch_hrs`). Replacing/complementing that with the manual's error-driven cascade would make
  the simulator closer to how the real PLC actually behaves in Hold mode.**
- Roof loop responds with a physical setpoint bound: **Maximum roof setpoint maximum / minimum**
  and **minimum roof setpoint** are all separately HMI-configurable clamps.
- **Two-burner-pair enable/disable thresholds**: HMI-settable "enable two burner" and "disable two
  burner" output-level setpoints, each gated by a timer, so the controller only adds/drops the
  second pair after sustained high/low roof-loop output — not on every "noise" fluctuation. This
  is the real mechanism behind the "Dual Pair" vs "Single Pair" switching that
  `optimizer.py`/`physics_model.py` currently model as a single fixed time threshold
  (`t_switch_hrs`) rather than an output-driven hysteresis.

### 5.1 Furnace-wide operating modes (C103 mode control)

| Mode | Trigger | Behavior |
|---|---|---|
| **Melt** | Operator, after charging | Roof temp control to a high fixed setpoint (max designed roof temp); bath TC stays retracted. Auto-reverts to Idle if furnace left unattended (no door/mode activity) for **1 hour**. |
| **Roof Automatic** | Operator, with charge weight/type entered | Same high-roof melt control, but duration is computed from charge weight; auto-switches to Bath Hold once elapsed. |
| **Hold (Bath Hold)** | Operator, after charge reaches flat-bath / liquid-pot-line-metal charged | Bath TC auto-inserted; PID controls bath temp via the roof cascade above. Auto-reverts to Idle at end of cast / empty furnace. |
| **Idle** | Operator, or auto after 1 h unattended Melt, or auto at end of cast | Roof controlled to (bath setpoint + small offset compensating furnace losses); bath TC retracted; keeps refractory / metal stable without overheating. |
| **Heat (Cold Restart)** | Auto if roof temp drops below a settable threshold (0–500°C, HMI) | Roof setpoint ramps up at a settable rate (0–500°C/hr) from current roof temp to a settable end point (600–1000°C), then auto-reverts to Roof Idle. |

`optimizer.py`'s two-phase `Melt → Hold` trajectory with a single `t_switch_hrs` is a simplified
analogue of Roof Automatic → Bath Hold; Idle/Cold-Restart/manual-Melt aren't modeled, which is fine
for optimizing a single "charge to tap" cycle but should be kept in mind if the tool is ever asked
to simulate multi-hour idle gaps between heats (the historical sensor CSV will contain those gaps).

## 6. Instrumentation (tag ↔ code cross-reference)

| Manual tag | Description | CSV column (`mfa_..._pv`) |
|---|---|---|
| TT 200 | Bath (metal) temperature thermocouple, type K | `tt200_pv` |
| TT 201 A/B, B/B | Roof thermocouples (2×, hottest used) | `tt201_pv` |
| TT 202 A–E | Hearth/sub-hearth thermocouples (5 provision) | not present in this CSV |
| AT 104 | Furnace exhaust O₂ transmitter | `ot104_pv` |
| PT 209 | Furnace pressure transmitter | `pt209_pv` |
| ZV 209 | Furnace pressure damper position | `zv209_pv` |
| FT (air/gas flow, per burner/pair) | Combustion air & gas mass flow (orifice + DP) | `ft210_pv`, `ft211_pv`, `ft213_pv`, `ft214_pv`, `ft215_pv`, `ft217_pv` |
| FV (flow control valves) | Motorised air/gas ratio control valves per burner | `fv210_pv`…`fv217_pv` (8 valves ≈ air+gas × 4 burners) |
| — | Burner/regenerator-associated temps (likely BCU or pilot-related, not explicitly itemized in manual text extracted) | `tt111_pv`…`tt114_pv` |

- **Bath TC**: type K, abrasion-resistant cast-iron sheath w/ ceramic coating, ~1,000 mm sheath,
  inserted/retracted pneumatically (trolley). Retracted except during Bath Hold mode.
- **Roof TCs**: type R (duplex), high-temp sheath, ~500 mm sheath. One of the two roof TCs also
  feeds a **hardwired over-temperature cutoff (TCH 201)** independent of the PLC, which trips
  purge + disables all burners via the BCU safety input.
- **Hearth TCs**: type R (duplex), ~200 mm sheath, monitor for refractory failure (rising
  under-hearth temperature = alarm).
- **Data loader alignment**: `data_loader.py` reads `mfa_ft211_pv` and integrates it as an
  Nm³/hr gas-flow signal (`gas_integrated_nm3 = Σ(ft211_pv) × 5s/3600`). Given the tag table
  above, worth double-checking whether `ft211` is actually the *gas* flow transmitter and not an
  air-flow transmitter — the manual's loop numbering pattern (`210F/214F/218F` = air,
  `211F/215F/219F` = gas) suggests `ft211` is plausible as a gas-flow tag for one burner/pair, but
  it's not confirmed 1:1 against this specific furnace's I/O list in the extracted text.

## 7. Control system platform

- PLC: Mitsubishi Q Process (ladder + function blocks), CC-Link IE Fibre (PLC↔PLC), CC-Link
  (PLC↔field IO), Ethernet to a Level-2 data server / SCADA.
- HMI: Mitsubishi GOT touchscreen, plus hardwired local pushbutton stations for door/tapping/mode
  select so operators don't need the HMI for routine actions.
- **AutoMelt**: Mechatherm's proprietary predictive control layer — predicts metal melt time (for
  timing skim/stir events) and metal slump time (for recharge timing) using tuned mathematical
  models per-furnace, explicitly marketed as delivering **real fuel savings by using only the fuel
  required for the load**. This is effectively the same problem `melter2`'s heating-curve
  optimizer is trying to solve/improve on — useful framing for scoping what "better than baseline"
  should mean (baseline in the codebase's `run_baseline_scenario()` is a simple fixed-roof-SP /
  fixed-excess-air policy, which is a reasonable proxy for pre-AutoMelt or non-AutoMelt operation).
- Burner safety is **not** PLC-resident: dedicated Kromschröder BCU480 burner control units handle
  ignition sequencing, UV flame scanning (main flame) + ionization (pilot), and lockout — PLC only
  requests states (pilot/main/reset) over Profibus and reads BCU status codes (00 off … 08 main
  running … 10 fault).

## 8. Alloys and metallurgy

### 8.1 Production alloy mix seen in `115年 MFX生產紀錄.xlsx` (MFA sheet, 380 valid heats)

| Alloy | Heat count |
|---|---|
| 5083A | 73 |
| 5052 | 64 |
| 6061 | 63 |
| 5083L | 31 |
| 5052KS | 22 |
| 5083S | 15 |
| 5182E | 17 |
| 6061H | 12 |
| 6M02 | 10 |
| 5042 | 10 |
| 6M01L | 9 |
| 5754R3 | 6 |
| 5182H | 6 |
| 5151 | 5 |

**Gap**: `physics_model.py`'s `ALLOY_PROPERTIES` dict does **not** include `5083` (or any 5083
variant), which is the single most common alloy actually run (73+31+15 = 119 of 380 heats, ~31%).
It currently falls through to `'DEFAULT'` via the substring-match `get_alloy_props()`. 5083 is a
Mg-heavy (~4–4.9% Mg) alloy — its solidus/liquidus (~570°C/638°C) and dross multiplier should be
closer to 5182 than to the generic default, and this should be added before the optimizer is
trusted for 5083 heats, which are the plurality of production.

Design manual's stated overall alloy mix (differs somewhat from the MFA-only sample above, likely
reflecting all three furnaces or a different period):
- 1xxx series: 30%
- 3xxx series: 10%
- 5xxx series: 55%
- Others: 5%

### 8.2 Overall production statistics (MFA sheet, raw — includes some clearly bad/outlier rows)

- Median charge weight: **~65.5 t** (25th–75th pct ≈ 55.8–70.9 t) — consistent with the furnace's
  80 t nameplate capacity and the codebase's default `charged_weight_kg = 65000`.
- Median melt duration: **~5.9 hr** (25th–75th pct ≈ 5.1–6.6 hr) — consistent with the codebase's
  default `target_duration_hrs = 6.0` and Streamlit slider range (3–10 hr).
- Median melt rate: **~10.4 t/hr** (some rows show clearly erroneous extreme outliers, e.g.
  54.7 t/hr max and a 2,178-hour "duration" — these need filtering before using the sheet for
  model calibration; `evaluator.py`'s `duration_hrs <= 1.0` filter catches only the low end, not
  these high-end/garbage rows).
- Median gas usage per heat: **~4,225 Nm³** (mean is skewed enormously by outlier rows into the
  hundreds of thousands — again, needs outlier filtering before backtesting).

### 8.3 Scrap/charge classification (from the paper 熔化爐加料紀錄 / 熔化爐操作紀錄 forms)

Charge composition is tracked and targeted against per-alloy standard ratios across five
categories:
- **水力鋁 (Hydro/primary aluminum)** — virgin metal.
- **PCR — 消費回收鋁 (Post-Consumer Recycled)**.
- **PIR — 總回收鋁 (Post-Industrial Recycled / total recycled)**.
- **SPR — 自產回收鋁 (Self-Produced Recycled)** — in-house recycled dross/scrap.
- **OSR — 外購回收鋁 (Outside-Sourced Recycled)** — purchased scrap.

Each heat logs 標準 (standard/target %) vs 加料 (actual charged %) per category, plus a
free-text explanation field when the actual ratio misses target. This — not just gross charge
weight — is a second lever on dross/burn-off behavior: dirtier/more-oxidized scrap (higher SPR/OSR
fraction, especially reprocessed dross-derived material) melts with more oxidation loss and is
exactly the condition the manual calls "dirty scrap mode," which forces higher excess air
automatically. **The current physics model has no scrap-cleanliness input at all** — dross burn-off
is driven only by alloy, roof/bath temp, excess air, and flat-bath state. If better-than-baseline
optimization needs to account for known-dirty charges, scrap mix (available in these charge-record
files) is the natural additional input.

Standard heat-tracing metrics recorded per heat include: 標準耗時 (standard/target duration),
實際耗時 (actual duration), 延誤 (delay, minutes), 燃料指數差 (fuel index delta) — i.e. this
plant already tracks planned-vs-actual duration and a fuel index per heat, which is a ready-made
"baseline" series for backtesting beyond what's in the Excel sheet's `MF本爐燃耗` column.

### 8.4 Holding furnace (downstream of MFA/B/C, not directly this optimizer's scope but relevant context)

The 靜置爐 (holding furnace, HF) record shows master-alloy additions after tap-over — e.g. **MG9**
(Mg master alloy), **TI75** (Ti/AlTi5B1-type grain refiner), **T3B1** (Al-Ti-B grain refiner rod
equivalent) — plus degassing (除氣), rotary flux injection (RFI), and skimming (耙渣) steps, each
individually timestamped. These are HF-side metallurgical adjustments happening after the melter's
job is done; they don't affect the melter heating curve but explain why `data_loader.py` treats
`t_end` (移湯結束時間, end of metal transfer) as the natural close of a "heat" window for sensor
aggregation — everything after that point is HF/casting-side work.

## 9. What the existing codebase already encodes correctly vs. approximates

**Grounded in the manual (verified above):**
- 4-burner, 2-pair regenerative topology and its "dual pair vs single pair" duty modeling.
- Stoichiometric air/gas ratio (9.52) is a plausible value for this NG spec.
- Excess-air search range (10–15%, up to a 25–30% baseline) sits inside the manual's 0–30% HMI
  range and near its 15%-at-high-fire design maximum.
- Roof setpoint ceiling default of 1200°C matches the manual's own example figure.
- Flue-O₂ output (~2.5% at 15% excess air) lands inside the manual's practical 1–3% O₂ band.

**Approximated / not directly from the manual (worth flagging to whoever extends the physics model):**
- `GAS_LHV = 36000 kJ/Nm3` vs. manual's stated gross heating value of 9,700 kcal/Nm³
  (≈40,600 kJ/Nm³) — an ~11% gap that directly scales every gas-consumption and cost number.
- `HEARTH_AREA_M2 = 45.0` vs. manual's stated bath area of 66.15 m².
- The Melt→Hold switch is a single time threshold (`t_switch_hrs`); the real PLC switches the
  second burner pair on an **output-level hysteresis with timers**, and switches Bath-Hold roof
  setpoint via a **bath-error cascade curve**, not a fixed post-switch setpoint.
- `wall_loss_kw`, `emissivity_eff`, `burnoff_k0`, `burnoff_ea` are calibrated/assumed constants
  (docstring says "calibrated to ~1.0% industrial yield loss") — not sourced from the manual, and
  not yet validated against the actual dross-weight or fuel-index fields available in the
  production/paper records.
- No alloy entry for 5083 (the most-produced alloy in the sample data) — currently silently falls
  back to `'DEFAULT'` alloy properties.
- No scrap-cleanliness/composition input, despite that data being available per-heat in the
  加料紀錄 forms.

## 10. Open items for heating-curve optimizer development

1. Reconcile `GAS_LHV` and `HEARTH_AREA_M2` against the manual's numbers (or document why the
   code intentionally uses different effective values).
2. Add 5083 (and ideally 5083A/L/S variants seen in the data) to `ALLOY_PROPERTIES`.
3. Replace/augment the fixed `sp_roof_melt`/`t_switch_hrs`/`sp_roof_hold` trajectory with the
   manual's actual cascade behavior (bath-error-driven roof setpoint in Hold mode; output-level
   hysteresis with timers for 2-pair↔1-pair switching) so simulated trajectories better resemble
   what the PLC would actually produce, which matters for backtesting credibility.
4. Filter obvious bad rows (near-zero or absurdly large duration/weight/gas values) out of the
   Excel production log before using it for calibration or backtesting — `evaluator.py` currently
   only filters `duration_hrs <= 1.0`.
5. Consider using the plant's own recorded 標準耗時/實際耗時/延誤/燃料指數差 fields as an
   independent, already-plant-validated "baseline" to sanity-check the optimizer's own baseline
   scenario, rather than relying solely on the code's synthetic `run_baseline_scenario()`.
6. Decide whether scrap-mix / cleanliness (PCR/PIR/SPR/OSR ratios in the 加料紀錄 data) should
   become a model input for dross burn-off, since the manual explicitly ties excess-air strategy
   to "dirty scrap" conditions.
7. Sensor CSV only covers MFA for one week (2026-07-07–14); MFB/MFC/MFQ/MF7 have production-log
   history but no corresponding sensor CSVs in this folder — optimizer validation is currently
   MFA-only by data availability, not by furnace design (the three main furnaces are structurally
   identical per the manual).
