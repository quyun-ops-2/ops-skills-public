# iOS CPP 流水线 · 准备清单

工具位置：`<技能目录>`（即解压后 appstore-cpp 所在的目录，下同）
脚本已用真实素材跑通离线环节（probe / validate / plan / JWT 签名），联网环节等凭证到位后再联调。

---

## 一、先看这条素材的体检结果（结论：不能直接传）

```
S2026081201_WC_01_HX_QSH_720_SLJ.mp4
40.90MB   41.02s   720x1280   25fps   avc1   ← 容器里读出来的
```

对着 App Preview 规格逐条判：

| 规格 | 要求 | 实际 | 判定 |
|---|---|---|---|
| 时长 | 15–30s | **41.02s** | ❌ 超 11 秒 |
| 分辨率 | 886×1920（或 1920×886） | **720×1280** | ❌ 不在接受列表 |
| 帧率 | ≤30fps | 25fps | ✅ |
| 编码 | H.264 | avc1 | ✅ |
| 大小 | ≤500MB | 40.9MB | ✅ |
| 比例 | 9:19.5（0.4615） | **9:16（0.5625）** | ⚠ 缩放后会上下补黑边 |

**两个 FAIL 都可以硬修，但比例那一项修不好**：9:16 缩到 886×1920 只能等比缩到 886×1575，上下补 345px 黑边。Apple 明确要求 preview 展示真实应用内体验，黑边多了有被拒风险。

**正解：回工程按 886×1920 重出一条**。720p 的投放素材本来也不是 App Preview 该用的源。

如果实在只有这条，兜底命令（需要 ffmpeg，本机还没装）：

```
ffmpeg -y -i "S2026081201_WC_01_HX_QSH_720_SLJ.mp4" -t 25.00 \
  -vf "scale=886:1920:force_original_aspect_ratio=decrease,pad=886:1920:(ow-iw)/2:(oh-ih)/2:black,setsar=1" \
  -r 30 -c:v libx264 -profile:v high -level:v 4.0 -pix_fmt yuv420p \
  -b:v 11M -maxrate 12M -bufsize 24M \
  -c:a aac -b:a 256k -ar 48000 -ac 2 -movflags +faststart out.mp4
```

---

## 二、需要准备的 4 样

| # | 东西 | 从哪拿 |
|---|---|---|
| 1 | **API Key 的 .p8 文件** | App Store Connect → 用户和访问 → 集成 → App Store Connect API → 生成密钥。**只能下载一次** |
| 2 | **Key ID**（10 位） | 同上，密钥列表里那一列 |
| 3 | **Issuer ID**（UUID） | 同上，页面顶部 |
| 4 | **bundle_id** | Xcode 里那个，形如 `com.example.app`。或者改用 App 的数字 app_id |

拿到后放这里（照 `credentials.example.json` 改）：

```
<技能目录>\config\credentials.json
```

---

## 三、配置里还有两个空

`config/SLOT-01_casino.json`：

```json
"bundle_id": "",          ← 必填（或改用 "app_id": "")
"promotional_text": ""    ← 必填，≤170 字符
```

`promotional_text` 是这个 CPP 唯一能自定义的文案位（App 名、图标、描述都改不了）。这 170 字符是公开可见的承诺，需由业务方提供准确文案。

---

## 四、联调顺序（拿到凭证之后）

```bash
cd <技能目录>\scripts

# 1. 自检：会顺带查到这个 App 有几个 iOS 版本、已经用了多少个 CPP
python run.py doctor

# 2. 看建页计划（离线）
python run.py plan

# 3. 只建一条，打印请求体
python run.py create --dry

# 4. 真建一条（**先只建一条**）
python run.py create --yes

# 5. 传视频
python run.py upload --yes
```

★ 第 4 步的返回**原样贴给我**。建页请求体是按 Apple 文档的 inline-create 形态拼的，没跑过真机；上传那个接口在文档里已被标记 deprecated（替代是 `appAssetLibraryVideos`）。这两处都需要看着真实响应定一次。

---

## 五、两个预期差异（跟 Play 那套不一样）

**① 不用传 YouTube**
Play CSL 的 Preview Video 只收 YouTube 链接，所以那边必须先上传。**iOS 的 App Preview 是直接上传 mp4 文件**，所以 iOS 素材走这条链路，一步都不碰 YouTube。

**② 每个页面单独审核，24–48 小时**
Play 那边建完随发布走；iOS 是**每建一页就要审一次**。7 款产品 × 多条素材，排期要按「页」算，不能按「批」算。批量建 20 页 = 20 次审核排队。

---

## 六、命令速查

| 命令 | 作用 | 联网 |
|---|---|---|
| `python run.py doctor` | 凭证/配置/App/CPP 数自检 | 有凭证才联网 |
| `python run.py plan` | 素材 → 建页计划 | 否 |
| `python run.py validate` | 只判合规 | 否 |
| `python run.py create --dry` | 打印建页请求体 | 否 |
| `python run.py create --yes` | 真建 CPP | 是 |
| `python run.py upload --dry` | 打印上传步骤 | 否 |
| `python run.py upload --yes` | 真传 Preview | 是 |

`--dir <素材目录>` 换素材，`--config <json>` 换产品。
