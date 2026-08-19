# -*- coding: utf-8 -*-
"""
80T Aluminum Melter Heating Curve Optimizer - Mobile Dedicated Web App (手機專用版)
Specially optimized for smartphone vertical screens, touch controls, and fast field operation.
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
    </style>
""", unsafe_allow_html=True)

def main():
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
        model=model,
        max_gas_flow_dual_pair=float(phys_cfg.get('max_gas_flow_dual_pair', 880.0)),
        max_gas_flow_single_pair=float(phys_cfg.get('max_gas_flow_single_pair', 440.0)),
        min_gas_flow_nm3h=float(phys_cfg.get('min_gas_flow_nm3h', 50.0)),
    )

    st.markdown("""
        <div class="mobile-header">
            <h2>🔥 80T 熔鋁爐升溫最佳化</h2>
            <p>📱 手機即時操作配方與節能試算 (Mobile Web App)</p>
        </div>
    """, unsafe_allow_html=True)

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

        with st.expander("🛠️ 現行方案與進階設定", expanded=False):
            base_dur1_str = st.text_input("現行大火時長 (hh:mm)", value=str(proc_cfg.get('baseline_dur1_hhmm', '04:30')))
            base_excess_air = st.slider("現行過剩空氣率 (%)", min_value=5.0, max_value=60.0, value=float(proc_cfg.get('excess_air_pct', 40.0)), step=1.0)
            target_bath_temp = st.number_input("目標出湯湯溫 (°C)", min_value=700.0, max_value=800.0, value=float(proc_cfg.get('target_bath_temp_c', 780.0)), step=10.0)

    dur1_hrs = parse_hhmm_to_hours(base_dur1_str, default=target_hrs)
    charged_weight_kg = charged_tonnes * 1000.0
    residual_weight_kg = residual_tonnes * 1000.0

    btn_calc = st.button("🚀 執行最佳化模擬計算", type="primary", use_container_width=True)

    if btn_calc or ('m_opt_res' not in st.session_state):
        with st.spinner("正在搜尋最佳 3 段階梯配方與最低燒損解..."):
            res = optimizer.optimize_heating_curve(
                charged_weight_kg=charged_weight_kg,
                residual_weight_kg=residual_weight_kg,
                discharge_deadline_hrs=target_hrs,
                alloy_name=selected_alloy,
                baseline_roof_sp=float(proc_cfg.get('baseline_sp1', 1180.0)),
                baseline_dur_melt_hrs=dur1_hrs,
                baseline_excess_air_pct=base_excess_air,
                target_bath_temp_c=target_bath_temp,
                dt_mins=1.0,
            )
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

    # --- 2. Key Metrics Grid (2 columns on mobile) ---
    st.markdown("### 📊 效益與能耗對照")
    
    liquidus = props['liquidus']
    opt_melt_rows = df_opt[df_opt['bath_temp_c'] >= liquidus]
    opt_melt_h = opt_melt_rows['time_hrs'].min() if not opt_melt_rows.empty else target_hrs
    opt_melt_rate = (charged_weight_kg / 1000.0) / opt_melt_h if opt_melt_h > 0 else 0.0

    k_col1, k_col2 = st.columns(2)
    with k_col1:
        st.metric(
            label="每爐總生產成本 (TWD)",
            value=f"${opt_sum['total_cost']:,.0f}",
            delta=f"-${savings['cost_savings_twd']:,.0f} (-{savings['cost_savings_pct']:.1f}%)"
        )
        st.metric(
            label="天然氣總耗量 (Nm³)",
            value=f"{opt_sum['cum_gas_nm3']:,.1f}",
            delta=f"-{savings['gas_savings_nm3']:,.1f} Nm³"
        )
    with k_col2:
        st.metric(
            label="氧化燒損渣量 (kg)",
            value=f"{opt_sum['cum_dross_kg']:.1f}",
            delta=f"-{savings['dross_savings_kg']:.1f} kg"
        )
        st.metric(
            label="平均溶解速率 (t/h)",
            value=f"{opt_melt_rate:.2f} t/h",
            delta=f"全融時長 {format_hours_to_hhmm(opt_melt_h)}",
            delta_color="off"
        )

    # --- 3. Dynamic Temperature Trajectory Chart (Touch-friendly) ---
    st.markdown("### 📈 升溫曲線軌跡")
    fig = go.Figure()
    
    fig.add_trace(go.Scatter(x=df_opt['time_hrs'], y=df_opt['sp_roof_c'], name='最佳化設點', line=dict(color='#1E88E5', width=3)))
    fig.add_trace(go.Scatter(x=df_opt['time_hrs'], y=df_opt['roof_temp_c'], name='最佳頂溫(TT201)', line=dict(color='#64B5F6', width=1.8)))
    fig.add_trace(go.Scatter(x=df_opt['time_hrs'], y=df_opt['bath_temp_c'], name='最佳湯溫(TT200)', line=dict(color='#43A047', width=3)))
    fig.add_trace(go.Scatter(x=df_base['time_hrs'], y=df_base['bath_temp_c'], name='現行湯溫', line=dict(color='#D81B60', width=1.8, dash='dash')))
    
    fig.add_hline(y=props['liquidus'], line_dash="dash", line_color="gray", annotation_text=f"液相線 {props['liquidus']}°C", annotation_position="top left")
    fig.add_hline(y=target_bath_temp, line_dash="dot", line_color="green", annotation_text=f"出湯 {target_bath_temp}°C", annotation_position="bottom left")

    fig.update_layout(
        height=380,
        margin=dict(l=10, r=10, t=30, b=30),
        xaxis_title="時間 (小時)",
        yaxis_title="溫度 (°C)",
        legend=dict(orientation="h", yanchor="top", y=-0.25, xanchor="center", x=0.5),
        hovermode="x unified"
    )
    st.plotly_chart(fig, use_container_width=True, config={'responsive': True, 'displayModeBar': False})

    # --- 4. Mobile Share / LAN QR Code Card ---
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
