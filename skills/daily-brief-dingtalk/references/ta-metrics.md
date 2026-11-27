# TA 指标口径（实测验证，改动前先读这份）

## 五产品映射

| 代号 | 产品 | project | 事件表 |
|---|---|---|---|
| PROD_A_AND | SLOT-01-Android | `prod_a_android` | `v_event_<YOUR_TABLE>` |
| PROD_A_IOS | SLOT-01-iOS | `prod_a_ios` | `v_event_<YOUR_TABLE>` |
| GR | SLOT-04(Android) | `prod_d_android` | `v_event_<YOUR_TABLE>` |
| PROD_B | SLOT-02 Android | `prod-b_android` | `v_event_<YOUR_TABLE>` |
| TW | SLOT-03 iOS | `prod_c_ios` | `v_event_<YOUR_TABLE>` |

客户端：`ta_api.py` 的 `TAClient(project)` → `.query(sql, timeout=240)`。
**该文件里硬编码了 5 个产品的 appid/secret**，属敏感信息，不要复制到会外传的位置。

---

## 内购（★最容易错的地方）

**必须用 `purchase_check_suc`（服务器校验后的事件）**：

```sql
SELECT SUM(price) AS rev, COUNT(DISTINCT "#account_id") AS users
FROM <table> WHERE "$part_event"='purchase_check_suc'
  AND "$part_date"='YYYY-MM-DD' AND istest=false
```

- ❌ **不要用 `purchase_success`**：那是客户端上报，会随机漏单（2026-10-22 PROD_A_IOS 漏 2 笔 = 39.98，缺口表现为 -99.99 / -21.98 这类整笔金额）。曾据此误判「iOS 回传延迟 / 渠道差异」，全部是假象。
- 同义事件 `recharge`、`sdk_purchase_success` 金额相同（同一批订单重复上报），取任一个即可。
- 字段：`itempos`（点位，英文如 `DIAMOND STORE`，需映射成 `DIAMOND_STORE`；`Mission Pass`→`MISSION_RUSH`）、`price`、`orderid`、`istest`。
- **验证结论**：5 产品 × 2026-10-20 **全部差异 0.00**。

**付费人数**：日报的付费率/ARPPU 用的就是 `COUNT(DISTINCT "#account_id")`。
PROD_A_AND 10/20：付费率 1.65% × DAU 1516 = 25 人 = TA 人数；777.52/25 = 31.10 = 报告 ARPPU。
包内 `_iap_users_raw`（39 人）与「活跃付费用户」（61 人）是**另外两种口径**，不是日报用的那个。

---

## 广告收入

```sql
SELECT SUM(dashboard_ad_revenue) AS rev
FROM <table> WHERE "$part_event"='dashboard_country_ad_revenue_sync'
  AND "$part_date"='YYYY-MM-DD'
```

按 国家×广告类型×渠道 拆分，另带 `dashboard_ad_impressions` / `dashboard_ad_ecpm` / `dashboard_ad_channel`。
**验证**：10/26 SUM=307.14 vs 报表 307.15；10/20 313.25 vs 313.32。

❌ **绝对不要用 `dNt20_ad_revenue_ga4`**：那是 GA4 按用户分桶的 D+N~D+20 **累计值**（d1=216、d14=4021），加不出当日实收，差 88 倍。

**总收入 = 内购 + 广告**（609.81 = 302.66 + 307.15，已自洽）。

---

## DAU（★三个事件缺一不可）

```sql
SELECT COUNT(DISTINCT "#account_id") AS dau FROM <table>
WHERE "$part_date"='YYYY-MM-DD' AND istest=false
  AND "$part_event" IN ('offLineData','app_open','login')
```

