# -*- coding: utf-8 -*-
"""每日自动跑：增量回算 TA 序列 → 生成速览 → 推送钉钉。

给 Windows 任务计划程序调用（每天 15:00）。不依赖 WorkBuddy 是否开着。

用法：
  python daily_run.py              # 跑昨天（T-1）
  python daily_run.py --day 1026   # 指定数据日
  python daily_run.py --dry        # 只预览不推送
"""
import argparse
import datetime
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PY = sys.executable
LOG = os.path.join(HERE, 'daily_run.log')

# ★ Windows 任务计划程序的默认控制台编码是 GBK，脚本里的 ✓ 等字符会直接
# UnicodeEncodeError 崩溃（1028 15:00 首次自动跑就死在这里）。强制 UTF-8。
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass


def log(msg):
    line = '[%s] %s' % (datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'), msg)
    print(line, flush=True)
    with open(LOG, 'a', encoding='utf-8') as f:
        f.write(line + '\n')


def run(cmd):
    # 子进程也必须 UTF-8，否则它 print 中文/✓ 时同样会在 GBK 下崩
    env = os.environ.copy()
    env['PYTHONIOENCODING'] = 'utf-8'
    r = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8',
                       errors='replace', env=env)
    if r.returncode != 0:
        log('失败: %s\n%s\n%s' % (' '.join(cmd), r.stdout[-800:], r.stderr[-800:]))
    return r


def resolve_date(arg):
    """`1102` / `2026-11-02` → ISO 日期（旧版把年份月份写死为 2026-10，跨月会取错）。"""
    arg = (arg or '').strip()
    if len(arg) == 10 and arg[4] == '-':
        return datetime.date.fromisoformat(arg).isoformat()
    if len(arg) == 4 and arg.isdigit():
        mm, dd = int(arg[:2]), int(arg[2:])
        today = datetime.date.today()
        for y in (today.year, today.year - 1, today.year + 1):
            try:
                d = datetime.date(y, mm, dd)
            except ValueError:
                continue
            if abs((d - today).days) <= 180:
                return d.isoformat()
    raise SystemExit('无法解析日期参数：%s（用 MMDD 或 YYYY-MM-DD）' % arg)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--day', help='数据日，如 1026；默认昨天')
    ap.add_argument('--dry', action='store_true')
    a = ap.parse_args()

    if a.day:
        D = resolve_date(a.day)
        day = D[5:7] + D[8:10]
    else:
        D = (datetime.date.today() - datetime.timedelta(days=1)).isoformat()
        day = D[5:7] + D[8:10]

    log('=== 开始 %s ===' % D)

    # 1) 增量回算当天（顺便把最近 3 天重拉一遍，吸收数据后补）
    start = (datetime.date.fromisoformat(D) - datetime.timedelta(days=2)).isoformat()
    log('回算 %s ~ %s' % (start, D))
    r = run([PY, os.path.join(HERE, 'ta_backfill.py'), '--start', start, '--end', D])
    if r.returncode != 0:
        log('回算失败，中止')
        return 1
    log(r.stdout.strip().splitlines()[-1] if r.stdout.strip() else '回算完成')

    # 2) 生成并推送（--compact：markdown 消息 + 4 列压缩表；★actionCard 实测更窄，不用）
    cmd = [PY, os.path.join(HERE, 'ta_brief.py'), day, '--compact']
    if a.dry:
        cmd.append('--dry')
    else:
        cmd.append('--push')
    r = run(cmd)
    out = (r.stdout or '').strip()
    log('速览输出:\n' + out[-1200:])
    if '已发送' in out or a.dry:
        log('=== 完成 ===')
        return 0
    log('推送未确认成功')
    return 1


if __name__ == '__main__':
    sys.exit(main())
