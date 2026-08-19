# -*- coding: utf-8 -*-
"""
80T Aluminum Melter Heating Curve Optimizer - Mobile Dedicated Web App (手機專用版)
Specially optimized for smartphone vertical screens, touch controls, and fast field operation.
100% mathematically aligned with desktop app.py.
"""

import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.physics_model import MelterPhysicsModel
from src.optimizer import HeatingCurveOptimizer
from src.config_manager import load_app_config

def parse_hhmm_to_hours(time_str: str, default: float = 0.0) -> float:
    if not time_str or not isinstance(time_str, str):
        return default
    try:
        parts = time_str.strip().split(':')
        if len(parts) == 2:
            return int(parts[0]) + int(parts[1]) / 60.0
        return float(time_str)
    except (ValueError, TypeError):
        return default

def format_hours_to_hhmm(hours: float) -> str:
    if hours is None or np.isnan(hours):
        return "--:--"
    total_mins = int(round(hours * 60))
    h = total_mins // 60
    m = total_mins % 60
    return f"{h:02d}:{m:02d}"

def get_local_ip() -> str:
    try:
        import socket
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(('8.8.8.8', 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return '127.0.0.1'

# Page Configuration - Centered & Mobile First
st.set_page_config(
    page_title="80T 熔鋁爐升溫最佳化 (手機版)",
    page_icon="📱",
    layout="centered",
    initial_sidebar_state="collapsed"
)

# Mobile Optimized CSS
st.markdown("""
    <style>
    .stApp {
        background-color: #F8F9FA;
    }
    .block-container {
        padding-top: 1.0rem !important;
        padding-left: 0.6rem !important;
        padding-right: 0.6rem !important;
        padding-bottom: 2.5rem !important;
    }
    .mobile-header {
        background: linear-gradient(135deg, #1E88E5 0%, #1565C0 100%);
        color: white;
        padding: 12px 14px;
        border-radius: 10px;
        margin-bottom: 12px;
        box-shadow: 0 2px 6px rgba(0,0,0,0.12);
    }
    .mobile-header h2 {
        color: white !important;
        font-size: 1.22rem !important;
        margin: 0 !important;
        font-weight: 700 !important;
    }
    .mobile-header p {
        color: #E3F2FD !important;
        font-size: 0.80rem !important;
        margin: 2px 0 0 0 !important;
    }
    .recipe-card {
        background: #FFFFFF;
        border-radius: 8px;
        padding: 10px 12px;
        margin-bottom: 8px;
        border-left: 4px solid #1E88E5;
        box-shadow: 0 1px 3px rgba(0,0,0,0.06);
    }
    .recipe-step-title {
        font-weight: 700;
        font-size: 0.90rem;
        color: #0D47A1;
        display: flex;
        justify-content: space-between;
    }
    .recipe-step-body {
        font-size: 0.82rem;
        color: #37474F;
        margin-top: 4px;
        line-height: 1.4;
    }
    div[data-testid="stMetric"] {
        background-color: #FFFFFF !important;
        border-radius: 8px !important;
        padding: 8px 10px !important;
        box-shadow: 0 1px 3px rgba(0,0,0,0.06) !important;
        border-left: 3px solid #1E88E5 !important;
        margin-bottom: 6px !important;
    }
    div[data-testid="stMetricLabel"] p {
        font-size: 0.74rem !important;
        line-height: 1.2 !important;
        color: #546E7A !important;
    }
    div[data-testid="stMetricValue"] div {
        font-size: 1.12rem !important;
        font-weight: 700 !important;
    }
    .stButton button {
        min-height: 46px !important;
        font-size: 1.0rem !important;
        font-weight: 700 !important;
        border-radius: 8px !important;
    }

    /* Plotly Sankey node text & chart titles: crisp solid black text without stroke or shadow */
    .js-plotly-plot .sankey-node text,
    .sankey-node text,
    text.node-label,
    .gtitle,
    .js-plotly-plot text {
        fill: #111827 !important;
        stroke: none !important;
        -webkit-text-stroke: 0px !important;
        text-shadow: none !important;
        filter: none !important;
        font-weight: 700 !important;
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif !important;
    }
    </style>
""", unsafe_allow_html=True)

def build_sankey_figure(sankey_data: dict, title: str = "熔煉爐全爐熱平衡能流圖 (Sankey Diagram)"):
    q_fuel = max(0.01, sankey_data['q_fuel_gj'])
    q_ox = max(0.01, sankey_data['q_ox_gj'])
    q_air_preheat = max(0.01, sankey_data['q_air_preheat_gj'])
    q_al = max(0.01, sankey_data['q_al_absorbed_gj'])
    q_dross_sens = max(0.01, sankey_data['q_dross_sensible_gj'])
    q_wall = max(0.01, sankey_data['q_wall_hearth_gj'])
    q_roof_leak = max(0.01, sankey_data['q_roof_exhaust_gj'])
    q_bed_flue = max(0.01, sankey_data['q_bed_flue_in_gj'])
    q_stack = max(0.01, sankey_data['q_stack_loss_gj'])
    
    q_total = max(0.01, q_fuel + q_ox + q_air_preheat)
    
    labels = [
        f"1. 燃料燃燒熱: {q_fuel:.1f} GJ ({q_fuel/q_total*100:.1f}%)",
        f"2. 鋁/鎂氧化熱: {q_ox:.1f} GJ ({q_ox/q_total*100:.1f}%)",
        f"3. 預熱助燃空氣: {q_air_preheat:.1f} GJ ({q_air_preheat/q_total*100:.1f}%)",
        f"4. 爐膛熱交換中心: {q_total:.1f} GJ (100%)",
        f"5. 鋁液有效吸熱: {q_al:.1f} GJ ({q_al/q_total*100:.1f}%)",
        f"6. 鋁渣升溫顯熱: {q_dross_sens:.1f} GJ ({q_dross_sens/q_total*100:.1f}%)",
        f"7. 爐壁爐底散熱: {q_wall:.1f} GJ ({q_wall/q_total*100:.1f}%)",
        f"8. 爐頂逸散煙氣: {q_roof_leak:.1f} GJ ({q_roof_leak/q_total*100:.1f}%)",
        f"9. 進入蓄熱床煙氣: {q_bed_flue:.1f} GJ ({q_bed_flue/q_total*100:.1f}%)",
        f"10. 煙囪排煙損失: {q_stack:.1f} GJ ({q_stack/q_total*100:.1f}%)",
    ]
    
    node_colors = [
        "#1E88E5", "#FB8C00", "#00ACC1", "#5E35B1", "#43A047",
        "#FFA726", "#8D6E63", "#E53935", "#F57C00", "#78909C"
    ]
    
    sources = [0, 1, 2, 3, 3, 3, 3, 3, 8]
    targets = [3, 3, 3, 4, 5, 6, 7, 8, 9]
    values = [q_fuel, q_ox, q_air_preheat, q_al, q_dross_sens, q_wall, q_roof_leak, q_bed_flue, q_stack]
    
    fig = go.Figure(data=[go.Sankey(
        node=dict(pad=15, thickness=16, line=dict(color="black", width=0.5), label=labels, color=node_colors),
        link=dict(source=sources, target=targets, value=values, color="rgba(180, 180, 180, 0.4)")
    )])
    fig.update_layout(
        title=dict(text=f"<b>{title}</b>", font=dict(size=12, color="#111827", family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif")),
        font=dict(size=11, color="#111827", family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif"),
        height=420,
        margin=dict(l=10, r=10, t=35, b=20)
    )
    return fig

def main():
    # Load configuration
    cfg = load_app_config()
    proc_cfg = cfg.get('process', {})
    phys_cfg = cfg.get('physics', {})
    
    model = MelterPhysicsModel(
        gas_price=float(proc_cfg.get('gas_price', 15.0)),
        aluminum_price=float(proc_cfg.get('aluminum_price', 75.0)),
        wall_loss_kw=float(phys_cfg.get('wall_loss_kw', 250.0)),
        hearth_loss_ref_kw=float(phys_cfg.get('hearth_loss_ref_kw', 85.0)),
        dross_factor_flat=float(phys_cfg.get('dross_factor_flat', 0.70)),
        emissivity_eff=float(phys_cfg.get('emissivity_eff', 0.85)),
        gas_lhv_kj_nm3=float(phys_cfg.get('gas_lhv_kj_nm3', 37256.0)),
        burnoff_ea=float(phys_cfg.get('burnoff_ea', 45000.0)),
        burnoff_k0=float(phys_cfg.get('burnoff_k0', 0.8583)),
    )
    
    optimizer = HeatingCurveOptimizer(
        physics_model=model,
        max_gas_flow_dual_pair=float(phys_cfg.get('max_gas_flow_dual_pair', 880.0)),
        max_gas_flow_single_pair=float(phys_cfg.get('max_gas_flow_single_pair', 440.0)),
        min_gas_flow_nm3h=float(phys_cfg.get('min_gas_flow_nm3h', 50.0)),
    )
    optimizer.max_gas_flow_dual_pair = float(phys_cfg.get('max_gas_flow_dual_pair', 880.0))
    optimizer.max_gas_flow_single_pair = float(phys_cfg.get('max_gas_flow_single_pair', 440.0))
    optimizer.min_gas_flow_nm3h = float(phys_cfg.get('min_gas_flow_nm3h', 50.0))

    # Mobile Header
    st.markdown("""
        <div class="mobile-header">
            <h2>🔥 80T 熔鋁爐升溫最佳化</h2>
            <p>📱 手機即時操作配方與節能試算 (Mobile Web App)</p>
        </div>
    """, unsafe_allow_html=True)

    # 1. Quick Conditions Input Form
    alloy_list = sorted(list(model.ALLOY_PROPERTIES.keys()))
    default_alloy = proc_cfg.get('alloy_name', '5052')
    alloy_idx = alloy_list.index(default_alloy) if default_alloy in alloy_list else 0

    with st.expander("⚙️ 點此設定【爐次工藝條件】", expanded=True):
        col_m1, col_m2 = st.columns(2)
        with col_m1:
            selected_alloy = st.selectbox("1. 產出鋁種", alloy_list, index=alloy_idx)
            charged_tonnes = st.number_input("2. 投料量 (t)", min_value=10.0, max_value=85.0, value=float(proc_cfg.get('charged_weight_tonnes', 55.0)), step=1.0)
        with col_m2:
            target_hrs = st.number_input("3. 時限 (h)", min_value=3.0, max_value=10.0, value=float(proc_cfg.get('target_duration_hrs', 5.0)), step=0.5)
            residual_tonnes = st.number_input("4. 殘湯量 (t)", min_value=0.0, max_value=15.0, value=float(proc_cfg.get('residual_weight_tonnes', 5.0)), step=0.5)

        with st.expander("🛠️ 現行升溫方案與進階設定", expanded=False):
            base_sp1 = st.number_input("現行第1段頂溫 (°C)", min_value=900.0, max_value=1250.0, value=float(proc_cfg.get('baseline_sp1', 1180.0)), step=10.0)
            base_dur1_str = st.text_input("現行第1段時長 (hh:mm)", value=str(proc_cfg.get('baseline_dur1_hhmm', '04:30')))
            base_sp2 = st.number_input("現行第2段頂溫 (°C)", min_value=800.0, max_value=1150.0, value=float(proc_cfg.get('baseline_sp2', 950.0)), step=10.0)
            base_dur2_str = st.text_input("現行第2段時長 (hh:mm)", value=str(proc_cfg.get('baseline_dur2_hhmm', '00:00')))
            base_sp3 = st.number_input("現行第3段保溫設點 (°C)", min_value=700.0, max_value=900.0, value=float(proc_cfg.get('baseline_sp3', 780.0)), step=10.0)
            
            excess_air_pct = st.slider("現行過剩空氣率 (%)", min_value=5.0, max_value=60.0, value=float(proc_cfg.get('excess_air_pct', 40.0)), step=1.0)
            target_bath_temp = st.number_input("目標出湯湯溫 (°C)", min_value=700.0, max_value=800.0, value=float(proc_cfg.get('target_bath_temp_c', 780.0)), step=10.0)
            max_roof_sp_limit = st.slider("頂溫上限安全天花板 (°C)", min_value=1100.0, max_value=1250.0, value=float(proc_cfg.get('max_roof_sp_limit', 1200.0)), step=10.0)

    dur1_hrs = parse_hhmm_to_hours(base_dur1_str, default=target_hrs)
    dur2_hrs = parse_hhmm_to_hours(base_dur2_str, default=0.0)
    charged_weight_kg = charged_tonnes * 1000.0
    residual_weight_kg = residual_tonnes * 1000.0

    btn_calc = st.button("🚀 執行最佳化模擬計算", type="primary", use_container_width=True)

    current_inputs = {
        'charged_weight_kg': charged_weight_kg,
        'residual_weight_kg': residual_weight_kg,
        'discharge_deadline_hrs': target_hrs,
        'alloy_name': selected_alloy,
        'baseline_roof_sp': base_sp1,
        'baseline_dur_melt_hrs': dur1_hrs,
        'baseline_sp_soak': base_sp2,
        'baseline_dur_soak_hrs': dur2_hrs,
        'baseline_sp_hold': base_sp3,
        'baseline_excess_air_pct': excess_air_pct,
        'target_bath_temp_c': target_bath_temp,
        'max_roof_sp_limit': max_roof_sp_limit,
    }

    if btn_calc or ('m_opt_res' not in st.session_state):
        with st.spinner("正在搜尋最佳 3 段階梯配方與最低燒損解..."):
            res = optimizer.optimize_heating_curve(**current_inputs)
            st.session_state['m_opt_res'] = res

    res = st.session_state.get('m_opt_res')
    if res is None:
        st.info("請點擊上方按鈕執行運算。")
        return

    opt_params = res['optimal_params']
    recipe_steps = res.get('recipe_steps', [])
    savings = res['savings']
    base_sum = res['baseline_summary']
    opt_sum = res['optimal_summary']
    df_opt = res.get('optimal_trajectory', res.get('optimal_df'))
    df_base = res.get('baseline_trajectory', res.get('baseline_df'))
    props = model.ALLOY_PROPERTIES[selected_alloy]

    # Metrics prep
    total_metal_tonnes = (charged_weight_kg + residual_weight_kg) / 1000.0
    charged_metal_tonnes = charged_weight_kg / 1000.0
    base_gas_per_t = base_sum['cum_gas_nm3'] / total_metal_tonnes if total_metal_tonnes > 0 else 0.0
    opt_gas_per_t = opt_sum['cum_gas_nm3'] / total_metal_tonnes if total_metal_tonnes > 0 else 0.0
    
    base_dross_pct = (base_sum['cum_dross_kg'] / charged_weight_kg) * 100.0 if charged_weight_kg > 0 else 0.0
    opt_dross_pct = (opt_sum['cum_dross_kg'] / charged_weight_kg) * 100.0 if charged_weight_kg > 0 else 0.0

    gas_pct = ((base_sum['cum_gas_nm3'] - opt_sum['cum_gas_nm3']) / base_sum['cum_gas_nm3']) * 100.0 if base_sum['cum_gas_nm3'] > 0 else 0.0
    dross_pct = ((base_sum['cum_dross_kg'] - opt_sum['cum_dross_kg']) / base_sum['cum_dross_kg']) * 100.0 if base_sum['cum_dross_kg'] > 0 else 0.0

    base_liq_rows = df_base[df_base['bath_temp_c'] >= props['liquidus']]
    base_melt_hrs = float(base_liq_rows.iloc[0]['time_hrs']) if not base_liq_rows.empty else float(target_hrs)
    
    opt_liq_rows = df_opt[df_opt['bath_temp_c'] >= props['liquidus']]
    opt_melt_hrs = float(opt_liq_rows.iloc[0]['time_hrs']) if not opt_liq_rows.empty else float(target_hrs)

    base_melt_rate_t_h = charged_metal_tonnes / base_melt_hrs if base_melt_hrs > 0 else 0.0
    opt_melt_rate_t_h = charged_metal_tonnes / opt_melt_hrs if opt_melt_hrs > 0 else 0.0
    melt_rate_delta_t_h = opt_melt_rate_t_h - base_melt_rate_t_h
    melt_rate_delta_pct = (melt_rate_delta_t_h / base_melt_rate_t_h * 100.0) if base_melt_rate_t_h > 0 else 0.0

    if hasattr(model, 'calculate_flue_oxygen_pct'):
        est_o2 = model.calculate_flue_oxygen_pct(excess_air_pct)
    else:
        x_f = excess_air_pct / 100.0
        est_o2 = (21.0 * x_f) / (1.0 + x_f * 1.05)

    # --- 1. DCS 3-Step Recipe for Mobile Operators ---
    st.markdown("### 📝 DCS 3 段階梯操作配方")
    if recipe_steps and len(recipe_steps) == 3:
        s1, s2, s3 = recipe_steps[0], recipe_steps[1], recipe_steps[2]
        st.markdown(f"""
            <div class="recipe-card" style="border-left-color: #E53935;">
                <div class="recipe-step-title">
                    <span>🔥 第 1 段：主熔化段 ({s1['interval_hhmm']})</span>
                    <span style="color:#C62828;"><b>{s1['sp_roof_c']:.0f} °C</b></span>
                </div>
                <div class="recipe-step-body">
                    - 持續時間：<b>{s1['duration_hhmm']}</b> | 燒嘴：{s1['burner_mode']}<br>
                    - 工藝目標：{s1['goal']}
                </div>
            </div>
            <div class="recipe-card" style="border-left-color: #FB8C00;">
                <div class="recipe-step-title">
                    <span>⚡ 第 2 段：平湯降火段 ({s2['interval_hhmm']})</span>
                    <span style="color:#EF6C00;"><b>{s2['sp_roof_c']:.0f} °C</b></span>
                </div>
                <div class="recipe-step-body">
                    - 持續時間：<b>{s2['duration_hhmm']}</b> | 燒嘴：{s2['burner_mode']}<br>
                    - 工藝目標：{s2['goal']} (及時降溫抑止白渣)
                </div>
            </div>
            <div class="recipe-card" style="border-left-color: #43A047;">
                <div class="recipe-step-title">
                    <span>🛡️ 第 3 段：出湯保溫段 ({s3['interval_hhmm']})</span>
                    <span style="color:#2E7D32;"><b>{s3['sp_roof_c']:.0f} °C</b></span>
                </div>
                <div class="recipe-step-body">
                    - 持續時間：<b>{s3['duration_hhmm']}</b> | 燒嘴：{s3['burner_mode']}<br>
                    - 工藝目標：{s3['goal']}
                </div>
            </div>
        """, unsafe_allow_html=True)

    # --- 2. Comprehensive KPI Cards: Row 1 Baseline vs Row 2 Optimal ---
    st.markdown("### 📌 熔煉能耗、成本與燒損綜合對照")
    
    # Row 1: 現行升溫方案基準
    st.markdown("##### 🏛️ 現行升溫方案基準 (Current Practice)")
    b1, b2 = st.columns(2)
    with b1:
        st.metric("每爐總生產成本 (TWD)", f"${base_sum['total_cost']:,.0f}")
        st.metric("天然氣總耗量 (Nm³)", f"{base_sum['cum_gas_nm3']:,.1f}", help=f"單耗: {base_gas_per_t:.1f} Nm³/t")
        st.metric("溫控設點模式 (°C)", f"{base_sp1:.0f} °C 全火" if dur1_hrs >= target_hrs else f"{base_sp1:.0f} → {base_sp3:.0f} °C")
    with b2:
        st.metric("氧化燒損渣量 (kg)", f"{base_sum['cum_dross_kg']:,.1f}", help=f"燒損率: {base_dross_pct:.2f}%")
        st.metric("溶解速率 (t/h)", f"{base_melt_rate_t_h:.2f}", help=f"全融時長: {format_hours_to_hhmm(base_melt_hrs)}")
        st.metric("現行過剩空氣率 (%)", f"{excess_air_pct:.1f}%", help=f"煙道殘氧: {est_o2:.2f}% O₂")

    # Row 2: 最佳化階梯升溫模式
    st.markdown("##### 🚀 最佳化階梯模式與降減效益")
    o1, o2 = st.columns(2)
    with o1:
        st.metric(
            "每爐總生產成本 (TWD)",
            f"${opt_sum['total_cost']:,.0f}",
            delta=f"-${savings['cost_savings_twd']:,.0f} (-{savings['cost_savings_pct']:.1f}%)"
        )
        st.metric(
            "天然氣總耗量 (Nm³)",
            f"{opt_sum['cum_gas_nm3']:,.1f}",
            delta=f"-{savings['gas_savings_nm3']:,.1f} Nm³ (-{gas_pct:.1f}%)"
        )
        st.metric(
            "最佳 3 段階梯溫控 (°C)",
            f"{opt_params['sp_roof_melt']:.0f}→{opt_params['sp_roof_soak']:.0f}→{opt_params['sp_roof_hold']:.0f}",
            delta="3 段階梯控溫",
            delta_color="off"
        )
    with o2:
        st.metric(
            "氧化燒損渣量 (kg)",
            f"{opt_sum['cum_dross_kg']:,.1f}",
            delta=f"-{savings['dross_savings_kg']:,.1f} kg (-{dross_pct:.1f}%)"
        )
        st.metric(
            "溶解速率 (t/h)",
            f"{opt_melt_rate_t_h:.2f}",
            delta=f"+{melt_rate_delta_t_h:.2f} t/h (+{melt_rate_delta_pct:.1f}%)"
        )
        st.metric(
            "最佳過剩空氣率 (%)",
            f"{opt_params['excess_air_pct']:.1f}%",
            delta=f"-{excess_air_pct - opt_params['excess_air_pct']:.1f}% (殘氧 {opt_params['flue_o2_pct']:.2f}%)"
        )

    # --- 3. Detailed Comparison Table (Collapsible) ---
    base_timing_str = f"00:00~{format_hours_to_hhmm(target_hrs)} (1180°C 全火到底)" if dur1_hrs >= target_hrs else f"00:00~{format_hours_to_hhmm(dur1_hrs)} (融化) → 轉湯溫保溫"
    base_sp_str = f"{base_sp1:.0f}°C 全火持續到底" if dur1_hrs >= target_hrs else f"{base_sp1:.0f}°C (融化) → {base_sp3:.0f}°C (保溫)"

    with st.expander("📋 點此展開「現行方案 vs. 最佳化」各項指標詳細對照表", expanded=False):
        df_compare = pd.DataFrame({
            "指標項目 (Metric)": [
                "每爐綜合生產成本 (Total Cost)",
                "  └ 天然氣費用 (Gas Cost)",
                "  └ 鋁金屬燒損損失 (Dross Metal Loss)",
                "天然氣總耗量 (Total Gas Consumption)",
                "天然氣單耗 (Specific Gas Consumption)",
                "鋁錠氧化燒損量 (Dross Generated)",
                "投料燒損率 (Dross Loss %)",
                "平均溶解速率 (Melting Rate)",
                "完全融解時長 (Time to Liquidus)",
                "三段溫控時段 (3-Step Timing Intervals)",
                "熔化/平湯/保溫 頂溫設點 (Stepwise Roof SP)",
                "過剩空氣率 / 煙道殘氧 (Excess Air / Flue O₂)",
                "出湯達成時限 (Target Deadline Met)"
            ],
            "現行升溫方案 (Baseline)": [
                f"${base_sum['total_cost']:,.0f} TWD",
                f"${base_sum['gas_cost']:,.0f} TWD",
                f"${base_sum['dross_cost']:,.0f} TWD",
                f"{base_sum['cum_gas_nm3']:,.1f} Nm³",
                f"{base_gas_per_t:.1f} Nm³/t",
                f"{base_sum['cum_dross_kg']:.1f} kg",
                f"{base_dross_pct:.2f}%",
                f"{base_melt_rate_t_h:.2f} t/h",
                f"{format_hours_to_hhmm(base_melt_hrs)} ({base_melt_hrs:.2f}h)",
                base_timing_str,
                base_sp_str,
                f"{excess_air_pct:.1f}% ({est_o2:.2f}% O₂)",
                f"達標 ({base_sum['final_bath_temp_c']:.1f}°C)"
            ],
            "最佳化階梯升溫 (Optimal)": [
                f"${opt_sum['total_cost']:,.0f} TWD",
                f"${opt_sum['gas_cost']:,.0f} TWD",
                f"${opt_sum['dross_cost']:,.0f} TWD",
                f"{opt_sum['cum_gas_nm3']:,.1f} Nm³",
                f"{opt_gas_per_t:.1f} Nm³/t",
                f"{opt_sum['cum_dross_kg']:.1f} kg",
                f"{opt_dross_pct:.2f}%",
                f"{opt_melt_rate_t_h:.2f} t/h",
                f"{format_hours_to_hhmm(opt_melt_hrs)} ({opt_melt_hrs:.2f}h)",
                f"第1段: 00:00~{format_hours_to_hhmm(opt_params['t_switch_hrs'])} | 第2段: {format_hours_to_hhmm(opt_params['t_switch_hrs'])}~{format_hours_to_hhmm(opt_params['t_soak_end_hrs'])} | 第3段: {format_hours_to_hhmm(opt_params['t_soak_end_hrs'])}~{format_hours_to_hhmm(target_hrs)}",
                f"{opt_params['sp_roof_melt']:.0f}°C (主熔) → {opt_params['sp_roof_soak']:.0f}°C (平湯) → {opt_params['sp_roof_hold']:.0f}°C (保溫)",
                f"{opt_params['excess_air_pct']:.1f}% ({opt_params['flue_o2_pct']:.2f}% O₂)",
                f"{'✅ 準時出湯' if res['deadline_met'] else '⚠️ 未達時限'} ({opt_sum['final_bath_temp_c']:.1f}°C)"
            ],
            "改善效益 (Improvement / Savings)": [
                f"節省 -${savings['cost_savings_twd']:,.0f} (-{savings['cost_savings_pct']:.1f}%)",
                f"節省 -${base_sum['gas_cost'] - opt_sum['gas_cost']:,.0f} (-{((base_sum['gas_cost'] - opt_sum['gas_cost'])/base_sum['gas_cost']*100) if base_sum['gas_cost']>0 else 0:.1f}%)",
                f"減少 -${base_sum['dross_cost'] - opt_sum['dross_cost']:,.0f} (-{((base_sum['dross_cost'] - opt_sum['dross_cost'])/base_sum['dross_cost']*100) if base_sum['dross_cost']>0 else 0:.1f}%)",
                f"節約 -{savings['gas_savings_nm3']:,.1f} Nm³ (-{gas_pct:.1f}%)",
                f"下降 -{base_gas_per_t - opt_gas_per_t:.1f} Nm³/t (-{gas_pct:.1f}%)",
                f"減少 -{savings['dross_savings_kg']:.1f} kg (-{dross_pct:.1f}%)",
                f"降低 -{base_dross_pct - opt_dross_pct:.2f} 個百分點",
                f"提速 +{melt_rate_delta_t_h:.2f} t/h (+{melt_rate_delta_pct:.1f}%)",
                f"提早 {format_hours_to_hhmm(base_melt_hrs - opt_melt_hrs)} 完成料堆全融",
                f"主熔提早至 {format_hours_to_hhmm(opt_params['t_switch_hrs'])} 轉平湯降火",
                "3 段階梯設定值，符合現場 PLC/DCS 執行需求",
                f"過剩空氣減少 {excess_air_pct - opt_params['excess_air_pct']:.1f}%",
                "符合出湯工藝時限要求"
            ]
        })
        st.dataframe(df_compare, use_container_width=True, hide_index=True)

    # --- 4. Dynamic Temperature Trajectory Chart (Touch-friendly with Open/Closed Markers) ---
    st.markdown("### 📈 1. 升溫動態軌跡")
    fig1 = go.Figure()
    
    # Baseline
    fig1.add_trace(go.Scatter(x=df_base['time_hrs'], y=df_base['sp_roof_c'], name='現行頂溫設點', legendgroup='現行方案', legendgrouptitle=dict(text='<b>🏛️ 現行升溫方案：</b>'), line=dict(color='#E53935', width=2, dash='dash')))
    fig1.add_trace(go.Scatter(x=df_base['time_hrs'], y=df_base['bath_temp_c'], name='現行鋁湯溫度 (TT200)', legendgroup='現行方案', line=dict(color='#D81B60', width=2.5)))
    
    # Markers for baseline
    start_melt_base = df_base[df_base['bath_temp_c'] >= props['solidus']]
    end_melt_base = df_base[df_base['bath_temp_c'] >= props['liquidus']]
    if not start_melt_base.empty:
        r_b_s = start_melt_base.iloc[0]
        fig1.add_trace(go.Scatter(x=[r_b_s['time_hrs']], y=[r_b_s['bath_temp_c']], mode='markers', marker=dict(symbol='triangle-up-open', size=13, color='#E53935', line=dict(width=2.5)), name='現行開始融解 (固相線 △)', legendgroup='現行方案'))
    if not end_melt_base.empty:
        r_b_e = end_melt_base.iloc[0]
        fig1.add_trace(go.Scatter(x=[r_b_e['time_hrs']], y=[r_b_e['bath_temp_c']], mode='markers', marker=dict(symbol='circle-open', size=13, color='#D81B60', line=dict(width=2.5)), name='現行結束熔解 (液相線 ○)', legendgroup='現行方案'))

    # Optimal
    opt_sp_name = f'最佳化 3 段階梯設點 ({opt_params["sp_roof_melt"]:.0f}°C → {opt_params["sp_roof_soak"]:.0f}°C → {opt_params["sp_roof_hold"]:.0f}°C)'
    fig1.add_trace(go.Scatter(x=df_opt['time_hrs'], y=df_opt['sp_roof_c'], name=opt_sp_name, legendgroup='最佳化模式', legendgrouptitle=dict(text='<br><b>🚀 最佳化階梯模式：</b>'), line=dict(color='#1E88E5', width=3)))
    fig1.add_trace(go.Scatter(x=df_opt['time_hrs'], y=df_opt['roof_temp_c'], name='最佳化頂溫 (TT201)', legendgroup='最佳化模式', line=dict(color='#64B5F6', width=2)))
    fig1.add_trace(go.Scatter(x=df_opt['time_hrs'], y=df_opt['bath_temp_c'], name='最佳化湯溫 (TT200)', legendgroup='最佳化模式', line=dict(color='#43A047', width=3)))

    # Markers for optimal
    start_melt_opt = df_opt[df_opt['bath_temp_c'] >= props['solidus']]
    end_melt_opt = df_opt[df_opt['bath_temp_c'] >= props['liquidus']]
    if not start_melt_opt.empty:
        r_o_s = start_melt_opt.iloc[0]
        fig1.add_trace(go.Scatter(x=[r_o_s['time_hrs']], y=[r_o_s['bath_temp_c']], mode='markers', marker=dict(symbol='triangle-up', size=13, color='#F57C00', line=dict(width=1.5, color='black')), name='最佳化開始融解 (固相線 ▲)', legendgroup='最佳化模式'))
    if not end_melt_opt.empty:
        r_o_e = end_melt_opt.iloc[0]
        fig1.add_trace(go.Scatter(x=[r_o_e['time_hrs']], y=[r_o_e['bath_temp_c']], mode='markers', marker=dict(symbol='circle', size=13, color='#2E7D32', line=dict(width=1.5, color='black')), name='最佳化結束熔解 (液相線 ●)', legendgroup='最佳化模式'))

    fig1.add_hline(y=props['liquidus'], line_dash="dash", line_color="gray", annotation_text=f"液相線 {props['liquidus']}°C", annotation_position="top left")
    fig1.add_hline(y=target_bath_temp, line_dash="dot", line_color="green", annotation_text=f"出湯 {target_bath_temp}°C", annotation_position="bottom left")

    fig1.update_layout(
        height=480,
        margin=dict(l=10, r=10, t=30, b=30),
        xaxis_title="熔煉時間 (小時)",
        yaxis_title="溫度 (°C)",
        legend=dict(orientation="h", traceorder="grouped", yanchor="top", y=-0.22, xanchor="center", x=0.5),
        hovermode="x unified"
    )
    st.plotly_chart(fig1, use_container_width=True, config={'responsive': True, 'displayModeBar': False})

    # --- 5. Chart 2: Gas Flow (Instant & Cumulative) ---
    st.markdown("### 📊 2. 燒嘴燃氣流量與累積氣量")
    fig2 = make_subplots(specs=[[{"secondary_y": True}]])
    fig2.add_trace(go.Scatter(x=df_base['time_hrs'], y=df_base['cum_gas_nm3'], name='現行累積瓦斯 (Nm³)', line=dict(color='#E53935', width=2, dash='dash')), secondary_y=False)
    fig2.add_trace(go.Scatter(x=df_opt['time_hrs'], y=df_opt['cum_gas_nm3'], name='最佳化累積瓦斯 (Nm³)', line=dict(color='#1E88E5', width=2)), secondary_y=False)
    fig2.add_trace(go.Scatter(x=df_base['time_hrs'], y=df_base['gas_flow_nm3h'], name='現行瞬間燃氣 (Nm³/h)', line=dict(color='#FB8C00', width=1.8, dash='dash')), secondary_y=True)
    fig2.add_trace(go.Scatter(x=df_opt['time_hrs'], y=df_opt['gas_flow_nm3h'], name='最佳化瞬間燃氣 (Nm³/h)', line=dict(color='#00ACC1', width=2)), secondary_y=True)

    fig2.update_layout(height=400, margin=dict(l=10, r=10, t=30, b=20), xaxis_title="時間 (小時)", legend=dict(orientation="h", yanchor="top", y=-0.25, xanchor="center", x=0.5))
    fig2.update_yaxes(title_text="累積氣量 (Nm³)", secondary_y=False)
    fig2.update_yaxes(title_text="瞬間流量 (Nm³/h)", secondary_y=True)
    st.plotly_chart(fig2, use_container_width=True, config={'responsive': True, 'displayModeBar': False})

    # --- 6. Chart 3: Cost Breakdown Bar Chart ---
    st.markdown("### 💰 3. 成本結構對比")
    categories = ['現行升溫方案', '最佳化 3 段階梯']
    fig3 = go.Figure(data=[
        go.Bar(name='天然氣費用 (TWD)', x=categories, y=[base_sum['gas_cost'], opt_sum['gas_cost']], marker_color='#42A5F5'),
        go.Bar(name=f'{selected_alloy} 氧化燒損費用 (TWD)', x=categories, y=[base_sum['dross_cost'], opt_sum['dross_cost']], marker_color='#EF5350')
    ])
    fig3.update_layout(barmode='stack', height=360, margin=dict(l=10, r=10, t=30, b=20), legend=dict(orientation="h", yanchor="top", y=-0.25, xanchor="center", x=0.5))
    st.plotly_chart(fig3, use_container_width=True, config={'responsive': True, 'displayModeBar': False})

    # --- 7. Chart 4: Full Furnace Sankey Energy Balance ---
    st.markdown("### 🔄 4. 全爐熱平衡能流桑基圖")
    sankey_mode = st.radio("選擇能流情境：", ["🚀 最佳化 3 段階梯模式", "🏛️ 現行升溫方案"], horizontal=True)
    s_data = res.get('sankey_optimal') if '最佳化' in sankey_mode else res.get('sankey_baseline')
    if s_data:
        sk1, sk2 = st.columns(2)
        with sk1:
            st.metric("熱能有效利用率", f"{s_data['thermal_eff_fuel_pct']:.1f} %")
            st.metric("全爐排煙熱損率", f"{s_data['total_flue_loss_pct']:.1f} %")
        with sk2:
            st.metric("蓄熱床餘熱回收率", f"{s_data['regen_recovery_pct']:.1f} %")
            st.metric("氧化放熱佔比", f"{s_data['q_ox_gj'] / (s_data['q_fuel_gj'] + s_data['q_ox_gj']) * 100:.1f} %")
        
        fig_sk = build_sankey_figure(s_data, title=f"[{selected_alloy}] {sankey_mode} 熱平衡能流 (單位: GJ)")
        st.plotly_chart(fig_sk, use_container_width=True, config={'responsive': True, 'displayModeBar': False})

    # --- 8. Mobile Share / LAN QR Code Card ---
    st.markdown("---")
    local_ip = get_local_ip()
    mobile_url = f"http://{local_ip}:8502"
    qr_img = f"https://api.qrserver.com/v1/create-qr-code/?size=180x180&data={mobile_url}"
    
    with st.expander("📱 分享給其他人手機連線", expanded=False):
        st.markdown(f"**同 Wi-Fi 手機直連網址**：\n`{mobile_url}`")
        st.markdown(f'<div style="text-align: center; margin: 8px 0;"><img src="{qr_img}" width="140" style="border-radius: 6px;" alt="QR Code"><br><small style="color: #666;">手機鏡頭掃描立即試用</small></div>', unsafe_allow_html=True)
        st.caption("💡 **加入主畫面 (PWA/Web App)**：\n1. 用 Safari (iOS) 或 Chrome (Android) 開啟。\n2. 點選【分享】或選單 → 選擇【加入主畫面】，即可全螢幕體驗！")

if __name__ == '__main__':
    main()
