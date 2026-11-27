---
name: daily-brief-dingtalk
description: >
  从数数 TA（ThinkingData）直连生成五产品日报速览，并推送钉钉群机器人。
  当用户说「日报速览」「推到钉钉」「发到机器人」「今天/昨天的速览」「自动发」「跑一下日报」，
  或需要一条含 收入/内购/DAU/ARPPU/付费率 + 机台排名 + 资源消耗 的日报简报时使用。
  ★ 与「日报生成」skill 的区别：那个产出 5 份单产品完整报告、需要下载 5 个 zip；
  本 skill 完全不碰 CSV，直接查 TA，只产出 1 条钉钉群消息。用户说「完整日报/单产品监控」时不要用本 skill。
agent_created: true
---

# 五产品日报速览（TA 直连 → 钉钉）

一条命令：查 TA → 算环比/位次 → 生成速览 → 推钉钉群。**不依赖任何 CSV 导出，整个 skill 自成一体，拷到哪都能跑。**

涉及产品：SLOT-01 Android / IOS、SLOT-04(Android)、SLOT-02 Android、SLOT-03 IOS。

## 目录结构

```
daily-brief-dingtalk/
├── SKILL.md
├── references/
│   ├── ta-metrics.md        每个指标取哪个事件/字段（改动前必读）
│   └── dingtalk-push.md     钉钉排版规则与踩过的坑
└── scripts/
    ├── ta_api.py            TA 取数客户端（ae-cli 版，委托 ta-query 的 ta_probe）
    ├── ta_backfill.py       回算序列 → ta_series.json
    ├── ta_brief.py          生成速览（+ 可选推送）
    ├── daily_run.py         一键：回算 + 生成 + 推送
    ├── dingtalk.py          钉钉推送（markdown，webhook 已内置）
    ├── _dingtalk.json       webhook / secret / keyword（可覆盖内置值）
    └── ta_series.json       逐日指标序列（随包附带 45 天历史，可自行回算补齐）
```

## 环境

| 项 | 要求 |
|---|---|
| Python | 3.8+ |
| 依赖 | 无额外依赖（取数走本机 `ae-cli` 子进程，不再需要 requests） |
| 网络 | 能访问 `https://ta.triwingames.com`（经 ae-cli）与钉钉 `oapi.dingtalk.com` |
| 前置 | **本机已装并登录 ae-cli**：`ae-cli auth status --host https://ta.triwingames.com --format json` 返回 `authenticated: true`；未登录先跑 `ae-cli auth login` |
| 工作目录 | **必须在 `scripts/` 下运行**（脚本用相对路径找 `ta_series.json` / `_dingtalk.json`） |

> ⚠️ 2026-11-25 数数系统升级，旧的 token 直连 API（`http://<YOUR_TA_HOST>/querySql`）已失效，取数全部改走 ae-cli。详见 `ta-query` skill 的「ae-cli 迁移要点与坑」。

命令里的 `<python>` 替换成本机 python。下文以 `python` 代指。

## 首次使用

```bash
cd <skill>/scripts
python ta_backfill.py --start 2026-09-14 --end 2026-10-27   # 建全量序列（也可直接用随包附带的）
python ta_brief.py 1027 --compact --dry                     # 预览，不发
```

`--dry` 输出正常后，去掉它就只生成、加 `--push` 才发群。

## 三种用法

**① 全自动（定时任务，默认跑昨天）**
```bash
python daily_run.py
```

**② 指定日期跑全流程（回算 + 推送）**
```bash
python daily_run.py --day 1028
```

**③ 只生成不推送（要先核对数据）**
```bash
python ta_brief.py 1028 --compact
```
**用户说「可以发了」才加 `--push`。** 这条是硬规则——用户明确要求过「我叫你发你才发，我要核对数据」。

其他开关：`--verify` 与包内快照逐项对比（本 skill 不自带快照，找不到会跳过）；`--dry` 预览不发送。

**日期参数**：`1026` 或 `2026-10-26` 都收，年份按「距今最近」自动取，跨月/跨年不用改代码。
（旧版把 `2026-10-` 写死在代码里，11 月起会静默取错日期，已修。）

## 执行流程（daily_run.py 内部）

1. **回算**：`ta_backfill.py --start D-2 --end D`，最近 3 天重拉一遍（吸收 TA 回传补数），合并进 `ta_series.json`
   - 验收：输出 `日期数 N（五产品齐全 N）：首日 ~ 末日`，N 应逐日 +1
2. **生成**：`ta_brief.py <MMDD> --compact`，读序列算 D-1 环比、7 日均、窗口位次；再查 TA 取机台 Top2 与资源
   - 验收：正文含「大盘」两行 + 一张 6 列表 + 5 段产品
3. **推送**：`dingtalk.py` 发 **markdown 消息**（`msgtype=markdown`）
   - 验收：输出 `[OK] 已发送： … （N 字）`

## 指标口径（最容易错，详见 `references/ta-metrics.md`）

| 指标 | 取法 | 精度 |
|---|---|---|
| 内购 | `purchase_check_suc` 的 `SUM(price)`，**不是** `purchase_success` | 五产品 ±0.00% |
| 广告 | `dashboard_country_ad_revenue_sync` 的 `dashboard_ad_revenue` | ±0.01 |
| 总收入 | 内购 + 广告 | ±0.00% |
| DAU | `offLineData ∪ app_open ∪ login` 去重，**三个事件缺一不可** | -0.16%~-0.62% |
| 付费率/ARPPU | 用上面的付费人数与内购算 | ±0.00% |
| 机台 | `spin` 按 `machinename` 分组 `SUM(totalbet)` | 机台名与包内一致 |
| 资源 | `item_consume`/`item_deliver` 且 `itemtype='diamonds'` 的 `SUM(itemcount)` | 与完整日报口径不同（全量 vs 付费），方向一致 |

