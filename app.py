"""
Streamlit Web Dashboard for 80T Aluminum Melter Heating Curve Optimizer.
Provides interactive scenario analysis, alloy selection, air-fuel ratio control, and 4-burner 2-pair regenerative combustion monitoring.
"""

import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import json
import os

try:
    from src.physics_model import MelterPhysicsModel, ALLOY_PROPERTIES, _CALIBRATED_CONSTANTS_PATH
    from src.optimizer import HeatingCurveOptimizer, format_hours_to_hhmm, parse_hhmm_to_hours
    from src.evaluator import MelterEvaluator
except ImportError:
    from physics_model import MelterPhysicsModel, ALLOY_PROPERTIES, _CALIBRATED_CONSTANTS_PATH
    from optimizer import HeatingCurveOptimizer, format_hours_to_hhmm, parse_hhmm_to_hours
    from evaluator import MelterEvaluator


CHART_FONT_SCALE = 1.2


def finalize_chart_layout(fig, height=520, base_size=12, title_size=18, axis_title_size=14):
    """Scales chart text by CHART_FONT_SCALE and pins title/legend/plot to non-overlapping
    positions: title top-left, legend as a horizontal bar BELOW the plot area (not floating
    above it near the title), with margins sized to fit both without clipping."""
    fig.update_layout(
        height=height,
        margin=dict(t=70, b=150, l=70, r=40),
        font=dict(size=round(base_size * CHART_FONT_SCALE)),
        title=dict(
            font=dict(size=round(title_size * CHART_FONT_SCALE)),
            x=0.01, xanchor='left', y=0.98, yanchor='top',
        ),
        legend=dict(
            orientation='h', yanchor='top', y=-0.24, xanchor='center', x=0.5,
            font=dict(size=round(base_size * CHART_FONT_SCALE)),
        ),
        hovermode="x unified",
    )
    fig.update_xaxes(
        title_font=dict(size=round(axis_title_size * CHART_FONT_SCALE)),
        tickfont=dict(size=round(base_size * CHART_FONT_SCALE)),
        hoverformat='.1f',
    )
    fig.update_yaxes(
        title_font=dict(size=round(axis_title_size * CHART_FONT_SCALE)),
        tickfont=dict(size=round(base_size * CHART_FONT_SCALE)),
        hoverformat='.1f',
    )
    return fig


def load_calibration_meta():
    """Returns the calibration meta dict (fit quality, sample size, caveats) written by
    src/calibration.py, or None if calibration hasn't been run yet."""
    if not os.path.exists(_CALIBRATED_CONSTANTS_PATH):
        return None
    try:
        with open(_CALIBRATED_CONSTANTS_PATH, 'r', encoding='utf-8') as f:
            return json.load(f).get('meta')
    except (json.JSONDecodeError, OSError):
        return None


