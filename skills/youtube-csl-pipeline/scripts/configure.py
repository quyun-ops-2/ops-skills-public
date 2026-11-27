#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
configure.py — 把脚本里的「本公司配置」换成接收方的。

用法：
  # ① 先看当前配置是什么（不改任何东西）
  python configure.py

  # ② 换成自己的（会先备份成 .bak，改完自动做语法检查）
  python configure.py --product "MY GAME SLOTS" \
      --title "Welcome to MY GAME SLOTS — spin the reels and win big!" \
      --desc-file my_description.txt \
      --template "默认商品详情"

  # ③ 只预览会改成什么
  python configure.py --product "..." --title "..." --desc-file d.txt --dry-run

  # ④ 改完再确认一遍
  python configure.py

为什么要这个工具，而不是让人手改：
  · `description_template` 是一个**多行数组 + `.join('\\n')`**，
    手改很容易漏掉 `].join('\\n'),` 这一截，改完脚本直接语法错误；
  · 标题里有 emoji（🎰🔥），用记事本另存可能变编码；
  · 五处散在不同行（500 / 531 / 555 / 788 / 504），漏一处不会报错，
    只会**静默用错文案** —— 而文案是发出去收不回的。

  ★ 所以这里做两件手改做不到的事：
    ① 改前备份；② 改后跑 `node --check` 语法检查。
