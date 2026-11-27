# ops-skills-public

脱密版团队工具集：**只保留方法与骨架，不含任何公司产品名、凭证、数据口径与业务数据。**

这里是 `quyun-ops-2` 组织内部工具库的**公开投影**。内部库保持不动，公开库由人工搬运、逐项脱密后提交。

## 收录内容

| 目录 | 用途 | 拿到后要自己补什么 |
|---|---|---|
| `skills/youtube-csl-pipeline/` | 用浏览器脚本批量传 YouTube、批量建 Google Play 自定义商店页（CSL） | 产品名、标题与描述文案、CSL 模板名 |
| `skills/daily-brief-dingtalk/` | 从数数 TA 拉数，生成日报速览并推钉钉群 | TA 地址与凭证、事件表名、项目号、群机器人 webhook |
| `skills/appstore-cpp/` | App Store 自定义产品页（CPP）建页与 App Preview 上传 | App Store Connect API Key、bundle_id、推广文本 |

每个技能目录下都有 `SKILL.md`，写清了它解决什么问题、需要哪些前置、怎么跑。

## 三条硬规则

1. **不要直接拿去生产用。** 所有产品名都是代号（`SLOT-01`、`BUBBLE-01` 这类），文案是占位。直接开会把别人的文案发出去。
2. **凭证一律自备。** 仓库里没有任何真实 key、token、webhook，示例文件里的值都是占位符。
3. **上传前必须脱密。** 详见 [脱密规范](脱密规范.md)——违反这一条会直接导致内部信息外泄。

## 目录约定

```
skills/<名字>/
├── SKILL.md            做什么 / 何时用 / 怎么用 / 输出什么
├── config/             配置与示例（*example* 文件含占位值）
├── scripts/            可执行脚本
└── references/         方法论、踩坑记录、口径说明
```

## 许可与来源

`youtube-csl-pipeline` 与 `video-outro-trimmer` 的原始思路来自团队实践，部分底座（`watch`、`ffmpeg-skill`）为第三方开源项目，遵循其各自许可。

本仓内容仅提供方法论与骨架，不对任何平台的自动化行为合规性作担保——使用前请自行确认目标平台的服务条款。
