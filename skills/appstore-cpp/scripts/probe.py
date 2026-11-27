"""纯 Python 解析 mp4/mov 容器信息，不依赖 ffmpeg。

为什么不用 ffprobe：本机没装 ffmpeg，而"能不能上传"这个判断必须**在读素材时**
就能给出，不能等装完工具链。App Preview 的硬要求（时长 15-30s、886x1920 等）
全部可以从容器头里读出来，不需要解码。

用法：
  python probe.py <video>
  python probe.py --dir <目录> --json
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

VIDEO_EXT = {".mp4", ".mov", ".m4v"}


def _boxes(buf: bytes, off: int, end: int):
    while off + 8 <= end:
        size = int.from_bytes(buf[off:off + 4], "big")
        typ = buf[off + 4:off + 8].decode("latin1", "replace")
        hdr = 8
        if size == 1:
            if off + 16 > end:
                break
            size = int.from_bytes(buf[off + 8:off + 16], "big")
            hdr = 16
        elif size == 0:
            size = end - off
        if size < hdr or off + size > end:
            break
        yield typ, off + hdr, off + size
        off += size


def _trak(buf: bytes, start: int, end: int) -> dict:
    info: dict = {}
    for typ, a, b in _boxes(buf, start, end):
        if typ == "tkhd" and b - a >= 8:
            w = int.from_bytes(buf[b - 8:b - 4], "big") / 65536.0
            h = int.from_bytes(buf[b - 4:b], "big") / 65536.0
            info["tkhd"] = (round(w), round(h))
        elif typ == "mdia":
            for t2, a2, b2 in _boxes(buf, a, b):
                if t2 == "mdhd" and b2 - a2 >= 20:
                    ver = buf[a2]
                    if ver == 0:
                        ts = int.from_bytes(buf[a2 + 12:a2 + 16], "big")
                        du = int.from_bytes(buf[a2 + 16:a2 + 20], "big")
                    else:
                        ts = int.from_bytes(buf[a2 + 20:a2 + 24], "big")
                        du = int.from_bytes(buf[a2 + 24:a2 + 32], "big")
                    info["timescale"], info["duration"] = ts, du
                elif t2 == "hdlr" and b2 - a2 >= 12:
                    info["handler"] = buf[a2 + 8:a2 + 12].decode("latin1", "replace")
                elif t2 == "minf":
                    for t3, a3, b3 in _boxes(buf, a2, b2):
                        if t3 != "stbl":
                            continue
                        for t4, a4, b4 in _boxes(buf, a3, b3):
                            if t4 == "stsd" and b4 - a4 >= 16:
                                cnt = int.from_bytes(buf[a4 + 4:a4 + 8], "big")
                                if cnt:
                                    info["codec"] = buf[a4 + 12:a4 + 16].decode("latin1", "replace")
                            elif t4 == "stts" and b4 - a4 >= 8:
                                n = int.from_bytes(buf[a4 + 4:a4 + 8], "big")
                                total = 0
                                for i in range(n):
                                    p = a4 + 8 + i * 8
                                    if p + 8 > b4:
                                        break
                                    total += int.from_bytes(buf[p:p + 4], "big")
                                info["samples"] = total
    return info


def probe(path: str | Path) -> dict:
    p = Path(path)
    buf = p.read_bytes()
    out = {
        "file": str(p),
        "name": p.name,
        "ext": p.suffix.lower(),
        "bytes": len(buf),
        "mb": round(len(buf) / 1048576, 2),
    }
    dur = None
    video = audio = None
    for typ, a, b in _boxes(buf, 0, len(buf)):
        if typ != "moov":
            continue
        for t2, a2, b2 in _boxes(buf, a, b):
            if t2 == "mvhd":
                ver = buf[a2]
                if ver == 0:
                    ts = int.from_bytes(buf[a2 + 12:a2 + 16], "big")
                    du = int.from_bytes(buf[a2 + 16:a2 + 20], "big")
                else:
                    ts = int.from_bytes(buf[a2 + 20:a2 + 24], "big")
                    du = int.from_bytes(buf[a2 + 24:a2 + 32], "big")
                if ts:
                    dur = du / ts
            elif t2 == "trak":
                info = _trak(buf, a2, b2)
                if info.get("handler") == "vide" and video is None:
                    video = info
                elif info.get("handler") == "soun" and audio is None:
                    audio = info

    out["duration_s"] = round(dur, 3) if dur else None
    if video:
        w, h = video.get("tkhd") or (0, 0)
        out["width"], out["height"] = w, h
        out["orientation"] = ("portrait" if h > w else "landscape" if w > h else "square")
        out["codec"] = video.get("codec")
        ts = video.get("timescale")
        du = video.get("duration")
        n = video.get("samples")
        if ts and du and n:
            out["fps"] = round(n / (du / ts), 2)
    out["has_audio"] = audio is not None
    return out


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    as_json = "--json" in args
    args = [a for a in args if a != "--json"]
    if args and args[0] == "--dir":
        root = Path(args[1])
        files = sorted([p for p in root.rglob("*") if p.suffix.lower() in VIDEO_EXT])
        rows = [probe(p) for p in files]
        if as_json:
            print(json.dumps(rows, ensure_ascii=False, indent=2))
        else:
            for r in rows:
                print("%-52s %6.2fMB %6.2fs %sx%s %sfps %s"
                      % (r["name"][:52], r["mb"], r.get("duration_s") or 0,
                         r.get("width"), r.get("height"), r.get("fps"), r.get("codec")))
        return 0
    if not args:
        print("usage: probe.py <video> [--json] | probe.py --dir <目录> [--json]")
        return 2
    r = probe(args[0])
    print(json.dumps(r, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
