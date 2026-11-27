---
name: appstore-cpp
description: >
  App Store 自定义产品页（CPP / Custom Product Page）的建页与视频上传流水线：素材体检 →
  规格校验 → 建页计划 → 建 CPP → 上传 App Preview。当用户说「建 CPP」「建自定义产品页」
  「iOS 商店页批量建」「App Preview 上传」「iOS 这边的商店页自动化」时使用。
  ★ 与 youtube-csl-pipeline 的分工：那个只管 Google Play 的 CSL（Android，浏览器脚本）；
  本 skill 只管 iOS，走官方 App Store Connect API。iOS 不需要先传 YouTube —— App Preview
  是直接上传的视频文件，不是链接。
agent_created: true
---

# App Store 自定义产品页（CPP）流水线

**Apple 给了 API，所以这条路比 Play 那边干净**：不用浏览器脚本，不会因为界面改版失效。

```
素材目录 → probe（读容器） → validate（对 Apple 规格） → plan（建页计划）
        → create（建 CPP，复制模板版） → upload（传 App Preview）→ 人工提交审核
```

---

## 与 Play CSL 的对照（别搞混）

| | Google Play CSL | App Store CPP |
|---|---|---|
| 上限 | 50 / 应用 | **35 / 应用** |
| 能改 | 应用名、图标、描述、图形 | 截图、App 预览视频、推广文本(170 字符) |
| 改不了 | — | **App 名、副标题、图标、描述** |
| 落地 | URL 参数 `listing`（自选） | URL 参数 `ppid`（Apple 生成） |
| 审核 | 随发布提交 | **每页单独送审，24-48h** |
| 视频来源 | **YouTube 链接**（public/unlisted） | **直接上传 mp4/mov** |
| 自动化 | 只能浏览器脚本（无 API） | **官方 API** |
| 工具 | skill `youtube-csl-pipeline` | 本 skill |

> 关键推论：**只做 iOS 就不必传 YouTube**。传 YouTube 只为喂 Play CSL 的 Preview Video。

---

## 前提（缺一样都跑不到最后）

1. **App Store Connect API Key**（用户和访问 → 集成 → App Store Connect API）
   `.p8` 私钥文件（只能下一次）+ Key ID + Issuer ID
2. **App 在 Console 里至少有一个 iOS 版本** —— 建 CPP 时要指定一个 `appStoreVersion` 当模板
3. **填 `config/SLOT-01_casino.json`**：`bundle_id`（或 `app_id`）、`promotional_text`（≤170 字符）
4. 视觉素材本身要合规（下表），不然建出来的页没视频

凭证放哪：`config/credentials.json`（照 `credentials.example.json` 改），或环境变量
`ASC_KEY_FILE` / `ASC_KEY_ID` / `ASC_ISSUER_ID`。**别把 .p8 提交进任何仓库。**

---

## App Preview 硬规格（官方，改动前必读）

| 项 | 要求 |
|---|---|
| 时长 | **15 - 30 秒** |
| 大小 | ≤ 500MB |
| 分辨率（是"接受分辨率"，不是设备分辨率） | iPhone **886×1920** 竖 / 1920×886 横（6.9/6.5/6.3/6.1 全用这一个）；iPad 1200×1600 / 1600×1200 |
| 帧率 | ≤ 30fps |
| 编码 | H.264（High Profile，≤ Level 4.0）或 ProRes 422 HQ |
| 音频 | 立体声 AAC 256kbps，44.1/48kHz（可无音轨） |
| 数量 | 每个 localization 最多 3 个 |
| 扩展名 | .mp4 / .mov / .m4v |

> 出处：`developer.apple.com/help/app-store-connect/reference/app-information/app-preview-specifications/`
> 一个高频误解：以为要按设备原生分辨率（2796×1290）出片。**不是**，全用 886×1920。

---

## 用法

```bash
cd <skill>/scripts

python run.py doctor            # 凭证 / 配置 / ffmpeg 自检，有凭证时顺带查 App 和 CPP 数
python run.py plan              # 素材 → 建页计划（离线，不联网）
python run.py validate          # 只看合规判定
python run.py create --dry      # 打印建页请求体，不发送
python run.py create --yes      # 真建
python run.py upload --dry      # 打印上传步骤
python run.py upload --yes      # 真传
```

`--dir` 可临时换素材目录，`--config` 可换产品配置（一个产品一份 json）。

**默认全是 dry-run**，`--yes` 才真发。理由和 CSL 那套一样：CPP 建一个占一个配额（35），
传错了还得走审核才能改。

---

## 各脚本在干什么

| 文件 | 作用 |
|---|---|
| `probe.py` | 纯 Python 解 mp4 容器头，读时长/宽高/帧率/编码/音轨。**不依赖 ffmpeg** |
| `validate.py` | 按上表判定，输出 FAIL/WARN，并生成兜底 ffmpeg 转码命令 |
| `plan.py` | 素材目录 → 建页计划（CPP 名、locale、推广文本、合规状态） |
| `asc.py` | ES256 JWT 签名 + REST 客户端 + 分片上传 |
| `run.py` | 统一入口 |

---

## 比例对不上怎么办（最常踩）

素材几乎是 **9:16**（TikTok/Reels 投放规格），而 App Preview 要 **9:19.5**（886×1920）。

- 等比缩放会得到 886×1575，填不满 → 上下补黑边
- **Apple 要求 preview 展示真实应用内体验**，黑边多了有被拒风险
- **正解：回工程按 886×1920 重出**。`validate.py` 给的 ffmpeg 命令只是没别的办法时的兜底
- 别用「模糊背景补边」蒙，那等于伪造画面

---

## 现在的完成度（诚实版）

| 环节 | 状态 |
|---|---|
| probe / validate / plan | ✅ 已用真实素材跑通 |
| JWT 签名 | ✅ 离线验签通过（ES256，r‖s 64 字节） |
| create（建 CPP） | ⚠ 请求体按 Apple 文档的 inline-create 形态拼，**未用真凭证跑过** |
| upload（传 Preview） | ⚠ `POST /v1/appPreviews` 在文档里已标 deprecated（替代 `appAssetLibraryVideos`），**必须联调一次定** |

第一次联调时：`doctor` 通了之后先跑 `create --yes` 只建一条，把返回原样贴回来再往下走。

---

## 故障速查

| 现象 | 处理 |
|---|---|
| `401` | Issuer ID / Key ID 贴错或带空格；.p8 被换过；本机时间不准（JWT 有 iat/exp） |
| `403` | key 无权限，或这个 App 不在该 key 所属团队 |
| `409` | 同名 CPP 已存在 —— 本 skill 会在建之前跳过 |
| `422` | 字段不合法，看 detail 里的 `pointer` 指到哪个字段 |
| `429` | 限流，等几分钟 |
| 「找不到 previewType=IPHONE_69 的预览集」 | 模板版本里没有这个尺寸的预览位；先用 Console 手工建一个 preview 占位，或换 `preview_type` |
| 传完还是空的 | 少了最后一步 `PATCH uploaded=true`（本 skill 已包含） |
| 建完在 Console 看不到 | CPP 是草稿状态，要在版本页里选择并提交审核 |
