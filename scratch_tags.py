"""Discriminating check: what are tt111-tt114 physically? Cold-end or bed media?"""
import pandas as pd

P = r'D:/Users/166215/Dropbox/Working/002-Doing/claude/melter2/mfa_20260707-0714_wide.csv'
cols = ['mfa_tt111_pv', 'mfa_tt112_pv', 'mfa_tt113_pv', 'mfa_tt114_pv',
        'mfa_tt200_pv', 'mfa_tt201_pv', 'mfa_ot104_pv', 'mfa_pt209_pv',
        'mfa_ft211_pv', 'mfa_ft215_pv']
df = pd.read_csv(P, usecols=cols)
print(df.describe(percentiles=[0.05, 0.5, 0.95]).T.to_string(float_format=lambda x: f'{x:9.1f}'))

# during ACTIVE firing only (total gas flow > 200 Nm3/h)
gas = df['mfa_ft211_pv'].fillna(0) + df['mfa_ft215_pv'].fillna(0)
act = df[gas > 200]
print(f"\n--- actively firing rows only (n={len(act)} of {len(df)}) ---")
print(act[['mfa_tt111_pv', 'mfa_tt112_pv', 'mfa_tt113_pv', 'mfa_tt114_pv',
           'mfa_tt200_pv', 'mfa_tt201_pv']].describe(percentiles=[0.05, 0.5, 0.95]).T.to_string(float_format=lambda x: f'{x:9.1f}'))
print(f"\ntotal gas flow (ft211+ft215) when firing: max={gas.max():.0f} p95={gas.quantile(0.95):.0f} Nm3/h")
