# 升溫曲線對能耗的影響、以及鋁渣生成量的關鍵因子

計算基準：65 噸 5052 合金、6 小時出湯時限、目標湯溫 720°C，操作點取最佳化搜尋結果
（頂溫 1120°C、切換點 2.7h、保溫 880°C、過剩空氣 10%）。方法與 `energy_sensitivity.html`
一致：對每個因子做 ±20% 擾動（決策變數以偏離最佳值衡量），量測結果變化幅度。

## 1. 升溫曲線對能耗的影響：中度顯著，但槓桿集中在「切換時機」

「升溫曲線」由 3 個操作決策變數組成：頂溫設點、切換保溫時機、保溫設點。

| 變數 | 對耗氣量的平均影響幅度 | 在全部 10 個因子中排名 |
|---|---|---|
| **切換保溫時機 (t_switch_hrs)** | **±27.6%** | 第 4（僅次於幾個物理常數） |
| 頂溫設點 (sp_roof_melt) | ±12.9% | 第 7（中等） |
| 保溫設點 (sp_roof_hold) | ±2.6% | 第 10（幾乎無影響） |

**結論**：升溫曲線整體確實顯著，但槓桿完全集中在「何時從 Melt 切到 Hold」——這一項單獨的
影響力就超過空燃比調整（±4.1%）跟保溫溫度設定（±2.6%）加起來。反而是「保溫要設多高」這件事
幾乎不影響耗氣量，因為切換之後湯溫很快貼近目標，誤差回饋機制會自動把頂溫壓低。完整 10 因子
耗氣量排名見 `energy_sensitivity.html`（互動版）與 `REGENERATIVE_SYSTEM_ANALYSIS.md` 第 1 節。

## 2. 鋁渣生成量的關鍵因子

同一操作基準下，重新對燒損（`cum_dross_kg`）跑一次相同方法的敏感度掃描：

| 排名 | 因子 | 類型 | 平均影響幅度 |
|---|---|---|---|
| 1 | 活化能 burnoff_ea | 物理常數（不可操作） | ±134.6% |
| 2 | 爐床面積 HEARTH_AREA_M2 | 物理常數（不可操作） | ±128.0% |
| **3** | **切換保溫時機 t_switch_hrs** | **操作決策** | **±62.5%** |
| 4 | 氧化速率係數 burnoff_k0 | 物理常數（已校正） | ±46.6% |
| **5** | **過剩空氣率 excess_air_pct** | **操作決策** | **±43.2%** |
| 6 | 頂溫設點 sp_roof_melt | 操作決策 | ±21.3% |
| 7 | 保溫設點 sp_roof_hold | 操作決策 | ±3.0% |

基準燒損：663.77 kg（約佔投料 1.021%）。

外加合金種類（類別型，非連續變數，Mg 含量越高燒損越大）：

| 合金 | 燒損 (kg) | 佔投料% |
|---|---|---|
| 99.7（純鋁） | 349.3 | 0.54% |
| 6061 | 444.4 | 0.68% |
| 5052 | 663.8 | 1.02%（基準） |
| 5083 | 801.1 | 1.23% |
| 5182 | 842.0 | 1.30% |

### 兩個重點

1. **操作員真正能控制、且影響最大的是「切換保溫時機」**——不只對耗氣量重要（能耗排名第4），
   對燒損更是決定性因素（可控因子中排第1，±62.5%）。原因在物理模型裡：一旦湯溫到達液相線
   （完全熔化、呈現「平湯面」狀態），氧化速率會直接乘上 **2.5 倍**（`dross_burnoff_rate_kg_hr()`
   的 `is_flat_bath` 機制）。切太晚等於讓爐子在「已經熔化、頂溫還很高」的狀態下多待，同時吃到
   耗氣量跟燒損兩頭的懲罰——這也解釋了為什麼這一個變數在能耗排名（第4）跟燒損排名（可控因子
   第1）都名列前茅。
2. **過剩空氣率對燒損的影響（±43.2%）遠大於對耗氣量的影響（±4.1%，見 `energy_sensitivity.html`）**
   ——這正是手冊裡「過高空氣量會加劇鋁表面氧化」這句話的量化版本：調空燃比對省瓦斯幫助不大，
   但對減少燒損很有感。

### 操作優先順序建議

如果只能調一件事，先調**切換保溫時機**（同時省氣又省渣）；其次是**過剩空氣率**（主要省渣，
對氣的影響很小）；頂溫設點與保溫設點的調整空間相對次要。

## 重現方式

```python
from src.optimizer import HeatingCurveOptimizer
from src.physics_model import MelterPhysicsModel

CHARGE, DURATION, ALLOY, TARGET, DT = 65000.0, 6.0, '5052', 720.0, 5.0
opt = HeatingCurveOptimizer()
res = opt.optimize_heating_curve(CHARGE, DURATION, alloy_name=ALLOY, target_bath_temp_c=TARGET, dt_mins=DT)
p = res['optimal_params']  # 最佳操作點，作為擾動基準

# 例如：測試切換時機對燒損的影響
model = MelterPhysicsModel()
o = HeatingCurveOptimizer(model)
_, s = o.simulate_trajectory(CHARGE, DURATION, p['sp_roof_melt'], t_switch_hrs=1.0,
                              sp_roof_hold=p['sp_roof_hold'], alloy_name=ALLOY,
                              excess_air_pct=p['excess_air_pct'], target_bath_temp_c=TARGET, dt_mins=DT)
print(s['cum_dross_kg'])
```

## 相關文件

- `energy_sensitivity.html` — 能耗排名的互動視覺化（10 因子完整排名與曲線）
- `SENSITIVITY_REPORT.md` — 全部參數的方向性與合理性驗證（含物理常數）
- `REGENERATIVE_SYSTEM_ANALYSIS.md` — 第 1 節為早期以「總成本」為指標的排名（本文件改用
  純耗氣量/純燒損分開計算，數字不同但結論方向一致）
