#!/usr/bin/env python3
"""提交前脱密扫描：命中任何一项就返回非 0，请改完再提交。

用法：
    python tools/scan_secrets.py .            # 扫当前目录
    python tools/scan_secrets.py skills/xxx   # 只扫某个技能

不依赖第三方库。
"""
from __future__ import annotations

import os
import re
import sys

RULES = [
    ("凭证", r"oapi\.dingtalk\.com/robot/send\?access_token=[0-9a-fA-F]{16,}",
     "钉钉群机器人 webhook 明文"),
    ("凭证", r"(?i)\b(?:api[_-]?key|app[_-]?secret|client[_-]?secret)\b\s*[:=]\s*['\"][A-Za-z0-9_\-]{16,}",
     "硬编码密钥"),
    ("凭证", r"(?i)Bearer\s+[A-Za-z0-9\-_\.]{20,}", "Bearer token"),
    ("凭证", r"\b[0-9a-f]{64}\b", "64 位十六进制串（疑似 secret）"),
    ("身份", r"[\w.+-]+@(?!github\.com|users\.noreply\.github\.com|example\.)[\w-]+\.[\w.]{2,}",
     "个人邮箱"),
    ("身份", r"(?<!\d)1[3-9]\d{9}(?!\d)", "手机号"),
    ("身份", r"\b0\d{19,20}\b", "钉钉 userId"),
    ("身份", r"\bding[0-9a-f]{20,}\b", "钉钉 corpId"),
    ("身份", r"[A-Za-z]:[\\/]+Users[\\/]+(?!<)[^\\/\s\"'`|)]+", "本机用户目录"),
    ("身份", r"/Users/(?!<)[A-Za-z0-9._-]+/", "macOS 用户目录"),
    ("设施", r"v_event_\d+", "TA 事件表名"),
    ("设施", r"\"project_id\"\s*:\s*\d+", "TA 项目号"),
    ("设施", r"\b(?!127\.|0\.0\.0\.0|10\.|192\.168\.)\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}:(?!80\b|443\b|8080\b)\d{2,5}\b",
     "IP:端口（除 localhost）"),
    ("设施", r"https?://alis?docs\.dingtalk\.com/", "钉钉内部文档链接"),
    ("数据", r"\"(?:revenue|iap|arppu|dau|payers)\"\s*:\s*\d{2,}", "疑似真实业务数值"),
]

SKIP_DIR = {".git", "__pycache__", "node_modules", ".venv", "venv"}
SKIP_EXT = {".png", ".jpg", ".jpeg", ".gif", ".ico", ".zip", ".pdf", ".woff", ".woff2", ".ttf"}
MAX_BYTES = 4 * 1024 * 1024


def ignored(text: str) -> bool:
    """文首 2KB 内含 scan:ignore-file 的跳过（规范/文档类自身举例用）。"""
    return "scan:ignore-file" in text[:2048]


def is_text(path: str) -> bool:
    try:
        with open(path, "rb") as f:
            head = f.read(4096)
    except OSError:
        return False
    if b"\x00" in head:
        return False
    try:
        head.decode("utf-8")
        return True
    except UnicodeDecodeError:
        return False


def main(argv: list[str]) -> int:
    roots = argv or ["."]
    hits = []
    scanned = 0
    for root in roots:
        for base, dirs, files in os.walk(root):
            dirs[:] = [d for d in dirs if d not in SKIP_DIR]
            for name in files:
                path = os.path.join(base, name)
                if os.path.splitext(name)[1].lower() in SKIP_EXT:
                    continue
                try:
                    if os.path.getsize(path) > MAX_BYTES or not is_text(path):
                        continue
                except OSError:
                    continue
                scanned += 1
                with open(path, encoding="utf-8", errors="replace") as f:
                    text = f.read()
                if ignored(text):
                    continue
                for cat, pat, desc in RULES:
                    for m in re.finditer(pat, text):
                        line = text[:m.start()].count("\n") + 1
                        value = m.group(0)
                        if re.fullmatch(r"[0-9a-f]{64}", value) or len(value) > 48:
                            value = value[:10] + "…"
                        hits.append((cat, path, line, desc, value))

    if not hits:
        print("扫描 %d 个文本文件，未发现需要脱密的内容。" % scanned)
        return 0

    print("扫描 %d 个文本文件，发现 %d 处需要处理：\n" % (scanned, len(hits)))
    for cat, path, line, desc, value in hits:
        print("[%s] %s:%d  %s  ->  %s" % (cat, path, line, desc, value))
    print("\n请按《脱密规范》第 2 节的 5 项替换处理后再提交。")
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
