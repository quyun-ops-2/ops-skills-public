# -*- coding: utf-8 -*-
"""从 TA 序列（ta_series.json）生成日报速览文本，含 D-1 环比与 7 日均对比。

不依赖任何 CSV。序列由 ta_backfill.py 维护（首次回算 + 每日增量）。

用法：
  python ta_brief.py 1026            # 输出速览
  python ta_brief.py 1026 --push     # 输出并推送到钉钉
  python ta_brief.py 1026 --verify   # 与包内快照逐项对比
"""
import argparse
import datetime
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from ta_api import TAClient  # noqa: E402

SERIES = os.path.join(HERE, 'ta_series.json')
SKILL = HERE  # ★skill 自包含：脚本所在目录
TAGS = ['PROD_A_AND', 'PROD_A_IOS', 'PROD_D', 'PROD_B', 'PROD_C']
NAME = {'PROD_A_AND': 'SLOT-01 Android', 'PROD_A_IOS': 'SLOT-01 IOS',
        'PROD_D': 'SLOT-04(Android)', 'PROD_B': 'SLOT-02 Android',
        'PROD_C': 'SLOT-03 IOS'}
FOLDER = {'PROD_A_AND': 'SLOT-01_Android', 'PROD_A_IOS': 'SLOT-01_IOS', 'PROD_D': 'SLOT-04',
          'PROD_B': 'PROD_B', 'PROD_C': 'TW_IOS'}
PROJ = {'PROD_A_AND': ('prod_a_android', 'v_event_<YOUR_TABLE>'),
        'PROD_A_IOS': ('prod_a_ios', 'v_event_<YOUR_TABLE>'),
        'PROD_D': ('prod_d_android', 'v_event_<YOUR_TABLE>'),
        'PROD_B': ('prod-b_android', 'v_event_<YOUR_TABLE>'),
        'PROD_C': ('prod_c_ios', 'v_event_<YOUR_TABLE>')}

SQL_RES = """SELECT
  SUM(CASE WHEN "$part_event"='item_consume' AND itemtype='diamonds' THEN itemcount ELSE 0 END) AS cons,
  SUM(CASE WHEN "$part_event"='item_deliver' AND itemtype='diamonds' THEN itemcount ELSE 0 END) AS grant_
FROM {tb} WHERE "$part_date"='{D}' AND istest=false"""

SQL_REASON = """SELECT reason, SUM(itemcount) AS v FROM {tb}
WHERE "$part_date"='{D}' AND "$part_event"='item_consume' AND itemtype='diamonds' AND istest=false
GROUP BY reason ORDER BY v DESC, reason ASC LIMIT 3"""

SQL_TOP2 = """SELECT machinename AS m, SUM(totalbet) AS gold,
  COUNT(DISTINCT "#account_id") AS u, SUM(spintimes) AS sp
FROM {tb} WHERE "$part_date"='{D}' AND "$part_event"='spin' AND istest=false AND settled=true
GROUP BY machinename ORDER BY gold DESC, machinename ASC LIMIT 2"""


def resolve_date(arg):
    """把 `1026` / `2026-10-26` 解析成 ISO 日期。

    ★ 旧版把年份写死成 2026-10，跨月（11 月）后会静默取错日期，故改为就近取年。
    """
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
        try:
            return datetime.date(today.year, mm, dd).isoformat()
        except ValueError:
            pass
    sys.exit('无法解析日期参数：%s（用 MMDD 或 YYYY-MM-DD）' % arg)


def load():
    if not os.path.exists(SERIES):
        sys.exit('缺 ta_series.json，先跑: python ta_backfill.py')
    return json.load(open(SERIES, encoding='utf-8'))


def pct(a, b):
    """a 相对 b 的百分比变化，b 为 0/None 时返回 '—'。"""
    if not b:
        return '—'
    return '%+.1f%%' % ((a / b - 1) * 100)


