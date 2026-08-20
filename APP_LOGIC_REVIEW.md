# app.py 背後計算邏輯審查

## 結論

`app.py` 主要負責 Streamlit UI、參數組裝與結果呈現；核心計算實際位於：

- `src/optimizer.py`
- `src/physics_model.py`

目前模型適合做「方案趨勢比較」，但尚不宜把輸出直接解讀為物理上封閉、可直接下發現場的最佳解。

## 問題清單

### 1. 高優先：Roof temperature 沒有受實際燃氣功率回饋

證據：[`src/optimizer.py:170-205`](src/optimizer.py:170)

目前屋頂溫度只由 setpoint 與固定響應率更新：

- 屋頂溫度會依 setpoint 上升。
- 後續才依輻射/對流熱通量反推所需燃氣流量。
- 即使燃氣流量被最大流量截斷，屋頂仍會照樣朝 setpoint 上升。

影響：燃燒功率、屋頂溫度、熱傳與浴湯升溫沒有形成閉合的動態迴路；高 setpoint 可能看似可達，但實際燃氣功率不足時不應能維持該屋頂溫度。

### 2. 高優先：Sankey 能量平衡的輸入/輸出邊界不一致

證據：[`src/physics_model.py:282-294`](src/physics_model.py:282)

目前同時：

- 將 `q_air_preheat` 列為 chamber input。
- 將尚未經蓄熱床回收的 `q_bed_flue_in` 列為 chamber output。
- 又把 `q_air_preheat` 從 `q_bed_flue_in` 分解出來。

影響：蓄熱回收熱被當成新增輸入，但回收來源又被列為輸出，造成 Sankey 的熱量邊界不是同一個 control volume，`total_chamber_input_gj` 與 `total_chamber_output_gj` 不必然相等。

### 3. 高優先：Overhead 燃氣被加入 Sankey，但沒有對應熱損項

證據：[`src/optimizer.py:454-493`](src/optimizer.py:454)

目前流程是：

1. 計算門開輻射、耐火材重蓄熱、換向吹掃與延長保溫等附加燃氣。
2. 將附加燃氣加到 `cum_gas_nm3`。
3. 使用加總後的燃氣量計算 Sankey。

但 Sankey 沒有加入上述 overhead 對應的熱損 sink。

影響：附加燃氣熱量會被錯誤歸入煙氣或未解釋熱，Sankey 不能代表完整的全週期能量平衡。

### 4. 高優先：時間軸落後一個 timestep

證據：[`src/optimizer.py:142-144`](src/optimizer.py:142)

目前每一輪先把 `t_hr = step * dt_hrs` 寫入時間序列，再執行該 timestep 的升溫與耗氣。因此 `time_hrs = 0` 的 bath temperature 實際上已經包含第一個 timestep 的結果。

影響：

- 熔解時間會提前約 `dt_mins`。
- deadline 判定與 melt rate 可能偏樂觀。
- 圖表上的溫度與燃氣曲線時間標籤與狀態不完全對齊。

### 5. 中高優先：低於 solidus 仍計入 50% 潛熱

證據：[`src/physics_model.py:148-154`](src/physics_model.py:148)

`calculate_theoretical_energy()` 只判斷 target temperature 是否低於 liquidus：

```python
latent_heat = weight_kg * latent_h if target_temp_c >= liquidus else weight_kg * latent_h * 0.5
```

因此即使 target temperature 低於 solidus，仍會加入半份熔解潛熱。

影響：低溫升溫情境的理論能耗被高估。target 位於 solidus 與 liquidus 之間時，也沒有依實際液相比例計算部分熔解。

### 6. 中高優先：最佳化其實是粗粒度離散搜尋

證據：[`src/optimizer.py:353-369`](src/optimizer.py:353)

目前候選值包括：

- 少數固定 roof melt setpoint。
- 只有 5 個第一段切換時間。
- soak setpoint 只有 950/1000/1050°C。
- hold setpoint 只有 750/780°C。
- `t_sw2 = t_sw1 + 1.2`，第二段時間幾乎被硬編碼。
- excess air 只有少數候選值。