- **少了 `login` 会系统性偏低 1.5~2.5%**：有一批用户只上报 `login`、不报 `app_open`（后台唤醒/冷启动走不同上报路径）。
- **任何单事件都对不上**：全事件去重 3157、`offLineData` 单算 1497、`login` 去重 1197、`open_view` 1414、`enter_lobby` 1447 —— 目标 1516 大于任何单事件，说明是**多事件并集**。
- 三事件并集后 10/26 五产品误差：PROD_A_AND -0.39% / PROD_A_IOS -0.16% / GR -0.20% / PROD_B -0.62% / TW -0.43%。
- 剩余 <0.6% 推测为「未登录游客」（有游戏行为但无登录/启动上报）。
- `v_user_76` 查 DAU 会报 `-1004`，不可用。

---

## 机台

```sql
SELECT machinename AS m, SUM(totalbet) AS gold,
       COUNT(DISTINCT "#account_id") AS users, SUM(spintimes) AS spins
FROM <table> WHERE "$part_event"='spin' AND "$part_date"='YYYY-MM-DD'
  AND istest=false AND settled=true
GROUP BY machinename ORDER BY gold DESC, machinename ASC LIMIT 2
```
`ORDER BY` 必须加二级 `machinename`，否则并列时每次结果不同（曾出现 `potAward` / `购买buff` 交替）。

---

## 资源消耗

```sql
SELECT
  SUM(CASE WHEN "$part_event"='item_consume' AND itemtype='diamonds' THEN itemcount ELSE 0 END) AS cons,
  SUM(CASE WHEN "$part_event"='item_deliver' AND itemtype='diamonds' THEN itemcount ELSE 0 END) AS grant_
FROM <table> WHERE "$part_date"='YYYY-MM-DD' AND istest=false
```
消耗位置：按 `reason` 分组取 Top2。

⚠️ **口径与完整日报不同**：速览用 **TA 全量**（所有正式用户），日报用包内「付费用户资源监控」。
10/26 PROD_A_AND 全量 130,769 vs 包内 109,845（+19%）；PROD_B 53,414 vs 6,005（**差 8.9 倍**）。
试过「当月付费用户」口径反而偏小 31%，对不上。**方向（净消耗/净发放）一致，绝对值不可混引。**

---

## 7 日均与窗口位次

- **7 日均 = 当日之前 7 天、不含当日**，样本不足 7 天返回 `None`（`avg7()`）。
- 窗口位次：五产品收入合计在 `ta_series.json` 全序列内降序排名。**分母会随序列增长变化**（43 → 44…），历史报告里的「第 N/30」不可与新分母直接对比。
- 高低档：`rank <= n/3` 偏高、`<= 2n/3` 中等、否则偏低。**必须同时给出窗口起止日期**。

---

## 序列维护

`ta_series.json` 结构：`{ "YYYY-MM-DD": { "PROD_A_AND": {revenue, iap, ad, dau, pay_rate, arppu}, ... } }`

`ta_backfill.py --start A --end B` 一次 SQL 按日期分组，每产品 2 条查询，写回整个区间。
**每天跑时默认回算最近 3 天**，吸收 TA 回传补数（TA 侧数据会晚到，比 CSV 导出时点更完整——TW 10/26 广告 TA 比报表多 4.98，就是后续补进来的）。

---

## 已知异常账号（按规则保留，只标注）

| 产品 | 账号 | 表现 |
|---|---|---|
| PROD_A_IOS | 83292 / 59689 / 243756 / 310170 | 超高额、单笔可达 100,000B，`istest` 全 `false` |
| GR | 827536 | 在/离场使 GR 金币单日波动 ±95% |
| PROD_A_AND | 874463 / 925416 | 常占全服 50~70% |

**用户明确规则：判断测试账号只认 `istest` 字段，禁止按「单笔恒定 / 金额异常 / 均值极高」等特征人工剔除。** 报告里只做占比标注。
已证伪的判据：单值 > 2^53｜量守恒｜跨表比值｜集中度 > 90%｜单笔恒定｜level/Import_Tools 超限。