def avg7(S, D, tag, key):
    """当日之前 7 天的均值（不含当日），样本不足 7 天返回 None。"""
    ds = sorted(S)
    i = ds.index(D)
    win = ds[max(0, i - 7):i]
    if len(win) < 7:
        return None
    vals = [S[d][tag][key] for d in win if S[d].get(tag) and S[d][tag].get(key) is not None]
    return sum(vals) / len(vals) if vals else None


def fetch_extra(D, D1):
    """资源（含前两个消耗位置）+ 机台 Top2（含 D-1 Spin），都带 D-1 对照。"""
    out = {}
    for tag in TAGS:
        proj, tb = PROJ[tag]
        c = TAClient(proj)
        r = c.query(SQL_RES.format(tb=tb, D=D), timeout=240)[0]
        r1 = c.query(SQL_RES.format(tb=tb, D=D1), timeout=240)[0] if D1 else None
        cons, grant = r['cons'] or 0, r['grant_'] or 0

        # 前两个消耗位置 + D-1 同 reason
        reasons = []
        rs = c.query(SQL_REASON.format(tb=tb, D=D), timeout=240)
        rs1 = c.query(SQL_REASON.format(tb=tb, D=D1), timeout=240) if D1 else []
        m1 = {x['reason']: (x['v'] or 0) for x in rs1}
        for x in rs[:2]:
            reasons.append((x['reason'], int(x['v'] or 0), m1.get(x['reason'])))

        # 机台 Top2 + D-1 同机台 Spin
        tops = []
        ts = c.query(SQL_TOP2.format(tb=tb, D=D), timeout=240)
        names = [x['m'] for x in ts]
        sp1 = {}
        if D1 and names:
            ms = ','.join("'%s'" % n.replace("'", "''") for n in names)
            q = c.query("""SELECT machinename AS m, SUM(spintimes) AS sp FROM {tb}
WHERE "$part_date"='{D}' AND "$part_event"='spin' AND istest=false AND settled=true
AND machinename IN ({ms}) GROUP BY machinename""".format(tb=tb, D=D1, ms=ms), timeout=240)
            sp1 = {x['m']: x['sp'] for x in q}
        for x in ts:
            tops.append((x['m'], (x['gold'] or 0) / 1e12, x['u'], x['sp'], sp1.get(x['m'])))

        out[tag] = dict(
            cons=int(cons), grant=int(grant), net=int(cons - grant),
            cons1=int(r1['cons'] or 0) if r1 else None,
            grant1=int(r1['grant_'] or 0) if r1 else None,
            reasons=reasons, tops=tops,
        )
    return out


def fmt_gold(t):
    if t is None:
        return '—'
    return '{:,.1f}T'.format(t) if t >= 1 else '{:,.0f}B'.format(t * 1000)


def fmt_res(net):
    if net is None:
        return '—'
    return ('净消耗 %s' % format(net, ',')) if net >= 0 else ('净发放 %s' % format(-net, ','))


def md_table(header, rows, aligns):
    out = ['| ' + ' | '.join(str(h) for h in header) + ' |']
    out.append('|' + '|'.join(':---' if a == 'l' else '---:' for a in aligns) + '|')
    for r in rows:
        out.append('| ' + ' | '.join(str(x) for x in r) + ' |')
    return '\n'.join(out)