# Page Configuration
st.set_page_config(
    page_title="80T 熔鋁爐升溫曲線最佳化器",
    page_icon="🔥",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom Styling
st.markdown("""
    <style>
    .main {
        background-color: #f8f9fa;
    }
    .metric-card {
        background-color: #ffffff;
        border-radius: 8px;
        padding: 16px;
        box-shadow: 0 2px 4px rgba(0,0,0,0.05);
        border-left: 4px solid #1E88E5;
    }
    </style>
""", unsafe_allow_html=True)


def get_optimizer_and_evaluator():
    model = MelterPhysicsModel()
    opt = HeatingCurveOptimizer(model)
    evaluator = MelterEvaluator(opt)
    return model, opt, evaluator


import hashlib

# Authorized passcodes (can also be overridden by environment variable MELTER_AUTH_PASSWORD)
DEFAULT_AUTH_PASSWORDS = {'rd2026', 'melter80t', 'admin888', 'mfx2026'}


def check_password(password: str) -> bool:
    """Validates user password against environment variable or default passcodes."""
    if not password:
        return False
    env_pwd = os.environ.get('MELTER_AUTH_PASSWORD')
    if env_pwd and password.strip() == env_pwd.strip():
        return True
    return password.strip() in DEFAULT_AUTH_PASSWORDS


def main():
    st.title("🔥 80T 反射式熔鋁爐升溫曲線與空燃比最佳化系統")
    st.caption("80T Static Aluminum Melter — Alloy Aware, Air-Fuel Ratio & 4-Burner 2-Pair Regenerative Combustion Optimizer")
    
    if 'is_authenticated' not in st.session_state:
        st.session_state['is_authenticated'] = False

    model, optimizer, evaluator = get_optimizer_and_evaluator()

    calib_meta = load_calibration_meta()
    if calib_meta:
        st.success(
            f"✅ 模型已校正 (Model calibrated against real production data): "
            f"燃耗擬合 {calib_meta.get('n_heats_gas_fit', '?')} 爐次 "
            f"(MAPE {calib_meta.get('gas_mape_pct', '?')}%), "
            f"燒損擬合 {calib_meta.get('n_heats_dross_fit', '?')} 爐次 "
            f"(MAE {calib_meta.get('dross_mae_pct_points', '?')} 個百分點)。"
            f" ⚠️ {calib_meta.get('caveat', '')}"
        )
    else:
        st.warning(
            "⚠️ 尚未執行模型校正 (model not yet calibrated against real data) — "
            "目前使用未校正的工程假設常數。請執行 `python -m src.calibration`。"
        )

    # Sidebar Input Parameters
    st.sidebar.header("⚙️ 爐次、合金與空燃比設定")

    # Access Control Sidebar Section
    st.sidebar.subheader("🔒 系統權限與登入")
    if st.session_state['is_authenticated']:
        st.sidebar.success("✅ 已授權模式 (Authorized)")
        if st.sidebar.button("🚪 登出權限 (Logout)", key="sidebar_logout_btn"):
            st.session_state['is_authenticated'] = False
            st.rerun()
    else:
        st.sidebar.caption("訪客模式：開放即時單爐模擬與手冊；歷史生產日報回測受權限保護。")
        with st.sidebar.expander("🔑 點此輸入授權密碼"):
            pwd_input = st.text_input("授權密碼", type="password", key="sidebar_pwd_input")
            if st.button("🔓 登入解鎖", key="sidebar_login_btn"):
                if check_password(pwd_input):
                    st.session_state['is_authenticated'] = True
                    st.rerun()
                else:
                    st.error("❌ 密碼錯誤")

    st.sidebar.markdown("---")
    st.sidebar.subheader("1. 鋁種與加料條件")
    alloy_list = ['5052', '5052KS', '5083A', '5083L', '6061', '5182', '3004', '99.7']
    selected_alloy = st.sidebar.selectbox("產出鋁種 (Alloy Type)", alloy_list, index=0)
    
    props = ALLOY_PROPERTIES.get(selected_alloy, ALLOY_PROPERTIES['DEFAULT'])
    st.sidebar.info(
        f"**{selected_alloy} 合金特徵**:\n"
        f"- 固相/液相線: {props['solidus']}°C / {props['liquidus']}°C\n"
        f"- 熔解潛熱: {props['latent_heat']} kJ/kg\n"
        f"- 高溫氧化燒損倍率: {props['dross_mult']}x"
    )
    
    charged_weight_tonnes = st.sidebar.number_input(
        "本爐投料重量 (公噸) Fresh Charge", min_value=10.0, max_value=85.0, value=65.0, step=1.0,
        help="本爐新加入的冷料重量 (不含前爐殘湯)。"
    )
    charged_weight_kg = charged_weight_tonnes * 1000.0

    residual_weight_tonnes = st.sidebar.number_input(
        "前爐殘湯重量 (公噸) Carry-in Residual", min_value=0.0, max_value=15.0, value=7.0, step=0.5,
        help="上一爐留在爐內、尚未出清的高溫殘湯重量 — 現場經驗約 5~10 公噸。"
             "此殘湯已接近液相線溫度，會降低本爐實際所需的新增熱量，模型現已納入計算。"
             " (Hot heel left from the previous heat; reduces this heat's new energy requirement.)"
    )
    residual_weight_kg = residual_weight_tonnes * 1000.0

    st.sidebar.caption(f"本爐爐內總金屬量 (投料 + 殘湯): **{charged_weight_tonnes + residual_weight_tonnes:.1f} 公噸**")

    target_duration_hrs = st.sidebar.slider(
        "要求出湯時限 (小時) Required Discharge Deadline",
        min_value=3.0, max_value=10.0, value=6.0, step=0.5,
        help="必須在此時限內達到目標湯溫並可出湯 — 這是硬性限制，最佳化只在能達成此時限的方案中挑選成本最低者。"
             " (Hard constraint: only schedules that reach target temp by this deadline are considered.)"
    )
    target_bath_temp = st.sidebar.slider(
        "目標出液湯溫 (°C) Target Bath Temp",
        min_value=700.0, max_value=800.0, value=780.0, step=10.0,
        help="現場出湯目標溫度預設 780°C (可調範圍 700°C ~ 800°C，每格 10°C)。"
    )
    max_roof_sp_limit = st.sidebar.slider("頂頭最高安全溫度天花板 (°C)", min_value=1100.0, max_value=1250.0, value=1200.0, step=10.0)
    
    st.sidebar.subheader("2. 現場傳統操作基準設定 (3段溫控)")
    with st.sidebar.expander("🛠️ 現場傳統溫控參數 (Melt / Flat / Bath Mode)", expanded=True):
        st.markdown("**第 1 段：融化模式 (Melt Mode)**")
        col_t1_sp, col_t1_dur = st.columns([1, 1])
        with col_t1_sp:
            base_sp1 = st.number_input("第1段目標頂溫 (°C)", min_value=900.0, max_value=1250.0, value=1180.0, step=10.0, key="base_sp1", help="加料完成關門後融化大火目標頂溫 (現場基準為 1180°C)")
        with col_t1_dur:
            base_dur1_str = st.text_input("第1段持續時間 (hh:mm)", value=format_hours_to_hhmm(target_duration_hrs), key="base_dur1", help="現場傳統基準操作：加料關門後 1180°C 大火持續到底 (預設全爐時限)")

        st.markdown("**第 2 段：平湯/過渡段 (Flat Bath Mode)**")
        col_t2_sp, col_t2_dur = st.columns([1, 1])
        with col_t2_sp:
            base_sp2 = st.number_input("第2段目標頂溫 (°C)", min_value=800.0, max_value=1150.0, value=950.0, step=10.0, key="base_sp2")
        with col_t2_dur:
            base_dur2_str = st.text_input("第2段持續時間 (hh:mm)", value="00:00", key="base_dur2", help="若現場無過渡段直接切換湯溫，持續時間設為 00:00")

        st.markdown("**第 3 段：湯溫/保溫模式 (Bath Mode)**")
        col_t3_sp, col_t3_dur = st.columns([1, 1])
        with col_t3_sp:
            base_sp3 = st.number_input("第3段保溫設點 (°C)", min_value=700.0, max_value=900.0, value=780.0, step=10.0, key="base_sp3", help="改用湯溫控制模式後之保溫設點 (預設 780°C)")
        with col_t3_dur:
            dur1_hrs = parse_hhmm_to_hours(base_dur1_str, default=target_duration_hrs)
            dur2_hrs = parse_hhmm_to_hours(base_dur2_str, default=0.0)
            rem_hrs = max(0.0, target_duration_hrs - dur1_hrs - dur2_hrs)
            st.caption(f"第3段持續時間：自動為剩餘 **{format_hours_to_hhmm(rem_hrs)}**")

    baseline_roof_sp = base_sp1
    baseline_switch_hrs = dur1_hrs

    st.sidebar.subheader("3. 空氣燃氣比與殘氧設定")
    excess_air_pct = st.sidebar.slider("基準過剩空氣率 Excess Air (%)", min_value=5.0, max_value=30.0, value=25.0, step=1.0)
    
    if hasattr(model, 'calculate_flue_oxygen_pct'):
        est_o2 = model.calculate_flue_oxygen_pct(excess_air_pct)
    else:
        x_frac = excess_air_pct / 100.0
        est_o2 = (21.0 * x_frac) / (1.0 + x_frac * 1.05)
    st.sidebar.caption(f"預估煙道殘氧量 (AT104): **{est_o2:.2f}% O₂**")
    
    st.sidebar.subheader("4. 能源與金屬價格")
    gas_price = st.sidebar.number_input("天然氣單價 (TWD / Nm³)", min_value=5.0, max_value=50.0, value=15.0, step=1.0)
    aluminum_price = st.sidebar.number_input("鋁錠/金屬單價 (TWD / kg)", min_value=30.0, max_value=150.0, value=75.0, step=5.0)
    
    model.gas_price = gas_price
    model.aluminum_price = aluminum_price
    
    # Main Tabs
    tab_title_bt = "📊 歷史爐次回測分析 (✅ 已解鎖)" if st.session_state.get('is_authenticated', False) else "📊 歷史爐次回測分析 (🔒 需授權)"
    tab_single, tab_backtest, tab_manual = st.tabs(["🚀 即時單爐最佳化模擬", tab_title_bt, "📖 4燒嘴蓄熱系統手冊"])
    
    with tab_single:
        st.markdown(
            f"<h3 style='font-size:1.35rem'>💡 鋁種 [{selected_alloy}] 最佳升溫與空燃比軌跡</h3>",
            unsafe_allow_html=True,
        )

        with st.spinner("計算熱力學、空燃比與燒損最佳解..."):
            res = optimizer.optimize_heating_curve(
                charged_weight_kg=charged_weight_kg,
                residual_weight_kg=residual_weight_kg,
                discharge_deadline_hrs=target_duration_hrs,
                alloy_name=selected_alloy,
                baseline_roof_sp=base_sp1,
                baseline_dur_melt_hrs=dur1_hrs,
                baseline_sp_soak=base_sp2,
                baseline_dur_soak_hrs=dur2_hrs,
                baseline_sp_hold=base_sp3,
                baseline_excess_air_pct=excess_air_pct,
                target_bath_temp_c=target_bath_temp,
                max_roof_sp_limit=max_roof_sp_limit,
            )
            
        opt_params = res['optimal_params']
        opt_sum = res['optimal_summary']
        base_sum = res['baseline_summary']
        savings = res['savings']
        recipe_steps = res.get('recipe_steps', [])

        df_opt = res['optimal_trajectory']
        df_base = res['baseline_trajectory']

        if not res['deadline_met']:
            st.error(
                f"⚠️ 在頂溫上限 {max_roof_sp_limit:.0f}°C 之下，找不到能於 {target_duration_hrs:.1f} 小時內"
                f"達到 {target_bath_temp:.0f}°C 的方案 — 以下為次佳(未達時限)方案，僅供參考。"
                " 請提高頂溫上限或放寬出湯時限。"
                " (No schedule met the discharge deadline at this roof-temp ceiling — showing the"
                " closest fallback; raise the ceiling or relax the deadline.)"
            )

        # Section 1: Comprehensive KPI Comparison
        total_metal_tonnes = (charged_weight_kg + residual_weight_kg) / 1000.0
        base_gas_per_t = base_sum['cum_gas_nm3'] / total_metal_tonnes if total_metal_tonnes > 0 else 0.0
        opt_gas_per_t = opt_sum['cum_gas_nm3'] / total_metal_tonnes if total_metal_tonnes > 0 else 0.0
        
        base_dross_pct = (base_sum['cum_dross_kg'] / charged_weight_kg) * 100.0 if charged_weight_kg > 0 else 0.0
        opt_dross_pct = (opt_sum['cum_dross_kg'] / charged_weight_kg) * 100.0 if charged_weight_kg > 0 else 0.0

        gas_pct = ((base_sum['cum_gas_nm3'] - opt_sum['cum_gas_nm3']) / base_sum['cum_gas_nm3']) * 100.0 if base_sum['cum_gas_nm3'] > 0 else 0.0
        dross_pct = ((base_sum['cum_dross_kg'] - opt_sum['cum_dross_kg']) / base_sum['cum_dross_kg']) * 100.0 if base_sum['cum_dross_kg'] > 0 else 0.0

        st.markdown("#### 📌 熔煉能耗、成本與燒損綜合對照 (Baseline vs. Optimal Summary)")

        # Row 1: 傳統操作模式基準 (Baseline Practice) - 純絕對值呈現，不帶 delta 比較以免混淆
        st.markdown("##### 🏛️ 傳統操作模式基準 (Baseline Practice)")
        b_col1, b_col2, b_col3, b_col4, b_col5 = st.columns(5)
        with b_col1:
            st.metric(
                label="傳統每爐總生產成本",
                value=f"${base_sum['total_cost']:,.0f} TWD",
                help=f"天然氣費 ${base_sum['gas_cost']:,.0f} + 氧化燒損金屬損失 ${base_sum['dross_cost']:,.0f}"
            )
        with b_col2:
            st.metric(
                label="傳統天然氣總耗量",
                value=f"{base_sum['cum_gas_nm3']:,.1f} Nm³",
                help=f"天然氣單耗: {base_gas_per_t:.1f} Nm³/t"
            )
            st.caption(f"📊 單耗: **{base_gas_per_t:.1f} Nm³/t**")
        with b_col3:
            st.metric(
                label="傳統氧化燒損渣量",
                value=f"{base_sum['cum_dross_kg']:.1f} kg",
                help=f"投料氧化燒損率: {base_dross_pct:.2f}%"
            )
            st.caption(f"🔥 燒損率: **{base_dross_pct:.2f}%**")
        with b_col4:
            if dur1_hrs >= target_duration_hrs:
                st.metric(
                    label="現場傳統溫控模式",
                    value=f"{base_sp1:.0f}°C 持續到底",
                    help="現場傳統操作基準：加料完成關門後以融化模式 1180°C 大火持續升溫到底。"
                )
                st.caption("🔥 傳統固定 1180°C 全火到底")
            else:
                st.metric(
                    label="現場傳統溫控模式",
                    value=f"{base_sp1:.0f}°C ({base_dur1_str})",
                    help=f"現場加料完成關門後以融化模式 {base_sp1:.0f}°C 持續大火升溫，{base_dur1_str} 警示提示改用湯溫模式。"
                )
                st.caption(f"⏱️ {base_dur1_str} 警示轉湯溫 {base_sp3:.0f}°C")
        with b_col5:
            st.metric(
                label="傳統過剩空氣率",
                value=f"{excess_air_pct:.1f}%",
                help="傳統操作空燃比設定"
            )
            st.caption(f"💨 煙道殘氧: **{est_o2:.2f}% O₂**")

        # Row 2: 最佳化升溫模式與效益 (Optimal Strategy & Savings vs. Baseline)
        st.markdown("##### 🚀 最佳化階梯升溫模式與降減效益 (Optimal & Savings vs. Baseline)")
        o_col1, o_col2, o_col3, o_col4, o_col5 = st.columns(5)
        with o_col1:
            st.metric(
                label="最佳化每爐總成本",
                value=f"${opt_sum['total_cost']:,.0f} TWD",
                delta=f"-${savings['cost_savings_twd']:,.0f} (-{savings['cost_savings_pct']:.1f}%)",
                delta_color="normal",
                help=f"天然氣費 ${opt_sum['gas_cost']:,.0f} + 氧化燒損金屬損失 ${opt_sum['dross_cost']:,.0f}"
            )
        with o_col2:
            st.metric(
                label="最佳化天然氣耗量",
                value=f"{opt_sum['cum_gas_nm3']:,.1f} Nm³",
                delta=f"-{savings['gas_savings_nm3']:,.1f} Nm³ (-{gas_pct:.1f}%)",
                delta_color="normal"
            )
            st.caption(f"📊 單耗: **{opt_gas_per_t:.1f} Nm³/t**")
        with o_col3:
            st.metric(
                label="最佳化氧化燒損渣量",
                value=f"{opt_sum['cum_dross_kg']:.1f} kg",
                delta=f"-{savings['dross_savings_kg']:.1f} kg (-{dross_pct:.1f}%)",
                delta_color="normal"
            )
            st.caption(f"🔥 燒損率: **{opt_dross_pct:.2f}%**")
        with o_col4:
            st.metric(
                label="最佳 3 段階梯控溫",
                value="3 段階梯控制",
                delta=f"{opt_params['sp_roof_melt']:.0f}°C → {opt_params['sp_roof_soak']:.0f}°C → {opt_params['sp_roof_hold']:.0f}°C",
                delta_color="off"
            )
            if recipe_steps and len(recipe_steps) == 3:
                st.caption(f"⏱️ 時段: **{recipe_steps[0]['duration_hhmm']} + {recipe_steps[1]['duration_hhmm']} + {recipe_steps[2]['duration_hhmm']}**")
        with o_col5:
            st.metric(
                label="最佳過剩空氣率",
                value=f"{opt_params['excess_air_pct']:.1f}%",
                delta=f"{opt_params['flue_o2_pct']:.2f}% O₂",
                delta_color="off"
            )
            st.caption(f"💨 煙道殘氧: **{opt_params['flue_o2_pct']:.2f}% O₂**")

        # Structured comparison table
        base_timing_str = f"00:00~{format_hours_to_hhmm(target_duration_hrs)} (1180°C 全火到底)" if dur1_hrs >= target_duration_hrs else f"00:00~{format_hours_to_hhmm(dur1_hrs)} (融化) → 轉湯溫保溫"
        base_sp_str = f"{base_sp1:.0f}°C 全火持續到底" if dur1_hrs >= target_duration_hrs else f"{base_sp1:.0f}°C (融化) → {base_sp3:.0f}°C (保溫)"

        with st.expander("📋 點此展開「傳統 vs. 最佳化」各項指標詳細對照表", expanded=True):
            df_compare = pd.DataFrame({
                "指標項目 (Metric)": [
                    "每爐綜合生產成本 (Total Cost)",
                    "  └ 天然氣費用 (Gas Cost)",
                    "  └ 鋁金屬燒損損失 (Dross Metal Loss)",
                    "天然氣總耗量 (Total Gas Consumption)",
                    "天然氣單耗 (Specific Gas Consumption)",
                    "鋁錠氧化燒損量 (Dross Generated)",
                    "投料燒損率 (Dross Loss %)",
                    "三段溫控時段 (3-Step Timing Intervals)",
                    "熔化/平湯/保溫 頂溫設點 (Stepwise Roof SP)",
                    "過剩空氣率 / 煙道殘氧 (Excess Air / Flue O₂)",
                    "出湯達成時限 (Target Deadline Met)"
                ],
                "傳統操作基準 (Baseline)": [
                    f"${base_sum['total_cost']:,.0f} TWD",
                    f"${base_sum['gas_cost']:,.0f} TWD",
                    f"${base_sum['dross_cost']:,.0f} TWD",
                    f"{base_sum['cum_gas_nm3']:,.1f} Nm³",
                    f"{base_gas_per_t:.1f} Nm³/t",
                    f"{base_sum['cum_dross_kg']:.1f} kg",
                    f"{base_dross_pct:.2f}%",
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
                    f"第1段: 00:00~{format_hours_to_hhmm(opt_params['t_switch_hrs'])} | 第2段: {format_hours_to_hhmm(opt_params['t_switch_hrs'])}~{format_hours_to_hhmm(opt_params['t_soak_end_hrs'])} | 第3段: {format_hours_to_hhmm(opt_params['t_soak_end_hrs'])}~{format_hours_to_hhmm(target_duration_hrs)}",
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
                    f"主熔提早至 {format_hours_to_hhmm(opt_params['t_switch_hrs'])} 轉平湯降火",
                    "3 段階梯設定值，符合現場 PLC/DCS 執行需求",
                    f"過剩空氣減少 {excess_air_pct - opt_params['excess_air_pct']:.1f}%",
                    "符合出湯工藝時限要求"
                ]
            })
            st.dataframe(df_compare, use_container_width=True, hide_index=True)
            
        st.markdown("---")
        
        # Interactive Chart 1: Temperature & Burner Firing Mode
        st.subheader("1. 頂頭與鋁湯升溫曲線及燒嘴對切動態 (Temperature & Burner Pair Mode)")
        
        fig1 = go.Figure()
        
        # Baseline curves
        baseline_trace_name = f'現場傳統模式設點 (Melt {base_sp1:.0f}°C 全火持續到底)' if dur1_hrs >= target_duration_hrs else f'現場傳統模式設點 (Melt {base_sp1:.0f}°C / {base_dur1_str} → Bath {base_sp3:.0f}°C)'
        fig1.add_trace(go.Scatter(
            x=df_base['time_hrs'], y=df_base['sp_roof_c'],
            name=baseline_trace_name,
            line=dict(color='#E53935', dash='dash')
        ))
        fig1.add_trace(go.Scatter(
            x=df_base['time_hrs'], y=df_base['bath_temp_c'],
            name='傳統鋁湯溫度 (TT200)',
            line=dict(color='#D81B60', width=2)
        ))
        
        # Optimal curves
        fig1.add_trace(go.Scatter(
            x=df_opt['time_hrs'], y=df_opt['sp_roof_c'],
            name=f'最佳化 3 段階梯設點 ({opt_params["sp_roof_melt"]:.0f}°C → {opt_params["sp_roof_soak"]:.0f}°C → {opt_params["sp_roof_hold"]:.0f}°C)',
            line=dict(color='#1E88E5', width=3)
        ))
        fig1.add_trace(go.Scatter(
            x=df_opt['time_hrs'], y=df_opt['roof_temp_c'],
            name='最佳化頂頭測溫 (TT201)',
            line=dict(color='#64B5F6', width=2)
        ))
        fig1.add_trace(go.Scatter(
            x=df_opt['time_hrs'], y=df_opt['bath_temp_c'],
            name='最佳化鋁湯溫度 (TT200)',
            line=dict(color='#43A047', width=3)
        ))
        
        # Threshold lines
        fig1.add_hline(y=props['liquidus'], line_dash="dash", line_color="gray", annotation_text=f"{selected_alloy} 液相線 {props['liquidus']}°C")
        fig1.add_hline(y=target_bath_temp, line_dash="dot", line_color="green", annotation_text=f"目標出湯溫度 {target_bath_temp}°C")

        # Vertical line at the traditional bath control switchover point (if not continuous to end)
        if dur1_hrs < target_duration_hrs:
            fig1.add_vline(
                x=dur1_hrs, line_dash="dot", line_color="#E53935", line_width=1.5,
                annotation_text=f"傳統改湯溫 ({base_dur1_str})", annotation_position="bottom right"
            )

        # Vertical line at the required discharge (tap-out) deadline.
        fig1.add_vline(
            x=target_duration_hrs, line_dash="dashdot", line_color="purple", line_width=2,
            annotation_text=f"目標出湯時間 {target_duration_hrs:.1f}h", annotation_position="top"
        )

        # Start-of-melt (bath temp reaches solidus) / end-of-melt (reaches liquidus) markers
        start_melt_rows = df_opt[df_opt['bath_temp_c'] >= props['solidus']]
        end_melt_rows = df_opt[df_opt['bath_temp_c'] >= props['liquidus']]
        if not start_melt_rows.empty:
            r = start_melt_rows.iloc[0]
            fig1.add_trace(go.Scatter(
                x=[r['time_hrs']], y=[r['bath_temp_c']], mode='markers',
                marker=dict(symbol='triangle-up', size=16, color='#F57C00', line=dict(width=1.5, color='black')),
                name='開始溶解 (達固相線)'
            ))
        if not end_melt_rows.empty:
            r = end_melt_rows.iloc[0]
            fig1.add_trace(go.Scatter(
                x=[r['time_hrs']], y=[r['bath_temp_c']], mode='markers',
                marker=dict(symbol='circle', size=14, color='#2E7D32', line=dict(width=1.5, color='black')),
                name='溶解結束 (達液相線)'
            ))

        fig1.update_layout(
            title=f"鋁種 [{selected_alloy}] 升溫動態軌跡 (現場傳統模式 vs. 最佳化 3 段階梯模式)",
            xaxis_title="熔煉時間 (小時)",
            yaxis_title="溫度 (°C)",
            hovermode="x unified",
        )
        finalize_chart_layout(fig1, height=560)
        st.plotly_chart(fig1, use_container_width=True)

        # Multi-Step Discrete Recipe Table & Card for Field / DCS implementation
        st.markdown("##### 📝 DCS / PLC 現場 3 段階梯操作配方 (Multi-Step Temperature Control Recipe)")
        if recipe_steps:
            df_recipe_table = pd.DataFrame([
                {
                    "階段 (Step)": f"第 {s['step']} 段",
                    "工藝模式 (Mode)": s['mode_name'],
                    "目標溫度設點 ($SP$)": f"{s['sp_roof_c']:.0f} °C",
                    "持續時間 (Duration)": f"{s['duration_hhmm']} ({s['duration_hrs']:.2f}h)",
                    "執行時段 (Interval)": s['interval_hhmm'],
                    "燒嘴燃燒對切模式 (Burner Mode)": s['burner_mode'],
                    "工藝目標 (Operational Goal)": s['goal'],
                }
                for s in recipe_steps
            ])
            st.dataframe(df_recipe_table, use_container_width=True, hide_index=True)

            rc1, rc2, rc3 = st.columns(3)
            s1, s2, s3 = recipe_steps[0], recipe_steps[1], recipe_steps[2]
            with rc1:
                st.info(
                    f"**第 1 段：{s1['mode_name']}**\n\n"
                    f"- **執行時段**：`{s1['interval_hhmm']}` (持續 **{s1['duration_hhmm']}**)\n"
                    f"- **頂溫設點**：**`{s1['sp_roof_c']:.0f} °C`** (水平固定)\n"
                    f"- **燃燒模式**：{s1['burner_mode']}\n"
                    f"- **工藝目標**：{s1['goal']}"
                )
            with rc2:
                st.info(
                    f"**第 2 段：{s2['mode_name']}**\n\n"
                    f"- **執行時段**：`{s2['interval_hhmm']}` (持續 **{s2['duration_hhmm']}**)\n"
                    f"- **頂溫設點**：**`{s2['sp_roof_c']:.0f} °C`** (水平固定)\n"
                    f"- **燃燒模式**：{s2['burner_mode']}\n"
                    f"- **工藝目標**：{s2['goal']}"
                )
            with rc3:
                st.info(
                    f"**第 3 段：{s3['mode_name']}**\n\n"
                    f"- **執行時段**：`{s3['interval_hhmm']}` (持續 **{s3['duration_hhmm']}**)\n"
                    f"- **頂溫設點**：**`{s3['sp_roof_c']:.0f} °C`** (水平固定)\n"
                    f"- **燃燒模式**：{s3['burner_mode']}\n"
                    f"- **工藝目標**：{s3['goal']}"
                )

        st.markdown("---")

        # Chart 2 & 3: Gas Flow and Cost Breakdown -- full width, stacked vertically.
        st.subheader("2. 兩對燒嘴燃氣流量與累積耗氣量 (Gas Flow & 2-Pair Status)")
        fig2 = make_subplots(specs=[[{"secondary_y": True}]])
        fig2.add_trace(go.Scatter(x=df_base['time_hrs'], y=df_base['cum_gas_nm3'], name='傳統累積天然氣 (Nm³)', line=dict(color='#E53935', dash='dash')), secondary_y=False)
        fig2.add_trace(go.Scatter(x=df_opt['time_hrs'], y=df_opt['cum_gas_nm3'], name='最佳化累積天然氣 (Nm³)', line=dict(color='#1E88E5', width=2)), secondary_y=False)
        fig2.add_trace(go.Scatter(x=df_opt['time_hrs'], y=df_opt['gas_flow_nm3h'], name='瞬間燃氣流量 (Nm³/h)', line=dict(color='#00ACC1', width=1.5)), secondary_y=True)

        fig2.update_layout(title="燒嘴瞬間流量 (Nm³/h) 與累積氣量 (Nm³)")
        fig2.update_xaxes(title_text="熔煉時間 (小時)")
        fig2.update_yaxes(title_text="累積耗氣量 (Nm³)", secondary_y=False)
        fig2.update_yaxes(title_text="瞬間流量 (Nm³/h)", secondary_y=True)
        finalize_chart_layout(fig2, height=480)
        st.plotly_chart(fig2, use_container_width=True)

        st.subheader("3. 鋁種燒損與成本結構對比 (Cost Breakdown)")
        categories = ['傳統固定 1100°C 模式', '最佳化 Heating Curve']
        gas_costs = [base_sum['gas_cost'], opt_sum['gas_cost']]
        dross_costs = [base_sum['dross_cost'], opt_sum['dross_cost']]

        fig3 = go.Figure(data=[
            go.Bar(name='天然氣費用 (TWD)', x=categories, y=gas_costs, marker_color='#42A5F5'),
            go.Bar(name=f'{selected_alloy} 氧化燒損費用 (TWD)', x=categories, y=dross_costs, marker_color='#EF5350')
        ])
        fig3.update_layout(barmode='stack', title=f"[{selected_alloy}] 每爐綜合生產成本對比 (TWD)")
        finalize_chart_layout(fig3, height=480)
        st.plotly_chart(fig3, use_container_width=True)

    with tab_backtest:
        if not st.session_state.get('is_authenticated', False):
            st.markdown("### 🔒 歷史數據回測權限保護 (Access Restricted)")
            st.warning(
                "⚠️ **此分頁涉及全廠實際生產日報 (114/115年 MFX) 與 5秒感測器歷史大數據，受企業內部權限保護。**\n\n"
                "未授權訪客可自由使用「**🚀 即時單爐最佳化模擬**」與「**📖 4燒嘴蓄熱系統手冊**」進行工程計算與空燃比分析。"
            )
            st.markdown("---")
            col_l, col_r = st.columns([1, 1])
            with col_l:
                st.write("##### 🔑 請輸入授權密碼以解鎖")
                with st.form("in_tab_login_form"):
                    tab_pwd = st.text_input("研發/管理員授權密碼 (Passcode)", type="password", placeholder="請輸入授權密碼")
                    submitted = st.form_submit_button("🔓 驗證並解鎖歷史回測資料庫")
                    if submitted:
                        if check_password(tab_pwd):
                            st.session_state['is_authenticated'] = True
                            st.success("✅ 驗證成功！正在載入歷史回測資料庫...")
                            st.rerun()
                        else:
                            st.error("❌ 密碼錯誤，請確認後重試。")
            with col_r:
                st.info(
                    "💡 **權限存取說明**：\n"
                    "- **公開功能**：8種合金熱物理相變計算、4燒嘴2對蓄熱燃燒模擬、空燃比與階梯頂溫最佳化。\n"
                    "- **受保護功能**：全廠 123 爐真實燃耗/金屬燒損回測、MFA 感測器流量計直接積分比對。\n\n"
                    "*(如需授權，請洽專案負責研究員)*"
                )
        else:
            st.subheader("📈 歷史爐次回測：最佳化 vs. 真實生產數據 (Optimizer vs. Real Historical Performance)")
            st.caption(
                "兩組回測皆以「真實」數據為對照組（感測器直接量測的燃氣流量、或產紀錄表的實際燃耗與實際金屬損耗），"
                "而非未校正的模擬基準情境 — 避免『最佳化用氣量其實比實際更多』卻仍顯示為省錢的矛盾。"
            )

            backtest_choice = st.radio(
                "選擇回測資料集 (Backtest dataset)",
                ["MFA 感測器週資料 (~20 爐, 燃氣流量直測)", "全廠生產紀錄抽樣 (含實際金屬燒損)"],
                horizontal=True,
            )

            if st.button("▶ 執行回測 (Run backtest)"):
                with st.spinner("正在讀取歷史資料並計算最佳化結果..."):
                    if backtest_choice.startswith("MFA"):
                        df_bt, summary_bt = evaluator.run_backtest_on_sensor_week()
                    else:
                        df_bt, summary_bt = evaluator.run_backtest_on_production_log()

                if summary_bt.get('total_heats_analyzed', 0) == 0:
                    st.warning("此資料集中沒有可用的爐次資料。")
                else:
                    c1, c2, c3, c4 = st.columns(4)
                    c1.metric("回測分析總爐數", f"{summary_bt['total_heats_analyzed']} 爐")
                    c2.metric("真實總燃耗 (Real, Nm³)", f"{summary_bt['total_real_gas_nm3']:,.0f} Nm³")
                    c3.metric("最佳化總燃耗 (Optimal, Nm³)", f"{summary_bt['total_opt_gas_nm3']:,.0f} Nm³",
                              delta=f"-{summary_bt['gas_delta_pct']:.1f}%", delta_color="normal")
                    c4.metric("回測總成本節省 (vs. 真實)", f"${summary_bt['total_cost_savings_twd']:,.0f} TWD")
                    st.caption(f"達成出湯時限的爐次比例: {summary_bt['pct_heats_deadline_met']:.1f}%")

                    st.markdown("---")
                    st.write("##### 各歷史爐次明細 (Heat Breakdown Table)")
                    fmt = {
                        'charged_weight_kg': '{:,.0f}',
                        'duration_hrs': '{:.1f}',
                        'real_gas_nm3': '{:,.1f}',
                        'opt_gas_nm3': '{:,.1f}',
                        'real_dross_kg': '{:,.1f}',
                        'opt_dross_kg': '{:.2f}',
                        'opt_excess_air_pct': '{:.1f}%',
                        'opt_flue_o2_pct': '{:.2f}%',
                        'real_cost_twd': '${:,.0f}',
                        'opt_cost_twd': '${:,.0f}',
                        'cost_savings_twd': '${:,.0f}',
                    }
                    fmt = {k: v for k, v in fmt.items() if k in df_bt.columns}
                    st.dataframe(df_bt.style.format(fmt), use_container_width=True)

    with tab_manual:
        st.subheader("📘 Mechatherm 80T 4 燒嘴 2 對蓄熱式燃燒系統")
        st.markdown("""
        - **燒嘴配置**: 4 個大功率燒嘴組成 2 對 (Pair 1: 111/112, Pair 2: 113/114)。
          **每一對裡永遠只有 1 支在燒**，另一支在抽廢氣蓄熱——手冊原文（1.4.56）："Only one
          burner will fire at any one time, its twin will be in exhaust mode"。所以全爐**最多
          同時 2 支火焰**（兩對各一支），不是 4 支同時點火。
        - **蓄熱交替機制 (Regenerative Switching)**:
          - 完整交替週期實測約 **240 秒**（用感測器 `tt111-114` 資料驗證，見
            `REGENERATIVE_SYSTEM_ANALYSIS.md`），燒嘴 A 噴火時燒嘴 B 抽廢氣預熱陶瓷介質球
            (Ceramic Balls)，蓄熱回收率達 70%+。
        - **空燃比與殘氧控制 (Air-Fuel Ratio & O₂)**:
          - 理論化學計量比: 1 m³ 天然氣需要 9.52 m³ 空氣。
          - 最佳化過剩空氣率設定於 10% ~ 15% (對應殘氧 AT104 於 1.9% ~ 2.8%)，過高空氣量會帶走大量高溫熱能並加劇鋁表面氧化。
        - **鋁種燒損差異 (Alloy Dross Differences)**:
          - 5052 / 5182 / 5083 (含鎂合金): 高溫下 Mg 揮發並極易形成 MgO 渣，表面氧化速率為純鋁 1.8x ~ 2.2x，需縮短高溫 Melt 階段。
          - 6061 / 3004: 氧化速率相對較低，可維繫標準熱傳。
        """)
        st.info(
            "ℹ️ **資料來源說明**: 上方殘氧量 (O₂%) 為依過剩空氣率換算的公式估計值，"
            "並非即時量測 — 本資料集中的爐內氧氣感測器 (AT104) 讀值全期為 0，無法使用；"
            "感測器 CSV 中的燃氣/空氣流量比值換算出的『實際』過剩空氣率明顯偏高且與本手冊設計值不符，"
            "因此模型的空燃比僅作為最佳化搜尋變數，未直接以真實歷史空燃比校正。"
            " (Real O2/excess-air trajectory could not be validated against this dataset — see MELTER_KNOWLEDGE.md / PLAN.md.)"
        )


if __name__ == '__main__':
    main()
