"""按 App Store 官方规格判定一条视频能否直接当 App Preview 上传。

判据全部来自 Apple 官方文档，不猜：
  https://developer.apple.com/help/app-store-connect/reference/app-information/app-preview-specifications/
  · 时长 15-30 秒          · 文件 <= 500MB
  · 接受分辨率（不是设备分辨率）：
      iPhone  886x1920（竖） / 1920x886（横）   ← 6.9/6.5/6.3/6.1 全用这一个
      iPad    1200x1600（竖） / 1600x1200（横）
  · 帧率 <= 30fps
  · H.264（High Profile，<= Level 4.0）或 ProRes 422 HQ
  · 音频：立体声 AAC 256kbps，44.1/48kHz

输出的每条问题都带 level：
  FAIL = Apple 会拒，必须修
  WARN = 可能过但大概率被审/被拒，建议修
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import probe as P  # noqa: E402

LIMIT_MB = 500
MIN_S, MAX_S = 15.0, 30.0
MAX_FPS = 30.0

# 接受分辨率 -> 说明
ACCEPTED = {
    (886, 1920): "iPhone 竖版",
    (1920, 886): "iPhone 横版",
    (1200, 1600): "iPad 竖版",
    (1600, 1200): "iPad 横版",
}
IPHONE = (886, 1920)
IPAD = (1200, 1600)

OK_CODECS = {"avc1": "H.264", "apch": "ProRes 422 HQ"}


def fit_command(src: str, dst: str, target: tuple[int, int] = IPHONE,
                seconds: float = 25.0, start: float = 0.0) -> str:
    """生成 ffmpeg 缩放+补边的命令。

    ★ 为什么默认用 pad 而不是 crop：pad 不丢画面，但会在上下/左右留黑边，
      App Store 审核要求「展示真实应用内体验」，黑边多了有被拒风险。
      比例差得远（比如 9:16 的投放素材 → 9:19.5）时，**正确做法是回工程
      按 886x1920 重出**，ffmpeg 只是没办法时的兜底。
    """
    w, h = target
    vf = ("scale=%d:%d:force_original_aspect_ratio=decrease,"
          "pad=%d:%d:(ow-iw)/2:(oh-ih)/2:black,setsar=1" % (w, h, w, h))
    cmd = [
        "ffmpeg -y",
        '-ss %.3f' % start if start else "",
        '-i "%s"' % src,
        "-t %.2f" % seconds,
        '-vf "%s"' % vf,
        "-r 30",
        "-c:v libx264 -profile:v high -level:v 4.0 -pix_fmt yuv420p",
        "-b:v 11M -maxrate 12M -bufsize 24M",
        "-c:a aac -b:a 256k -ar 48000 -ac 2",
        "-movflags +faststart",
        '"%s"' % dst,
    ]
    return " ".join(x for x in cmd if x)


def validate(path: str | Path, target: tuple[int, int] | None = None) -> dict:
    info = P.probe(path)
    issues: list[dict] = []

    def add(level: str, code: str, msg: str, fix: str = "") -> None:
        issues.append({"level": level, "code": code, "msg": msg, "fix": fix})

    if info["ext"] not in {".mp4", ".mov", ".m4v"}:
        add("FAIL", "ext", "扩展名 %s 不被接受（只要 .mp4/.mov/.m4v）" % info["ext"])
    if info["mb"] > LIMIT_MB:
        add("FAIL", "size", "文件 %.1fMB 超过 %dMB 上限" % (info["mb"], LIMIT_MB))

    d = info.get("duration_s")
    if not d:
        add("FAIL", "duration", "读不出时长，容器可能损坏")
    elif d > MAX_S:
        add("FAIL", "duration", "时长 %.2fs 超过 30s 上限（超 %.2fs）"
            % (d, d - MAX_S), "裁到 25s 左右，别贴着 30s 剪")
    elif d < MIN_S:
        add("FAIL", "duration", "时长 %.2fs 不足 15s" % d)

    res = (info.get("width"), info.get("height"))
    want = target or TARGET_DEFAULT
    if res not in ACCEPTED:
        add("FAIL", "resolution",
            "分辨率 %sx%s 不在 Apple 接受列表里（只接受 886x1920 / 1920x886 / 1200x1600 / 1600x1200）" % res)
    elif target and res != target:
        add("WARN", "resolution",
            "分辨率 %sx%s 可接受，但和你想投的 %dx%d 不一致" % (res[0], res[1], target[0], target[1]))

    fps = info.get("fps") or 0
    if fps > MAX_FPS:
        add("FAIL", "fps", "帧率 %.2ffps 超过 30fps" % fps)

    codec = info.get("codec")
    if codec not in OK_CODECS:
        add("FAIL", "codec", "编码 %s 不被接受（要 H.264 或 ProRes 422 HQ）" % codec)

    if not info.get("has_audio"):
        add("WARN", "audio", "没有音轨。App Preview 允许无音轨，但带声的转化更好")

    # 比例提示：这是最容易白忙一场的地方
    if res[0] and res[1]:
        src_ratio = res[0] / res[1]
        tgt_ratio = want[0] / want[1]
        if abs(src_ratio - tgt_ratio) > 0.01:
            bars = "上下" if src_ratio > tgt_ratio else "左右"
            add("WARN", "aspect",
                "画面比例 %.3f 与目标 %.3f 不符，缩放后会在%s补黑边。"
                "黑边多了会被审核挑" % (src_ratio, tgt_ratio, bars),
                "最稳的做法：回工程按 %dx%d 重出。只能用这条时，跑 fit 命令兜底" % want)

    hard = [i for i in issues if i["level"] == "FAIL"]
    return {
        "file": info["file"],
        "info": info,
        "target": "%dx%d" % want,
        "ok": not hard,
        "issues": issues,
        "fit_command": (fit_command(info["file"], "FITTED_" + info["name"], want)
                        if hard or any(i["code"] == "aspect" for i in issues) else None),
    }


TARGET_DEFAULT = IPHONE


def main(argv: list[str] | None = None) -> int:
    import json
    args = sys.argv[1:] if argv is None else argv
    if not args:
        print("usage: validate.py <video> [--ipad] [--json]")
        return 2
    as_json = "--json" in args
    target = IPAD if "--ipad" in args else IPHONE
    path = [a for a in args if not a.startswith("--")][0]
    r = validate(path, target)
    if as_json:
        print(json.dumps(r, ensure_ascii=False, indent=2))
        return 0 if r["ok"] else 1
    i = r["info"]
    print("=" * 72)
    print("  %s" % i["name"])
    print("  %.2fMB  %.2fs  %sx%s  %.2ffps  %s  目标 %s"
          % (i["mb"], i.get("duration_s") or 0, i.get("width"), i.get("height"),
             i.get("fps") or 0, i.get("codec"), r["target"]))
    print("=" * 72)
    if not r["issues"]:
        print("  [OK] 符合 App Preview 规格，可以直接传")
    for x in r["issues"]:
        print("  [%s] %-10s %s" % (x["level"], x["code"], x["msg"]))
        if x["fix"]:
            print("           -> %s" % x["fix"])
    if r["fit_command"]:
        print("\n  兜底转码命令（需要 ffmpeg）：")
        print("    " + r["fit_command"])
    return 0 if r["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
