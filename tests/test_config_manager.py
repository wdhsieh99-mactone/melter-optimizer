"""
Unit tests for configuration manager and parameter persistence.
"""

import os
import json
import pytest
from src.config_manager import (
    load_app_config,
    save_app_config,
    reset_app_config,
    DEFAULT_APP_CONFIG,
    CONFIG_FILE_PATH,
)
from src.physics_model import MelterPhysicsModel
from src.optimizer import HeatingCurveOptimizer


def test_load_and_reset_config():
    reset_app_config()
    cfg = load_app_config()
    assert 'process' in cfg
    assert 'physics' in cfg
    assert cfg['process']['alloy_name'] == '5052'
    assert cfg['physics']['hearth_area_m2'] == 66.15


def test_save_custom_config():
    cfg = load_app_config()
    orig_temp = cfg['process']['target_bath_temp_c']
    cfg['process']['target_bath_temp_c'] = 770.0
    cfg['physics']['wall_loss_kw'] = 260.0
    
    assert save_app_config(cfg) is True
    
    reloaded = load_app_config()
    assert reloaded['process']['target_bath_temp_c'] == 770.0
    assert reloaded['physics']['wall_loss_kw'] == 260.0
    
    # Restore defaults
    reset_app_config()
    restored = load_app_config()
    assert restored['process']['target_bath_temp_c'] == 780.0
    assert restored['physics']['wall_loss_kw'] == 250.0


def test_model_with_custom_config():
    cfg = load_app_config()
    p_cfg = cfg['physics']
    model = MelterPhysicsModel(
        wall_loss_kw=p_cfg['wall_loss_kw'],
        hearth_area_m2=p_cfg['hearth_area_m2'],
        hearth_loss_ref_kw=p_cfg['hearth_loss_ref_kw'],
        dross_factor_flat=p_cfg['dross_factor_flat'],
        regen_base_eff=p_cfg['regen_base_eff']
    )
    assert model.HEARTH_AREA_M2 == 66.15
    assert model.wall_loss_kw == 250.0
    assert model.hearth_loss_ref_kw == 85.0
    assert model.dross_factor_flat == 0.70
    assert model.regen_base_eff == 0.74

    opt = HeatingCurveOptimizer(
        physics_model=model,
        max_gas_flow_dual_pair=p_cfg['max_gas_flow_dual_pair'],
        max_gas_flow_single_pair=p_cfg['max_gas_flow_single_pair'],
        min_gas_flow_nm3h=p_cfg['min_gas_flow_nm3h']
    )
    assert opt.max_gas_flow_dual_pair == 880.0
    assert opt.max_gas_flow_single_pair == 440.0
    assert opt.min_gas_flow_nm3h == 50.0
