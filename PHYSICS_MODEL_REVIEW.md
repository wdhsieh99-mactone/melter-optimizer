# 80T 鋁熔爐最佳化工具 — 物理計算邏輯審查

審查日期：2026-08-20
審查對象：`app.py` 及 `src/physics_model.py`、`src/optimizer.py`、`src/regenerator_model.py`、`src/calibration.py`
審查方法：逐檔讀碼 + 對照 `src/calibrated_constants.json` 實際校正值，非僅讀文件描述

## 結論先行

模型骨架（能量守恆、T⁴輻射、Arrhenius氧化動力學）方向正確，且作者對簡化假設有相當誠實的自我揭露（`calibration.py` 的 caveat、`SENSITIVITY_REPORT.md`）。但有 **4 個會實際扭曲最佳化建議的物理/邏輯盲區**，其中第 1、2 項已用程式碼與 `calibrated_constants.json` 逐行驗證確認存在。

## 主要盲區

| # | 位置 | 問題 | 驗證證據 |
|---|------|------|---------|
| 1 | `physics_model.py:171-176`（動力學）+ `optimizer.py` 目標函數 | **燒損模型誤差量級 ≥ 訊號本身，但決定了成本目標函數的主要項** | `calibrated_constants.json`：Ea=45000 J/mol 是「工程假設，未獨立校正」，只有 k₀ 是自由參數；擬合結果 `dross_mae_pct_points=3.52`。文件記載典型燒損率量級約 1%（`MELTER_KNOWLEDGE.md:305`，雖已過時但量級可信）。換句話說：**±3.5 個百分點的絕對誤差，比要優化的訊號本身還大**。而 `optimizer.py:353` 的頂溫搜尋空間到 1200°C（預設 `max_roof_sp_limit`）/1250°C（可調），遠超校正錨點 1100°C（`calibrated_constants.json` 的 `assumed_replay_policy`）——**Arrhenius 外插到未驗證溫域**，加上平湯 2.5× 二元開關（`physics_model.py`）也是未獨立驗證的經驗值。gas_cost 與 dross_cost 相加成單一 total_cost 去排序方案，等於用一個誤差比訊號還大的量去決定「該不該犧牲燃氣多燒久一點換取少燒損」。 |
| 2 | Sankey (`app.py:67`) vs 前向模擬 (`optimizer.py` `simulate_trajectory`) | **鋁氧化放熱只出現在事後 Sankey 展示，從未回饋進最佳化用的能量平衡** | `grep` `optimizer.py` 全文無 `0.60`/`31.05`/氧化熱項；`q_net` 只有 `q_rad + q_conv - q_hearth`。以 65t charge、典型燒損估算，`q_ox_gj`（=`cum_dross_kg*0.6*31.05/1000`）相對 `q_fuel_gj` 量級可達 **一到兩成**，不是可忽略的小項。更值得注意的推論：`efficiency_scale` 被校正到 **1.235**（`combustion_efficiency()` 基礎公式上限只有 0.65，乘 1.235 意味著再生式燒嘴「有效燃燒效率」被推到 ~68-85%，對鋁熔爐而言偏高）。這個異常偏高的效率倍數，很可能不是燃燒效率真的變好，而是**校正過程用它來偷偷吸收了「氧化放熱沒被建模」這個缺口**——即模型把該算在氧化熱頭上的能量，錯記成了燃燒效率。這代表 `efficiency_scale` 不是純粹的燃燒效率係數，混雜了一個未拆解的能量來源，對外插到不同燒損率的情境（如最佳化建議的低燒損策略）會系統性失真。 |
| 3 | `physics_model.py:230`（`compute_heat_cost`） | **`dross_cost = dross_kg × aluminum_price`：全額鋁價套用在全部撈渣質量上** | 已讀原始碼確認，無回收率折減、無氧化物/金屬比例拆分。實務上撈渣（dross/skim）是氧化物+助熔劑+夾帶金屬的混合物，夾帶金屬可透過壓渣機/回收爐追回 50-70%，真實經濟損失遠低於「整塊渣 × 原鋁市價」。這會系統性把目標函數推向「不計燃氣代價也要壓低燒損」，即讓最佳化結果偏向保守慢升溫策略，但對應的燃氣成本增加是實打實的，換來的渣減損節省卻被高估。 |
| 4 | `physics_model.py:171-176`（`combustion_efficiency`，clamp 順序） | **平湯/保溫段（soak/hold）的燃燒效率被夾在天花板 0.68，決策變數在此區間對效率項無區分度** | 逐行確認 clamp 在乘上 `efficiency_scale` **之後**才做（`eff = (base-penalty)*scale; clamp(eff,0.32,0.68)`），且上下界本身不隨 scale 縮放。用 `efficiency_scale=1.2353` 實算：頂溫 ≤ ~1080°C 時 `eff` 一律撞到 0.68 上限（例：950°C→0.726→夾到0.68；780°C→0.778→夾到0.68）。而 optimizer 的 `sp_roof_soak∈{950,1000,1050}`、`sp_roof_hold∈{750,780}` 候選值**全部落在這個飽和區**——意味著搜尋這兩個決策變數時，燃燒效率這一項完全不隨之變化（僅輻射/對流的 T⁴、ΔT 項還有差異），最佳化在效率通道上其實沒有真正比較這些候選值。 |