"""

import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
DEFAULT_SCRIPT = HERE.parent / "assets" / "csl-helper.user.js"


def force_utf8_stdio():
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except Exception:
            pass


# ---------------------------------------------------------------------------
# 读取
# ---------------------------------------------------------------------------

def read_str_field(src, key):
    """读 `key: '...'` 这样的单行字符串。找不到返回 None。"""
    m = re.search(r"^\s*%s:\s*'((?:[^'\\]|\\.)*)'" % re.escape(key), src, re.M)
    return m.group(1) if m else None


def read_desc(src):
    """读 description_template 那个数组。返回 (原文片段, 行列表)。"""
    m = re.search(
        r"(\n([ \t]*)description_template:\s*\[)(.*?)(\]\.join\('\\n'\),)",
        src, re.S)
    if not m:
        return None, None
    body = m.group(3)
    lines = re.findall(r"'((?:[^'\\]|\\.)*)'", body)
    return m.group(0), [unesc(l) for l in lines]


def read_array(src, key):
    m = re.search(r"%s:\s*\[(.*?)\]" % re.escape(key), src, re.S)
    if not m:
        return None
    return [unesc(x) for x in re.findall(r"'((?:[^'\\]|\\.)*)'", m.group(1))]


def unesc(s):
    return s.replace("\\'", "'").replace("\\\\", "\\").replace("\\n", "\n")


def esc(s):
    return s.replace("\\", "\\\\").replace("'", "\\'")


# ---------------------------------------------------------------------------
# 展示
# ---------------------------------------------------------------------------

def show(src, script_path):
    ver = read_str_field(src, "@version") or ""
    print("=" * 68)
    print("  当前配置：%s" % script_path)
    print("=" * 68)
    print("  产品名        %s" % (read_str_field(src, "product_name") or "(读不到)"))
    print("  标题模板      %s" % (read_str_field(src, "title_template") or "(读不到)"))
    print("  CSL 模板名    %s" % (read_str_field(src, "template_name") or "(读不到)"))

    desc = read_str_field(src, "description_template")
    _, lines = read_desc(src)
    if lines:
        print("  描述模板      %d 行，共 %d 字" % (len(lines), len("\n".join(lines))))
        for l in lines[:3]:
            print("                  | %s" % (l[:56] if l else "(空行)"))
        if len(lines) > 3:
            print("                  | …… 还有 %d 行" % (len(lines) - 3))
    else:
        print("  描述模板      (读不到)")

    known = read_array(src, "known_products")
    if known:
        print("  已知产品全集  %s" % "、".join(known))

    print()
    print("  ── 判断要不要改 ──")
    product = read_str_field(src, "product_name") or ""
    template = read_str_field(src, "template_name") or ""

    # ★ 分两档，因为这两件事的**可信度不一样**：
    #   · 产品名能确定是"没改" —— `SLOT-02` 明显是上一家的
    #   · 模板名**不能** —— 它可能真的就叫「默认商品详情」（中文界面下很常见），
    #     所以只提示"请确认"。否则真叫这个名字的人每次自检都被喊一遍，
    #     喊到最后他就学会无视所有提醒了 —— 那比不提醒更糟。
    todo, confirm = [], []

    if product.strip().upper() in {
        "SLOT-02", "SLOT-01", "SLOT-04 CASINO", "SLOT-03"
    }:
        todo.append("产品名还是原作者的（%s）—— 改成你自己的" % product)

    if template == "默认商品详情":
        confirm.append(
            "CSL 模板名仍是「默认商品详情」—— 如果你 Console 里确实叫这个名字，忽略即可")

    if not todo:
        print("  ✓ 文案相关配置看起来已经是你自己的了。")
    for t in todo:
        print("  ! %s" % t)
    for c in confirm:
        print("  · %s" % c)

    if todo:
        print()
        print("  改法见 references/配置替换清单.md，或用本工具：")
        print("    python configure.py --product \"...\" --title \"...\" --desc-file d.txt")


# ---------------------------------------------------------------------------
# 写入
# ---------------------------------------------------------------------------

def build_desc_block(lines, indent):
    """构造 `description_template` 的数组体。

    ★ 返回的片段**不含开头的 `[`** —— 调用方的正则分组 1 已经把 `[` 吃进去了，
      这里再带一个就会拼成 `[[`，脚本直接语法错误。
      （第一版就是这么写错的，靠下面的 --dry-run 测出来的。）
    """
    pad = indent + "    "
    items = []
    for l in lines:
        items.append("%s'%s'," % (pad, esc(l)))
    return "\n%s\n%s].join('\\n')," % ("\n".join(items), indent)


def apply_changes(src, args):
    changed = []

    def sub_once(pattern, repl, label, flags=re.M | re.S):
        nonlocal src
        new, n = re.subn(pattern, repl, src, count=1, flags=flags)
        if n == 0:
            raise SystemExit("ERROR: 找不到要替换的 %s —— 脚本版本可能不一样。" % label)
        src = new
        changed.append(label)

    if args.product:
        sub_once(r"^(\s*)product_name:\s*'(?:[^'\\]|\\.)*'",
                 lambda m: "%sproduct_name: '%s'" % (m.group(1), esc(args.product)),
                 "product_name")

    if args.title:
        sub_once(r"^(\s*)title_template:\s*'(?:[^'\\]|\\.)*'",
                 lambda m: "%stitle_template: '%s'" % (m.group(1), esc(args.title)),
                 "title_template")

    if args.template:
        sub_once(r"^(\s*)template_name:\s*'(?:[^'\\]|\\.)*'",
                 lambda m: "%stemplate_name: '%s'" % (m.group(1), esc(args.template)),
                 "template_name")

    if args.desc_file or args.desc:
        if args.desc_file:
            p = Path(args.desc_file).expanduser()
            if not p.exists():
                raise SystemExit("ERROR: 描述文件不存在：%s" % p)
            text = p.read_text(encoding="utf-8")
        else:
            text = args.desc
        lines = text.replace("\r\n", "\n").split("\n")
        while lines and not lines[-1].strip():
            lines.pop()

        m = re.search(r"(\n([ \t]*)description_template:\s*\[).*?(\]\.join\('\\n'\),)",
                      src, re.S)
        if not m:
            raise SystemExit("ERROR: 找不到 description_template 块。")
        indent = m.group(2)
        new_block = m.group(1) + build_desc_block(lines, indent) + m.group(3)[len("].join('\\n'),"):]
        src = src[:m.start()] + new_block + src[m.end():]
        changed.append("description_template（%d 行）" % len(lines))

    if args.known:
        names = [n.strip() for n in args.known.split(",") if n.strip()]
        body = "known_products: [" + ", ".join("'%s'" % esc(n) for n in names) + "]"
        m = re.search(r"known_products:\s*\[.*?\]", src, re.S)
        if not m:
            raise SystemExit("ERROR: 找不到 known_products。")
        src = src[:m.start()] + body + src[m.end():]
        changed.append("known_products（%d 个）" % len(names))

    elif args.product:
        # ★ 只改了产品名、没给 --known 时，**自动**把新产品并进全集。
        #   不做这一步会留一个哑坑：禁忌名单是 `全集 − 当前产品`，
        #   而新产品不在全集里 → 名单里一个都不少，看起来"正常"，
        #   但判据从此永远漏掉当前产品这一项。换产品的人不会想到还要改这里。
        existing = read_array(src, "known_products") or []
        p = args.product.strip()
        if p and p not in existing:
            merged = [p] + [x for x in existing if x != p]
            body = "known_products: [" + ", ".join("'%s'" % esc(n) for n in merged) + "]"
            m = re.search(r"known_products:\s*\[.*?\]", src, re.S)
            if m:
                src = src[:m.start()] + body + src[m.end():]
                changed.append("known_products（自动加入 %s，共 %d 个）" % (p, len(merged)))

    return src, changed


def syntax_check(path):
    node = shutil.which("node")
    if not node:
        print("  · 本机没找到 node，跳过语法检查（不影响使用，但建议自查）")
        return True
    r = subprocess.run([node, "--check", str(path)], capture_output=True, text=True)
    if r.returncode == 0:
        print("  ✓ 语法检查通过")
        return True
    print("  ✕ 语法检查失败：")
    print(r.stderr.strip()[:800])
    return False


ANSWER_KEYS = {
    # 中文（填空模板里用的）
    "产品名": "product", "产品": "product",
    "标题": "title", "视频标题": "title",
    "描述文件": "desc_file", "描述": "desc",
    "模板名": "template", "模板": "template", "csl模板名": "template",
    "已知产品": "known", "已知产品全集": "known",
    # 英文（也认，方便改过模板的人）
    "product": "product", "title": "title",
    "desc": "desc_file", "desc_file": "desc_file", "description": "desc_file",
    "template": "template", "known": "known", "known_products": "known",
}


def parse_answers(path):
    """读 `键 = 值` 形式的填空文件，返回 (字段字典, 文件所在目录)。

    ★ 为什么要有这条路：
      让接收方记四个命令行参数、还要在 Windows 上处理引号和 emoji 转义，
      是白白增加失败面。填一张表就只需要"会打字"。
      而且填完的这张表本身就是一份记录 —— 出问题时能一眼看出当时填了什么。

    ★ 解析刻意**宽松**：`=` 两边空格随意、`#` 开头是注释、空值跳过、
      认不出的键忽略而不是报错。填空的人不该因为多打个空格就跑不起来。
    """
    p = Path(path).expanduser()
    if not p.exists():
        raise SystemExit("ERROR: 找不到填空文件：%s" % p)

    out = {}
    for raw in p.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or line.startswith("//"):
            continue
        if "=" not in line:
            continue
        k, v = line.split("=", 1)
        k = k.strip().lower()
        v = v.strip()
        if not v:
            continue                      # 留空 = 这一项不改
        field = ANSWER_KEYS.get(k)
        if field:
            out[field] = v

    return out, p.resolve().parent


def main():
    force_utf8_stdio()

    ap = argparse.ArgumentParser(description="把 CSL Helper 的配置换成你自己的")
    ap.add_argument("--answers", help="读填空文件（`键 = 值` 形式，见 要填的信息.txt）")
    ap.add_argument("--script", default=str(DEFAULT_SCRIPT), help="要改的 user.js")
    ap.add_argument("--product", help="产品名（用于文案哨兵判据）")
    ap.add_argument("--title", help="视频标题模板（{name} = 文件名去后缀）")
    ap.add_argument("--desc-file", help="描述文件（txt，每行一句，空行保留）")
    ap.add_argument("--desc", help="直接给描述（短描述用）")
    ap.add_argument("--template", help="Play Console 里的 CSL 模板名（必须完全一致）")
    ap.add_argument("--known", help="已知产品全集，逗号分隔（用于算禁忌名单）")
    ap.add_argument("--dry-run", action="store_true", help="只预览，不写文件")
    args = ap.parse_args()

    # ★ 填空文件只补「命令行没给过」的项 —— 命令行优先。
    #   这样"大部分填表 + 临时覆盖某一项"也能用。
    if args.answers:
        ans, ans_dir = parse_answers(args.answers)
        for field, value in ans.items():
            if not getattr(args, field, None):
                setattr(args, field, value)
        # 描述文件的相对路径按**填空文件所在目录**算，不是按当前工作目录 ——
        # 对方把 desc.txt 和填好的表放一起就行，不用管自己 cd 在哪。
        if args.desc_file:
            df = Path(args.desc_file).expanduser()
            if not df.is_absolute():
                args.desc_file = str(ans_dir / df)
        if ans:
            print("  已从填空文件读到 %d 项：%s"
                  % (len(ans), "、".join(sorted(ans.keys()))))

    script_path = Path(args.script).expanduser().resolve()
    if not script_path.exists():
        raise SystemExit("ERROR: 脚本不存在：%s" % script_path)

    src = script_path.read_text(encoding="utf-8")

    # 没有任何修改参数 → 只显示
    if not any([args.product, args.title, args.template, args.desc_file, args.desc, args.known]):
        show(src, script_path)
        return 0

    print("=" * 68)
    print("  %s配置：%s" % ("预览" if args.dry_run else "修改", script_path.name))
    print("=" * 68)

    new_src, changed = apply_changes(src, args)

    print("  会改这些：")
    for c in changed:
        print("    · %s" % c)
    print()
    print("  ── 改后 ──")
    print("  产品名        %s" % (read_str_field(new_src, "product_name") or "(未变)"))
    print("  标题模板      %s" % (read_str_field(new_src, "title_template") or "(未变)"))
    print("  CSL 模板名    %s" % (read_str_field(new_src, "template_name") or "(未变)"))
    _, lines = read_desc(new_src)
    if lines:
        print("  描述模板      %d 行，%d 字" % (len(lines), len("\n".join(lines))))
    print()

    if args.dry_run:
        print("  [dry-run] 没有写文件。去掉 --dry-run 才会真正保存。")
        return 0

    backup = script_path.with_suffix(script_path.suffix + ".bak")
    shutil.copy2(script_path, backup)
    print("  已备份      %s" % backup.name)

    script_path.write_text(new_src, encoding="utf-8")
    print("  已写入      %s" % script_path)

    if not syntax_check(script_path):
        print()
        print("  ✕ 语法检查没过 —— 已用备份还原。")
        shutil.copy2(backup, script_path)
        return 1

    print()
    print("  下一步：把改好的 csl-helper.user.js 全文粘进 Tampermonkey，Ctrl+S 保存。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
