"""把素材目录变成一张「建页计划」：每个视频对应一个 CPP。

设计跟 Play CSL 那套保持一致：**复制模板，只换一个字段**。这边换的是
App Preview 视频 + 推广文本，截图和文案全随模板走。

CPP 名（reference name）规则：
  · 只给内部识别和报表用，玩家看不到
  · 一旦建了就不好改（改名要走 PATCH，报表历史会断），所以按素材名取
  · 长度压在 60 字符内

输出：JSON（给程序）+ 表格（给人看）
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import probe as P  # noqa: E402
import validate as V  # noqa: E402

PROMO_MAX = 170          # 推广文本上限（官方）
NAME_MAX = 60
DISPLAY = {
    "iphone_6_9": (886, 1920),
    "iphone_6_5": (886, 1920),
    "iphone_6_3": (886, 1920),
    "iphone_6_1": (886, 1920),
    "ipad_13": (1200, 1600),
}


def load_config(path: str | Path) -> dict:
    p = Path(path)
    if not p.exists():
        raise SystemExit("找不到配置文件：%s" % p)
    return json.loads(p.read_text(encoding="utf-8"))


def build(cfg: dict, video_dir: str | Path | None = None) -> dict:
    d = Path(video_dir or cfg.get("video_dir") or ".")
    if not d.exists():
        raise SystemExit("素材目录不存在：%s" % d)
    target = DISPLAY.get(cfg.get("target_display", "iphone_6_9"), DISPLAY["iphone_6_9"])
    promo = (cfg.get("promotional_text") or "").strip()

    files = sorted([p for p in d.rglob("*") if p.suffix.lower() in P.VIDEO_EXT])
    items, blocked = [], []
    for f in files:
        v = V.validate(f, target)
        stem = f.stem
        name = (cfg.get("cpp_name_template") or "{stem}").format(stem=stem, product=cfg.get("product", ""))
        entry = {
            "file": str(f),
            "stem": stem,
            "cpp_name": name[:NAME_MAX],
            "locale": cfg.get("locale", "en-US"),
            "promotional_text": promo,
            "promo_len": len(promo),
            "preview_ready": v["ok"],
            "issues": v["issues"],
            "probe": {k: v["info"].get(k) for k in
                      ("duration_s", "width", "height", "fps", "codec", "mb", "has_audio")},
        }
        if not v["ok"]:
            entry["fit_command"] = v.get("fit_command")
            blocked.append(entry)
        items.append(entry)

    warn = []
    if not promo:
        warn.append("promotional_text 还没填（上限 170 字符）—— 建页时会空着")
    elif len(promo) > PROMO_MAX:
        warn.append("promotional_text %d 字符，超过 170 上限" % len(promo))
    if not cfg.get("bundle_id") and not cfg.get("app_id"):
        warn.append("bundle_id / app_id 都没填 —— 无法定位 App")
    if not files:
        warn.append("素材目录里没有 mp4/mov/m4v")

    return {
        "app": {"product": cfg.get("product"), "bundle_id": cfg.get("bundle_id"),
                "app_id": cfg.get("app_id"), "template_version": cfg.get("template_version")},
        "target_display": cfg.get("target_display"),
        "target_px": "%dx%d" % target,
        "count": len(items),
        "ready": len([i for i in items if i["preview_ready"]]),
        "blocked": len(blocked),
        "warnings": warn,
        "items": items,
    }


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if not args:
        print("usage: plan.py <config.json> [--dir <素材目录>] [--json]")
        return 2
    as_json = "--json" in args
    args = [a for a in args if a != "--json"]
    vdir = None
    if "--dir" in args:
        i = args.index("--dir")
        vdir = args[i + 1]
        args = args[:i] + args[i + 2:]
    cfg = load_config(args[0])
    r = build(cfg, vdir)

    if as_json:
        print(json.dumps(r, ensure_ascii=False, indent=2))
        return 0

    print("=" * 78)
    print("  建页计划  %s  目标 %s（%s）" % (r["app"]["product"] or "(未填产品)",
                                          r["target_display"], r["target_px"]))
    print("=" * 78)
    for w in r["warnings"]:
        print("  [WARN] %s" % w)
    print()
    print("  %-46s %-22s %s" % ("素材", "CPP 名", "状态"))
    print("  " + "-" * 74)
    for it in r["items"]:
        st = "可上传" if it["preview_ready"] else "不合规 %d 项" % len(
            [x for x in it["issues"] if x["level"] == "FAIL"])
        print("  %-46s %-22s %s" % (it["stem"][:46], it["cpp_name"][:22], st))
        for x in it["issues"]:
            if x["level"] == "FAIL":
                print("        [FAIL] %s：%s" % (x["code"], x["msg"]))
    print()
    print("  合计 %d 条，可直接上传 %d 条，需先修 %d 条"
          % (r["count"], r["ready"], r["blocked"]))
    if r["blocked"]:
        print("  修法（需 ffmpeg）：")
        for it in r["items"]:
            if it.get("fit_command"):
                print("    " + it["fit_command"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