def build(D, S, extra=None, compact=False, with_title=True):
    """compact=True 输出 4 列压缩表（格内 <br> 换行）；with_title=False 用于卡片（标题在卡片头上）。"""
    ds = sorted(S)
    if D not in S:
        sys.exit('%s 不在序列里，先跑 ta_backfill 补齐' % D)
    i = ds.index(D)
    prev = ds[i - 1] if i > 0 else None
    cur = S[D]

    tot = sum(cur[t]['revenue'] for t in TAGS)
    iap = sum(cur[t]['iap'] for t in TAGS)
    tot1 = sum(S[prev][t]['revenue'] for t in TAGS) if prev else None
    alltot = sorted((sum(S[d][t]['revenue'] for t in TAGS) for d in ds), reverse=True)
    rank = alltot.index(tot) + 1

    dt = datetime.date.fromisoformat(D)
    wd = '周一周二周三周四周五周六周日'[dt.weekday() * 2:][:2]
    order = sorted(TAGS, key=lambda x: -cur[x]['revenue'])

    L = ['### %d月%d日日报（%s）' % (dt.month, dt.day, wd), ''] if with_title else []
    # 行尾两空格 = Markdown 硬换行，否则钉钉会把相邻两行合并成一段
    L.append('**大盘**：收入 %s（%s）  '
             % (format(tot, ',.2f'), pct(tot, tot1) if tot1 else '—'))
    # 窗口位次：注明窗口起止日期与高低档（前 1/3 偏高、中间中等、后 1/3 偏低）
    d_first = datetime.date.fromisoformat(ds[0])
    d_last = datetime.date.fromisoformat(ds[-1])
    grade = ('偏高' if rank <= len(ds) / 3
             else '中等' if rank <= len(ds) * 2 / 3 else '偏低')
    L.append('内购 %s ｜ 窗口第 %d/%d（%d/%d~%d/%d，%s）'
             % (format(iap, ',.2f'), rank, len(ds),
                d_first.month, d_first.day, d_last.month, d_last.day, grade))
    L.append('')

    if compact:
        # ★4 列压缩版：每格「值<br>vsD-1 / vs7日」，表格前后必须各留一个空行
        def cell(val, pat, key):
            s1 = pat.format(val)
            p1 = pct(val, S[prev][t][key]) if prev else '—'
            return '%s<br>%s / %s' % (s1, p1, pct(val, avg7(S, D, t, key)))

        rows = []
        for t in order:
            v = cur[t]
            rows.append([t,
                         cell(v['revenue'], '{:,.0f}', 'revenue'),
                         cell(v['iap'], '{:,.0f}', 'iap'),
                         cell(v['dau'], '{:,}', 'dau'),
                         '{:,.2f}'.format(v['arppu'] or 0),
                         '%.2f%%' % (v['pay_rate'] or 0)])
        L.append(md_table(['产品', '收入', '内购', 'DAU', 'ARPPU', '付费率'],
                          rows, ['l', 'r', 'r', 'r', 'r', 'r']))
        L.append('')
        L.append('> 收入／内购／DAU 的格内第二行依次为 vs D-1 / vs 7 日均')
        L.append('')
    else:
        # 拆两张窄表：气泡内可完整显示，不用横向滚动
        rows1, rows2 = [], []
        for t in order:
            v = cur[t]
            p = S[prev][t] if prev else None
            rows1.append([
                t,
                '{:,.0f}'.format(v['revenue']),
                pct(v['revenue'], p['revenue']) if p else '—',
                pct(v['revenue'], avg7(S, D, t, 'revenue')),
                '{:,.0f}'.format(v['iap']),
                pct(v['iap'], p['iap']) if p else '—',
                pct(v['iap'], avg7(S, D, t, 'iap')),
            ])
            rows2.append([
                t,
                '{:,}'.format(v['dau']),
                pct(v['dau'], p['dau']) if p else '—',
                pct(v['dau'], avg7(S, D, t, 'dau')),
                '{:,.2f}'.format(v['arppu'] or 0),
                '%.2f%%' % (v['pay_rate'] or 0),
            ])
        L.append(md_table(['产品', '收入', 'D-1', '7日', '内购', 'D-1', '7日'],
                          rows1, ['l'] + ['r'] * 6))
        L.append('')
        L.append(md_table(['产品', 'DAU', 'D-1', '7日', 'ARPPU', '付费率'],
                          rows2, ['l'] + ['r'] * 5))
        L.append('')

    # 每个产品下面拆成「机台排名」与「资源消耗情况」两行
    for t in order:
        L.append('**%d. %s**  ' % (order.index(t) + 1, NAME[t]))
        e = (extra or {}).get(t)
        if not e:
            L.append('**机台排名：** —  ')
            L.append('**资源消耗情况：** —')
            L.append('')
            continue
        if e['tops']:
            parts = ['%s %s人%s（Spin %s）'
                     % (nm, format(u, ','), fmt_gold(gold), pct(sp, sp1))
                     for nm, gold, u, sp, sp1 in e['tops']]
            L.append('**机台排名：** ' + '、'.join(parts) + '  ')
        else:
            L.append('**机台排名：** —  ')
        seg = '消耗%s（%s）、发放%s（%s）、%s' % (
            format(e['cons'], ','), pct(e['cons'], e['cons1']),
            format(e['grant'], ','), pct(e['grant'], e['grant1']),
            fmt_res(e['net']))
        if e['reasons']:
            seg += '；' + '、'.join('%s %s（%s）' % (n, format(v2, ','), pct(v2, v1))
                                   for n, v2, v1 in e['reasons'])
        L.append('**资源消耗情况：** ' + seg)
        L.append('')

    return '%d月%d日日报速览' % (dt.month, dt.day), '\n'.join(L).rstrip()