**窗口位次**：按五产品收入合计在序列内降序排名，必须同时给出窗口起止日期与高低档（`rank<=n/3` 偏高、`<=2n/3` 中等、否则偏低）。

## 排版规则（踩过坑，详见 `references/dingtalk-push.md`）

- **表格前后必须各留一个空行**，否则钉钉把表格并进上一段、显示成 `| 产品 | 收入 |` 原始竖线
- **单元格内换行用 `<br>`**（如 `1,506<br>-18.4% / -13.6%`），实测生效
- **段落内换行用行尾两个空格**，否则相邻两行被合并
- **用 markdown 消息，不要用 actionCard**：实测 markdown 约 745px、actionCard 仅约 350px，卡片反而更窄
- 表格控制在 **6 列内**，超过会被右侧裁切

## 配定时任务（对方机器）

Windows 任务计划，每天 15:00。**两个必须项：注册完把 LogonType 改成 S4U，否则会随机被杀（见故障表第一行）。**

```powershell
$py = "C:\path\to\python.exe"
$sc = "C:\...\daily-brief-dingtalk\scripts\daily_run.py"
$a  = New-ScheduledTaskAction -Execute $py -Argument "`"$sc`"" -WorkingDirectory (Split-Path $sc)
$t  = New-ScheduledTaskTrigger -Daily -At "15:00"
$s  = New-ScheduledTaskSettingsSet -StartWhenAvailable -DontStopIfGoingOnBatteries -AllowStartIfOnBatteries
Register-ScheduledTask -TaskName "DailyReport_DingTalk" -Action $a -Trigger $t -Settings $s -Force

# ★ 必须：改为后台服务型登录，不依赖交互会话
$p = (Get-ScheduledTask -TaskName "DailyReport_DingTalk").Principal
$p.LogonType = 'S4U'
Set-ScheduledTask -TaskName "DailyReport_DingTalk" -Principal $p
```

验证：`Start-ScheduledTask -TaskName "DailyReport_DingTalk"`，约 1.5 分钟后 `LastTaskResult` 应为 **0**。

**不想往群里发一条验证消息时**：另建一个同名 `_Verify` 临时任务、`-Argument` 多加 `--dry`，`Start-ScheduledTask` 跑完看到 `LastResult=0` 再 `Unregister` 掉。
实测（本机 venv python）：全流程 **约 2 分 30 秒**（回算 60s + 生成 90s），`--dry` 不推送。

## 故障速查

| 现象 | 原因 | 处理 |
|---|---|---|
| **`LastTaskResult=3221225786`（0xC000013A）**、日志跑到一半突然没有下文、`Get-Process python*` 无进程 | 任务 `LogonType=Interactive`，锁屏/切换用户/远程断开时**进程被系统直接杀掉**。**这是"看起来失败其实数据已算完"的第二大来源** | 改成 `S4U`（见上一节）。★ 见到 0xC000013A **先查 LogonType 与会话状态，不要查代码** |
| `LastTaskResult=1`、日志写「回算失败」 | 任务计划控制台是 **GBK**，`✓` 等符号编码不了（**数据其实已算完，只是最后打印成功信息时挂**） | 本 skill 已把输出符号改成 `[OK]`/`[WARN]`，且 `daily_run.py` 仍保留 `reconfigure(utf-8)` + `PYTHONIOENCODING=utf-8` 双保险；改代码后**必须在 PowerShell（GBK）里验证**，Bash 里测不出来 |
| `XXX 不在序列里` | 序列还没回算到那天 | `python ta_backfill.py --start … --end …` |
| PowerShell `Get-Content` 读到乱码 | PowerShell 的 `*>` 重定向会按控制台代码页二次解码 | 用 `Read` 直读文件，或 `python` 以 `rb` 读取后按 utf-16 解码；不影响实际推送内容 |
| 表格显示成一堆竖线 | 表格前缺空行 | 见排版规则 |
| 群里收到但只有一半 | 列数超 6、被右裁切 | 减列或改 `--compact` |
| `ModuleNotFoundError: requests` | 依赖没装 | `pip install requests` |
| 钉钉返回 `310000` | 机器人启用了加签/keyword 但没配 | 在 `_dingtalk.json` 补 `secret` 或 `keyword` |
| 群里出现两条一样的日报 | 手动补跑后又触发了定时任务 | 正常，不影响；只推一次时确认 `NextRunTime` 与当前时间不冲突 |

## 已知数据异常（不要当成 bug）

- **83292 / 59689 / 243756 / 310170**：PROD_A_IOS 的四个超高额账号，`istest` 全为 `false`。**规则：判断测试账号只认 `istest`，禁止按单笔恒定/金额异常人工剔除** → 一律保留，但在正文里标注单人占比。
- **827536**：GR 头号大R，在/离场会让 GR 金币单日波动 ±95%。
- 机台榜在这些账号主导时**只能读结构，不能读热度**。

## 敏感信息

`scripts/ta_api.py` **已不含任何 TA 凭证**（改为走 ae-cli 的登录态，token 由 ae-cli 存在系统 secure-store 里）。`scripts/_dingtalk.json` 仍内含群机器人 webhook。
**按用户授权随 skill 分发，请勿外传、勿提交到公开仓库。** 若需换凭证：
- TA：跑 `ae-cli auth login --host https://ta.triwingames.com` 用对应账号登录即可，不再需要 appid/secret
- 钉钉：改 `_dingtalk.json` 的 `webhook`，或设环境变量 `DINGTALK_WEBHOOK`