## 次要問題（值得注意，非 headline）

- **潛熱處理不一致**：`app.py:73` 的 Sankey 用「液相線以上全潛熱 / 以下半潛熱」二值階梯，`optimizer.py` 的 `energy_to_bath_temp()` 卻用能量對溫度線性內插。同一套系統對同一物理量用兩種模型，對 5xxx 系（Al-Mg 固溶體，無強共晶）誤差尚可接受，但兩者本該一致。
- **對流係數 `h=0.010/0.015`**（`optimizer.py:180`）固定不隨燃燒對數（雙對全火 vs 單對微火，流量差 2 倍）變化，物理上应隨氣體流速/雷諾數變。輻射在千度量級本來就佔主導，此項影響有限，但仍是模型未捕捉的維度。
- **校正是「政策條件式」而非爐體本徵**：`calibrated_constants.json` 的 `meta.assumed_replay_policy` 明說是假設所有 123 爐都執行同一組固定 SP（1100°C/25%過剩空氣/0.9×duration切換）反推出常數。這代表 `efficiency_scale`、`burnoff_k0` 描述的是「爐子在這組固定政策附近的行為」，最佳化去搜尋差異很大的策略（不同切換時機、不同過剩空氣）時，這些常數的外插有效性未經驗證。
- **MAPE 17.55% 未傳遞到 UI 顯示的節省金額**：任何最佳化建議節省若小於基準燃氣成本的 ~18%，其實落在模型雜訊範圍內，但介面呈現的是單點 NT$ 數字，沒有不確定區間。

## 附註：文件與程式碼有落差

`MELTER_KNOWLEDGE.md`（第 297-311 行）記載的部分常數已過時，與目前 `src/physics_model.py` 實際值不符：
- 文件寫 `GAS_LHV=36000`，程式碼實際為 `40585`（`physics_model.py:32`，已對齊 Mechatherm 手冊 9700 kcal/Nm³）
- 文件寫 `HEARTH_AREA_M2=45.0`，程式碼實際為 `66.15`（`physics_model.py:37`，已對齊手冊 10,500×6,300mm）
- 文件寫「無 5083 合金項」，程式碼實際已有 `5083` 條目（`physics_model.py:72`，含 substring 比對涵蓋 5083A/5083L/5083S）

代表程式碼已修正過這幾處，但知識文件沒有同步更新。後續分析時建議以程式碼實際值為準，不要單純參照 `MELTER_KNOWLEDGE.md` 的舊數字。

## 一句話判斷

模型的骨架（熱平衡、輻射、動力學形式）沒錯，但**成本目標函數由一個誤差比訊號還大的燒損項主導、又因為氧化熱只進 Sankey 不進最佳化迴圈而讓 `efficiency_scale` 吸收了一塊未拆解的能量**——這兩點疊加，意味著目前輸出的「最佳加熱曲線」排序，其可信度可能不如介面呈現的精確度所暗示。若要用來真的改變操作策略，第 1、2、3 項建議在信任結論前先解決。
