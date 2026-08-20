"""
Configuration Manager for 80T Aluminum Melter Heating Curve Optimizer.
Handles loading, saving, and persisting user default parameters and internal physics model assumptions.
"""

import json
import os
from typing import Dict, Any

CONFIG_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'config')
CONFIG_FILE_PATH = os.path.join(CONFIG_DIR, 'furnace_parameters.json')

DEFAULT_APP_CONFIG: Dict[str, Any] = {
    # 1. 預設操作工藝與邊界條件 (Initial Load Defaults)
    "process": {
        "alloy_name": "5052",
        "charged_weight_tonnes": 65.0,
        "residual_weight_tonnes": 0.0,
        "target_duration_hrs": 6.0,
        "target_bath_temp_c": 780.0,
        "max_roof_sp_limit": 1200.0,
        "excess_air_pct": 40.0,
        "gas_price": 15.0,
        "aluminum_price": 75.0,
        "baseline_sp1": 1180.0,
        "baseline_dur1_hhmm": "06:00",
        "baseline_sp2": 1050.0,
        "baseline_dur2_hhmm": "00:00",
        "baseline_sp3": 780.0,
    },
    # 2. 物理模型與爐體幾何/熱工假設參數 (Internal Physics Model Parameters)
    "physics": {
        "hearth_area_m2": 66.15,
        "wall_loss_kw": 250.0,
        "hearth_loss_ref_kw": 85.0,
        "dross_factor_flat": 0.70,
        "emissivity_eff": 0.85,
        "gas_lhv_kj_nm3": 37256.0,
        "max_gas_flow_dual_pair": 880.0,
        "max_gas_flow_single_pair": 440.0,
        "min_gas_flow_nm3h": 50.0,
        "burnoff_ea": 45000.0,
        "burnoff_k0": 0.8583,
        "regen_base_eff": 0.74,
    },
    # 3. 現場工藝動態附加損耗 (Field Operational Overhead Losses)
    "overhead": {
        "enable_overhead": True,
        "charge_door_open_mins": 60.0,
        "dross_door_open_mins": 20.0,
        "reversal_loss_pct": 4.0,
        "refractory_reheat_gj": 7.0,
        "actual_total_duration_hrs": 5.87,
    }
}


def ensure_config_dir():
    """Ensures that the config directory exists."""
    if not os.path.exists(CONFIG_DIR):
        os.makedirs(CONFIG_DIR, exist_ok=True)


def load_app_config() -> Dict[str, Any]:
    """Loads configuration from JSON file. If file does not exist, creates it with defaults."""
    ensure_config_dir()
    if not os.path.exists(CONFIG_FILE_PATH):
        save_app_config(DEFAULT_APP_CONFIG)
        return json.loads(json.dumps(DEFAULT_APP_CONFIG))
    
    try:
        with open(CONFIG_FILE_PATH, 'r', encoding='utf-8') as f:
            cfg = json.load(f)
            
        # Ensure all required keys exist (merge with defaults for backwards compatibility)
        merged_cfg = json.loads(json.dumps(DEFAULT_APP_CONFIG))
        if 'process' in cfg:
            merged_cfg['process'].update(cfg['process'])
        if 'physics' in cfg:
            merged_cfg['physics'].update(cfg['physics'])
        if 'overhead' in cfg:
            merged_cfg['overhead'].update(cfg['overhead'])
        return merged_cfg
    except Exception as e:
        print(f"Warning: Failed to load config from {CONFIG_FILE_PATH}: {e}. Using defaults.")
        return json.loads(json.dumps(DEFAULT_APP_CONFIG))


def save_app_config(config_dict: Dict[str, Any]) -> bool:
    """Saves configuration to JSON file."""
    ensure_config_dir()
    try:
        with open(CONFIG_FILE_PATH, 'w', encoding='utf-8') as f:
            json.dump(config_dict, f, indent=4, ensure_ascii=False)
        return True
    except Exception as e:
        print(f"Error saving config to {CONFIG_FILE_PATH}: {e}")
        return False


def reset_app_config() -> Dict[str, Any]:
    """Resets configuration file to factory defaults and returns it."""
    save_app_config(DEFAULT_APP_CONFIG)
    return json.loads(json.dumps(DEFAULT_APP_CONFIG))


if __name__ == '__main__':
    cfg = load_app_config()
    print("Loaded config:", json.dumps(cfg, indent=2, ensure_ascii=False))