def verify(D, S):
    snap = None
    for d in sorted(os.listdir(SKILL)):
        if not d.startswith('snapshots_') or 'bak' in d:
            continue
        f = os.path.join(SKILL, d, 'SLOT-01_Android.json')
        if os.path.exists(f) and json.load(open(f, encoding='utf-8')).get('date') == D:
            snap = os.path.join(SKILL, d)
            break
    if not snap:
        print('\n（找不到 %s 的包内快照，跳过对比）' % D)
        return
    print('\n' + '=' * 74)
    print('=== 与包内快照对比（%s）===' % D)
    print('%-5s %-8s %11s %11s %9s' % ('产品', '指标', '包内', 'TA', '误差'))
    print('-' * 50)
    bad = []
    for t in TAGS:
        j = json.load(open(os.path.join(snap, FOLDER[t] + '.json'), encoding='utf-8'))
        v = S[D][t]
        for name, pk, ta in [('总收入', j['core']['revenue']['current'], v['revenue']),
                             ('内购', j['iap']['iap_revenue']['current'], v['iap']),
                             ('DAU', j['core']['dau']['current'], v['dau']),
                             ('ARPPU', j['core']['arppu']['current'], v['arppu'])]:
            if not pk or ta is None:
                continue
            e = (ta - pk) / pk * 100
            print('%-5s %-8s %11.2f %11.2f %+8.2f%%%s'
                  % (t, name, pk, ta, e, '' if abs(e) < 2 else '  <<<'))
            if abs(e) >= 2:
                bad.append((t, name, round(e, 2)))
    print('\n超 2%% 的项:', bad if bad else '无')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('day', help='数据日，如 1026')
    ap.add_argument('--push', action='store_true', help='推送到钉钉')
    ap.add_argument('--verify', action='store_true', help='与包内快照对比')
    ap.add_argument('--dry', action='store_true', help='推送前预览')
    ap.add_argument('--card', action='store_true',
                    help='（已弃用）旧版卡片模式，现等价于 --compact；实测卡片更窄')
    ap.add_argument('--compact', action='store_true',
                    help='4 列压缩表（格内 值<br>对比），配合 markdown 消息使用')
    a = ap.parse_args()

    D = resolve_date(a.day)
    S = load()
    ds = sorted(S)
    D1 = ds[ds.index(D) - 1] if D in ds and ds.index(D) > 0 else None
    print('查询资源与机台…', flush=True)
    extra = fetch_extra(D, D1)
    title, text = build(D, S, extra, compact=(a.card or a.compact),
                        with_title=not a.card)
    print(text)

    if a.verify:
        verify(D, S)

    if a.push:
        import dingtalk
        cfg = dingtalk.load_cfg()
        if not cfg['webhook'] and not a.dry:
            sys.exit('未配置钉钉 webhook：写 _dingtalk.json 或设 DINGTALK_WEBHOOK')
        dingtalk.send(cfg['webhook'], cfg['secret'], title, text,
                      keyword=cfg.get('keyword', ''), dry=a.dry)


if __name__ == '__main__':
    main()
