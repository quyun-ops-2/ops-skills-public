# 钉钉群机器人推送规则（实测）

## 消息类型：用 markdown，不要用 actionCard

同一群里两条消息并排量过宽度：

| 类型 | 消息区宽度 | 结论 |
|---|---|---|
| `markdown` | **约 745px** | ✅ 用这个 |
| `actionCard`（无按钮） | 约 350px | ❌ 更窄 |
| `actionCard`（带 singleTitle/singleURL） | 约 350px | ❌ 一样窄 |

三种 `errcode` 都是 0，所以**发送成功不代表渲染正确**，必须看群里实际效果。
曾误判「卡片更宽」，实际卡片是最窄的。用户给参照的「别人机器人发的宽表」其实就是 **markdown 表格 + 列少（4 列）**。

**宽度是钉钉客户端写死的**，脚本无法调整，唯一能做的是**减少表格列数**（6 列内可完整显示，再多就要横向滑）。

## 三条排版硬规则

### ① 表格前后必须各留一个空行
```python
L.append('')                       # ← 必须有
L.append(md_table(['产品','收入'], rows, aligns))
L.append('')                       # ← 必须有
```
否则钉钉把表格并进上一段，**显示成 `| 产品 | 收入 |` 的原始竖线文本**（踩过两次）。

### ② 单元格内换行用 `<br>`
```
| PROD_A_IOS | 1,506<br>-18.4% / -13.6% | 767<br>-31.7% / -24.9% |
```
实测生效，用于「值 + 双对比」压缩列数。

### ③ 段落内换行用行尾两个空格
```python
L.append('**大盘**：收入 4,382.39（-13.4%）  ')   # 行尾两空格 = Markdown 硬换行
L.append('内购 1,768.25 ｜ 窗口第 31/43（9/14~10/26，偏低）')
```
单 `\n` 会被合并成一段（曾导致 `**1. 产品名**` 和「机台排名」挤在同一行）。

## 定稿版式

```
### 10月26日日报（周一）

**大盘**：收入 4,382.39（-13.4%）
内购 1,768.25 ｜ 窗口第 31/43（9/14~10/26，偏低）

| 产品 | 收入 | 内购 | DAU | ARPPU | 付费率 |
|:---|---:|---:|---:|---:|---:|
| PROD_A_IOS | 1,506<br>-18.4% / -13.6% | 767<br>-31.7% / -24.9% | 1,884<br>+0.7% / -3.5% | 23.26 | 1.75% |

> 收入／内购／DAU 的格内第二行依次为 vs D-1 / vs 7 日均

**1. SLOT-01 IOS**
**机台排名：** Golden Dynasty 577人6,199.1T（Spin +8.0%）、Dancing Drum 128人1,108.6T（Spin -14.6%）
**资源消耗情况：** 消耗585,191（+25.1%）、发放540,737（+42.4%）、净消耗 44,454；购买feature 234,278（+15.9%）、消耗钻石继续pick 165,450（+62.7%）
```

**不写广告**（虽然 收入=内购+广告），用户明确不要。
内购/ARPPU/付费率只出现在表格里，文字段只讲机台与资源。

## 发送接口

`POST <webhook>`，body：
```json
{"msgtype":"markdown","markdown":{"title":"…","text":"…"},"at":{"isAtAll":false}}
```

**安全设置**：用**加签**时有 `timestamp` + `sign`（HMAC-SHA256，密钥作 key、`timestamp\n` 作 msg）；
选**自定义关键词**时正文必须含该词，否则报 `310000`。
当前配置：`scripts/_dingtalk.json` → `{"webhook": "...", "secret": ""}`，**secret 为空 = 该机器人未启用加签**。
webhook 同时内置在 `scripts/dingtalk.py` 的 `DEFAULT_WEBHOOK` 里，`_dingtalk.json` 与同名环境变量都可覆盖它。

该文件仅存本地，不写进 skill、不外传。

**限流**：每机器人每分钟 20 条，超限限流 10 分钟。速览只有 1 条，不会触发。

## 定时任务

```
DailyReport_DingTalk   每天 15:00   python.exe <skill>/scripts/daily_run.py
```

### ★★ 坑一：LogonType 必须改成 S4U（否则随机被杀）

任务默认用 `LogonType=Interactive`，只在**用户交互式登录会话**里运行。
一旦锁屏切换、切换用户、远程桌面断开，**系统会直接杀掉进程**，表现是：

- `LastTaskResult = 3221225786`（`0xC000013A` = `STATUS_CONTROL_C_EXIT`）
- 日志停在中间（常见：回算写完了、生成阶段没有下文）
- `Get-Process python*` 查不到任何进程

**数据其实没问题，是进程被带走。** 修法：

```powershell
$p = (Get-ScheduledTask -TaskName "DailyReport_DingTalk").Principal
$p.LogonType = 'S4U'
Set-ScheduledTask -TaskName "DailyReport_DingTalk" -Principal $p
```

S4U = 服务型登录，不依赖交互会话、不需要保存密码，仍以原用户身份访问网络。
改完用 `Start-ScheduledTask` 手动触发，约 1.5 分钟后 `LastTaskResult` 应为 `0`。

**排查口诀：见到 0xC000013A 先查 LogonType，不要去查代码。**

### ★★ 坑二：GBK 编码

任务计划的控制台默认 `GBK(cp936)`，脚本里任何 `✓`/emoji 都会
`UnicodeEncodeError: 'gbk' codec can't encode character '\u2713'` **直接崩**。
数据其实已经算完，只是最后打印成功信息时挂，所以日志看起来像「回算失败」。

本 skill 已做两层处理：
1. 输出符号全部改成 `[OK]` / `[WARN]`（最根本）
2. `daily_run.py` 仍保留兜底：`sys.stdout.reconfigure(encoding='utf-8')` + 子进程 `PYTHONIOENCODING='utf-8'`

**验证必须在 PowerShell（GBK 控制台）里跑一次 `daily_run.py --dry`**，Bash 里是 UTF-8 环境、测不出这个问题。

## 推送纪律

用户明确要求过「**我叫你发你才发，我要核对数据**」，后来又说「明天你自己发 15:00」恢复自动。
→ **默认：定时任务自动发；任何手动重发/补发前，先只生成正文给用户看，得到「可以发」再加 `--push`。**
