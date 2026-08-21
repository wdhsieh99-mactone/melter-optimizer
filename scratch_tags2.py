import pandas as pd, numpy as np
P = r'D:/Users/166215/Dropbox/Working/002-Doing/claude/melter2/mfa_20260707-0714_wide.csv'
df = pd.read_csv(P, usecols=['mfa_ft210_pv','mfa_ft211_pv','mfa_ft213_pv','mfa_ft214_pv',
                             'mfa_ft215_pv','mfa_ft217_pv','mfa_tt201_pv','mfa_pt209_pv'])
print(df.describe(percentiles=[.05,.5,.95]).T.to_string(float_format=lambda x: f'{x:9.1f}'))
gas = df['mfa_ft211_pv'].fillna(0)+df['mfa_ft215_pv'].fillna(0)
air_candidates = {'ft210':df['mfa_ft210_pv'],'ft213':df['mfa_ft213_pv'],
                  'ft214':df['mfa_ft214_pv'],'ft217':df['mfa_ft217_pv']}
act = gas>200
print(f"\nwhen firing (n={act.sum()}): gas mean={gas[act].mean():.0f} Nm3/h")
for k,v in air_candidates.items():
    r = (v[act]/gas[act]).replace([np.inf,-np.inf],np.nan).dropna()
    print(f"  {k}: mean={v[act].mean():8.0f}  ratio/gas median={r.median():6.2f} (stoich air/gas = 9.52)")
comb = (df['mfa_ft210_pv'].fillna(0)+df['mfa_ft214_pv'].fillna(0))[act]/gas[act]
print(f"  ft210+ft214 combined ratio/gas: median={comb.median():.2f}")
print(f"\nfurnace pressure pt209 (Pa): pct of time negative = {(df['mfa_pt209_pv']<0).mean()*100:.1f}%")
print(f"  when firing: mean={df['mfa_pt209_pv'][act].mean():.1f}, p5={df['mfa_pt209_pv'][act].quantile(.05):.1f}, min={df['mfa_pt209_pv'][act].min():.1f}")

# stack sensible loss estimate for one real heat, using measured regenerator exit temp
gas_heat = 4445.7                       # AQ674 integrated
for ea in [0.15, 0.25, 0.40]:
    flue = gas_heat*(10.5+9.52*ea)
    for texit in [130., 200.]:
        print(f"  EA={ea*100:3.0f}%  flue={flue:7.0f} Nm3  stack loss at {texit:.0f}C = {flue*1.32*(texit-25)/1e6:5.1f} GJ"
              f"  ({flue*1.32*(texit-25)/1e6/(gas_heat*40.585/1000)*100:4.1f}% of fuel {gas_heat*40.585/1000:.0f} GJ)")
