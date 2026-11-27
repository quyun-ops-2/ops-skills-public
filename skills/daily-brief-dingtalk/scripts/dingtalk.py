# -*- coding: utf-8 -*-
"""钉钉群机器人推送（速览专用精简版）。

只保留发一条 markdown 消息所需的最小逻辑，可在任意目录独立运行。

配置优先级（后者覆盖前者）：
  内置默认值 < ./_dingtalk.json < 环境变量 DINGTALK_WEBHOOK / DINGTALK_SECRET

★ 内置的 webhook 与「五产品日报」机器人一致（用户授权写入）。
★ 机器人若启用「加签」安全设置，必须在 _dingtalk.json 里补 secret；
  若启用「自定义关键词」，正文必须含该关键词，否则钉钉返回 310000。
"""
import base64
import hashlib
import hmac
import io
import json
import os
import time
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
CFG_PATH = os.path.join(HERE, '_dingtalk.json')

# 五产品日报群机器人（未启用加签，实测 errcode=0）
DEFAULT_WEBHOOK = ('https://oapi.dingtalk.com/robot/send?access_token='
                   '<REDACTED>')
DEFAULT_SECRET = ''


def load_cfg():
    cfg = {'webhook': DEFAULT_WEBHOOK, 'secret': DEFAULT_SECRET, 'keyword': ''}
    if os.path.exists(CFG_PATH):
        try:
            cfg.update(json.load(io.open(CFG_PATH, encoding='utf-8')))
        except Exception as e:
            print('[WARN] _dingtalk.json 读取失败，改用内置配置：%s' % e)
    cfg['webhook'] = os.environ.get('DINGTALK_WEBHOOK') or cfg.get('webhook', '')
    cfg['secret'] = os.environ.get('DINGTALK_SECRET') or cfg.get('secret', '')
    cfg['keyword'] = os.environ.get('DINGTALK_KEYWORD') or cfg.get('keyword', '')
    return cfg


def sign_url(webhook, secret):
    """加签：sign = base64(hmac_sha256(secret, timestamp + '\\n' + secret))"""
    if not secret:
        return webhook
    ts = str(round(time.time() * 1000))
    s = '%s\n%s' % (ts, secret)
    sign = base64.b64encode(
        hmac.new(secret.encode('utf-8'), s.encode('utf-8'), hashlib.sha256).digest()
    ).decode('utf-8')
    sep = '&' if '?' in webhook else '?'
    return '%s%stimestamp=%s&sign=%s' % (webhook, sep, ts, urllib.parse.quote_plus(sign))


def send(webhook, secret, title, text, keyword='', at_all=False, dry=False):
    """发一条 markdown 消息。返回 0 成功、1 失败。"""
    if keyword and keyword not in text:
        text = '%s\n\n%s' % (keyword, text)
    payload = {
        'msgtype': 'markdown',
        'markdown': {'title': title, 'text': text},
        'at': {'isAtAll': bool(at_all)},
    }
    body = json.dumps(payload, ensure_ascii=False).encode('utf-8')

    if dry:
        print('[DRY] %s（%d 字，%d 字节）' % (title, len(text), len(body)))
        print('-' * 70)
        print(text)
        return 0

    req = urllib.request.Request(
        sign_url(webhook, secret), data=body,
        headers={'Content-Type': 'application/json; charset=utf-8'}, method='POST')
    with urllib.request.urlopen(req, timeout=15) as r:
        res = json.loads(r.read().decode('utf-8'))
    if res.get('errcode') != 0:
        print('[FAIL] 发送失败：%s' % res)
        return 1
    print('[OK] 已发送：%s（%d 字）' % (title, len(text)))
    return 0


if __name__ == '__main__':
    c = load_cfg()
    print('webhook:', c['webhook'][:58] + '...')
    print('secret :', '(空，未加签)' if not c['secret'] else c['secret'][:6] + '...')
    print('发送测试：', send(c['webhook'], c['secret'], '连通测试', '通道正常。', dry=True))