影響：輸出應稱為「候選方案集合中的最低成本方案」，不應直接宣稱是連續控制空間中的全域最佳解。

### 7. 中高優先：搜尋階段與最後 deadline 判定的容許誤差不一致

證據：

- 搜尋接受條件：[`src/optimizer.py:384-390`](src/optimizer.py:384)
- 最後輸出判定：[`src/optimizer.py:501`](src/optimizer.py:501)

搜尋階段接受：

```python
final_bath_temp_c >= target_bath_temp_c - 2.0
```

最後 `deadline_met` 卻使用：

```python
final_bath_temp_c >= target_bath_temp_c - 5.0
```

影響：同一方案可能在搜尋階段被接受，但最後的 deadline 狀態定義不同；結果報告的判定基準不一致。

### 8. 中優先：Dross rate 沒有依投料量做質量守恆限制

證據：[`src/physics_model.py:217-225`](src/physics_model.py:217)

目前只限制瞬時燒損速率：

- 使用固定 `MAX_PLAUSIBLE_DROSS_RATE_KG_HR`。
- 沒有依本爐投料量或剩餘金屬量限制累積燒損。
- 最低速率 `max(0.1, rate)` 使任何情境都有非零燒損。

影響：小批量、長時間或參數外插時，累積燒損可能超出本爐可損失的金屬量。

### 9. 中優先：延長保溫 overhead 使用固定燃氣流量

證據：[`src/physics_model.py:376-384`](src/physics_model.py:376)

```python
gas_holding_extended_nm3 = extra_hold_hrs * 60.0
```

影響：延長保溫耗氣沒有使用實際 holding flow、最低火流量或燒嘴狀態；它只是固定常數乘時間，無法反映不同爐況與湯溫。

另外，`app.py` 的預設 target duration 約 6.5 h，而 actual total duration 約 5.87 h：

- [`app.py:475`](app.py:475)
- [`app.py:553`](app.py:553)

因此預設情境下 `extra_hold_hrs` 會被算成 0，與「含等待保溫」的欄位語意不一致。

## app.py 的使用層盲區

證據：[`app.py:698-712`](app.py:698)

輸入變更後不會自動重算，而是顯示警告並保留前次結果，必須再次按計算按鈕。

這是目前的刻意互動設計，不一定是程式錯誤；但若使用者忽略警告，畫面上的結果可能不是目前輸入條件的結果。

## 已完成驗證

- `py_compile`：`app.py`、`src/optimizer.py`、`src/physics_model.py` 通過。
- `tests/test_optimizer.py`：11 tests passed。
- 數值探針確認：
  - target 低於 solidus 時仍會加入 latent heat。
  - Sankey 的 input/output 數值不必然平衡。
  - simulation 的第一筆時間標籤已包含第一個 timestep 的升溫結果。

## 建議 Antigravity 的查修順序

1. 先釐清 Sankey 的 control-volume 邊界，重新定義 primary fuel、oxidation heat、regenerator recovery 與 overhead 的流向。
2. 將 roof temperature 改為受實際燃氣功率與熱損共同決定，建立燃燒功率 → 屋頂/爐膛 → 鋁湯的閉迴路。
3. 修正 timestep 的狀態與時間標籤對齊。
4. 修正固相/兩相區/液相區的 enthalpy 分段計算。
5. 統一 deadline 容許誤差，並在結果中明確標示「離散候選搜尋」而非無條件稱為最佳化。
6. 對 dross 累積量加入本爐金屬量上限與合理的 alloy/operation-specific bound。
7. 將 holding overhead 改為依實際 holding flow 或模擬狀態計算。

## 給後續查修者的判定原則

- 每個修正都應新增一個可重現的 regression test。
- Sankey 修正後必須明確檢查 `input - output` 殘差，並說明允許的數值誤差。
- 不要只用現有校正資料把結果「調回合理數字」；先確認模型結構與能量邊界正確，再重新校正參數。
