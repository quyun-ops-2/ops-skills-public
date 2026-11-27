# -*- coding: utf-8 -*-
"""用 TA 回算历史序列（供速览的环比 / 窗口位次使用），并增量补齐新的一天。

一次 SQL 按日期分组，5 产品 × 2 查询即可覆盖整段窗口。

输出 ta_series.json：
  { "2026-10-26": { "PROD_A_AND": {iap, ad, revenue, dau, payers, pay_rate, arppu}, ... }, ... }

用法：
  python ta_backfill.py                    # 默认回算 2026-09-14 ~ 今天
  python ta_backfill.py --start 2026-09-14 --end 2026-10-26
"""
import argparse
import datetime
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ta_api import TAClient  # noqa: E402

PRODS = [('prod_a_android', 'v_event_<YOUR_TABLE>', 'PROD_A_AND'),
         ('prod_a_ios', 'v_event_<YOUR_TABLE>', 'PROD_A_IOS'),
         ('prod_d_android', 'v_event_<YOUR_TABLE>', 'PROD_D'),
         ('prod-b_android', 'v_event_<YOUR_TABLE>', 'PROD_B'),
         ('prod_c_ios', 'v_event_<YOUR_TABLE>', 'PROD_C')]

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'ta_series.json')

SQL = """SELECT "$part_date" AS d,
  SUM(CASE WHEN "$part_event"='purchase_check_suc' THEN price ELSE 0 END) AS iap,
  COUNT(DISTINCT CASE WHEN "$part_event"='purchase_check_suc' THEN "#account_id" END) AS payers,
  COUNT(DISTINCT CASE WHEN "$part_event" IN ('offLineData','app_open','login') THEN "#account_id" END) AS dau,
  COUNT(DISTINCT CASE WHEN "$part_event"='spin' THEN "#account_id" END) AS spinners,
  SUM(CASE WHEN "$part_event"='spin' THEN spintimes ELSE 0 END) AS spins
FROM {tb} WHERE "$part_date">='{S}' AND "$part_date"<='{E}' AND istest=false
GROUP BY "$part_date" ORDER BY "$part_date" """

SQL_AD = """SELECT "$part_date" AS d, SUM(dashboard_ad_revenue) AS ad,
  SUM(dashboard_ad_impressions) AS imp
FROM {tb} WHERE "$part_date">='{S}' AND "$part_date"<='{E}'
AND "$part_event"='dashboard_country_ad_revenue_sync'
GROUP BY "$part_date" ORDER BY "$part_date" """


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--start', default='2026-09-14')
    ap.add_argument('--end', default=datetime.date.today().isoformat())
    a = ap.parse_args()

    series = {}
    if os.path.exists(OUT):
        series = json.load(open(OUT, encoding='utf-8'))

    for proj, tb, tag in PRODS:
        c = TAClient(proj)
        print('拉取 %s ...' % tag, flush=True)
        rows = c.query(SQL.format(tb=tb, S=a.start, E=a.end), timeout=600)
        ads = {x['d']: (x['ad'] or 0, x['imp'] or 0)
               for x in c.query(SQL_AD.format(tb=tb, S=a.start, E=a.end), timeout=600)}
        n = 0
        for r in rows:
            D = r['d']
            iap = r['iap'] or 0.0
            ad, imp = ads.get(D, (0, 0))
            payers = r['payers'] or 0
            dau = r['dau'] or 0
            series.setdefault(D, {})[tag] = dict(
                iap=round(iap, 2), ad=round(ad, 2), revenue=round(iap + ad, 2),
                dau=int(dau), payers=int(payers),
                pay_rate=round(payers / dau * 100, 2) if dau else None,
                arppu=round(iap / payers, 2) if payers else None,
                spins=int(r['spins'] or 0), spinners=int(r['spinners'] or 0),
                impressions=int(imp),
            )
            n += 1
        print('   %s: %d 天' % (tag, n), flush=True)

    json.dump(series, open(OUT, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    ds = sorted(series)
    full = [d for d in ds if len(series[d]) == len(PRODS)]
    print('')
    print('[OK] %s' % OUT)
    print('  日期数 %d（五产品齐全 %d）：%s ~ %s' % (len(ds), len(full), ds[0], ds[-1]))
    gap = [d for d in ds if len(series[d]) != len(PRODS)]
    if gap:
        print('  [WARN] 不齐全的日期:', gap)


if __name__ == '__main__':
    main()
