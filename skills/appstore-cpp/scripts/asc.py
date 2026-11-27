"""App Store Connect API 客户端：ES256 JWT 签名 + REST 调用 + 分片上传。

凭证三件套（在 App Store Connect → 用户和访问 → 集成 → App Store Connect API 里创建）：
  · .p8 私钥文件（只给一次，丢了只能重建）
  · Key ID（10 位）
  · Issuer ID（UUID，账号级，不是 key 级）

优先级：命令行参数 < 环境变量 < config/credentials.json
  ASC_KEY_FILE / ASC_KEY_ID / ASC_ISSUER_ID

★ JWT 有效期上限 20 分钟，这里默认 15 分钟并做缓存复用；
  同一个 token 反复用是官方推荐做法，别每个请求都签一次。
"""
from __future__ import annotations

import base64
import json
import os
import time
from pathlib import Path

import requests
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
CRED = ROOT / "config" / "credentials.json"
BASE = "https://api.appstoreconnect.apple.com"
AUD = "appstoreconnect-v1"


def _b64u(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def load_creds(key_file: str | None = None, key_id: str | None = None,
               issuer_id: str | None = None) -> dict:
    c = {}
    if CRED.exists():
        try:
            c = json.loads(CRED.read_text(encoding="utf-8"))
        except Exception as e:                       # noqa: BLE001
            raise SystemExit("credentials.json 读不出来：%s" % e)
    c["key_file"] = key_file or os.environ.get("ASC_KEY_FILE") or c.get("key_file") or ""
    c["key_id"] = key_id or os.environ.get("ASC_KEY_ID") or c.get("key_id") or ""
    c["issuer_id"] = issuer_id or os.environ.get("ASC_ISSUER_ID") or c.get("issuer_id") or ""
    return c


def make_jwt(key_file: str, key_id: str, issuer_id: str, ttl: int = 900) -> str:
    """签一个 ES256 JWT。ttl 不能超过 1200 秒。"""
    p = Path(key_file).expanduser()
    if not p.exists():
        raise SystemExit("找不到 .p8 私钥：%s" % p)
    key = serialization.load_pem_private_key(p.read_bytes(), password=None)
    if not isinstance(key, ec.EllipticCurvePrivateKey):
        raise SystemExit("这个私钥不是 EC 密钥（App Store Connect 要求 ES256/P-256）")
    header = {"alg": "ES256", "kid": key_id, "typ": "JWT"}
    now = int(time.time())
    payload = {"iss": issuer_id, "iat": now, "exp": now + min(ttl, 1200), "aud": AUD}
    signing = "%s.%s" % (
        _b64u(json.dumps(header, separators=(",", ":")).encode()),
        _b64u(json.dumps(payload, separators=(",", ":")).encode()))
    der = key.sign(signing.encode(), ec.ECDSA(hashes.SHA256()))
    r, s = decode_dss_signature(der)
    # ★ JWS 要求 r||s 定长 32 字节，而 ECDSA 签名是 DER 编码 —— 这里必须手动转，
    #   少这一步会得到一个"看起来像 JWT"但 Apple 一律 401 的串。
    raw = r.to_bytes(32, "big") + s.to_bytes(32, "big")
    return "%s.%s" % (signing, _b64u(raw))


class ASC:
    def __init__(self, creds: dict | None = None, verbose: bool = True):
        self.c = creds or load_creds()
        missing = [k for k in ("key_file", "key_id", "issuer_id") if not self.c.get(k)]
        if missing:
            raise SystemExit("缺少凭证：%s（见 config/credentials.example.json）" % ", ".join(missing))
        self.verbose = verbose
        self._tok = None
        self._tok_at = 0
        self.session = requests.Session()

    def token(self) -> str:
        if not self._tok or time.time() - self._tok_at > 780:
            self._tok = make_jwt(self.c["key_file"], self.c["key_id"], self.c["issuer_id"])
            self._tok_at = time.time()
        return self._tok

    def request(self, method: str, path: str, params: dict | None = None,
                body: dict | None = None, raw_url: str | None = None,
                headers: dict | None = None, data: bytes | None = None,
                timeout: int = 60) -> dict:
        url = raw_url or (BASE + path)
        h = {"Authorization": "Bearer " + self.token()}
        if raw_url is None:
            h["Content-Type"] = "application/json"
        if headers:
            h.update(headers)
        payload = None
        if body is not None:
            payload = json.dumps(body, ensure_ascii=False).encode()
        r = self.session.request(method, url, params=params, data=data or payload,
                                 headers=h, timeout=timeout)
        if r.status_code >= 400:
            detail = r.text[:900]
            raise ASCError(method, url, r.status_code, detail)
        if not r.text.strip():
            return {}
        try:
            return r.json()
        except ValueError:
            return {"raw": r.text}

    def get(self, path, **kw):
        return self.request("GET", path, **kw)

    def post(self, path, body, **kw):
        return self.request("POST", path, body=body, **kw)

    def patch(self, path, body, **kw):
        return self.request("PATCH", path, body=body, **kw)

    # ---- 常用查询 -------------------------------------------------------
    def app_by_bundle(self, bundle_id: str) -> dict | None:
        r = self.get("/v1/apps", params={"filter[bundleId]": bundle_id, "limit": 1})
        data = r.get("data") or []
        return data[0] if data else None

    def ios_versions(self, app_id: str) -> list[dict]:
        r = self.get("/v1/apps/%s/appStoreVersions" % app_id,
                     params={"filter[platform]": "IOS", "limit": 20,
                             "fields[appStoreVersions]": "versionString,platform,appStoreState,createdDate"})
        return r.get("data") or []

    def cpp_list(self, app_id: str) -> list[dict]:
        r = self.get("/v1/apps/%s/appCustomProductPages" % app_id,
                     params={"limit": 200, "fields[appCustomProductPages]": "name,url,visible"})
        return r.get("data") or []

    def cpp_versions(self, cpp_id: str) -> list[dict]:
        r = self.get("/v1/appCustomProductPages/%s/appCustomProductPageVersions" % cpp_id,
                     params={"limit": 50})
        return r.get("data") or []

    def cpp_localizations(self, version_id: str) -> list[dict]:
        r = self.get("/v1/appCustomProductPageVersions/%s/appCustomProductPageLocalizations"
                     % version_id, params={"limit": 50})
        return r.get("data") or []

    # ---- 分片上传（截图/预览视频通用）----------------------------------
    def upload_operations(self, ops: list[dict], blob: bytes, verbose: bool = True) -> int:
        """按 uploadOperations 逐片 PUT。返回成功的片数。"""
        ok = 0
        for i, op in enumerate(ops):
            method = op.get("method", "PUT")
            url = op.get("url")
            off = int(op.get("offset", 0))
            length = int(op.get("length", 0))
            chunk = blob[off:off + length]
            hdrs = {h["name"]: h["value"] for h in op.get("requestHeaders", [])}
            r = requests.request(method, url, data=chunk, headers=hdrs, timeout=300)
            if r.status_code >= 400:
                raise ASCError(method, url.split("?")[0], r.status_code, r.text[:400])
            ok += 1
            if verbose:
                print("    片 %d/%d  %.1fMB  ok" % (i + 1, len(ops), len(chunk) / 1048576))
        return ok


class ASCError(RuntimeError):
    def __init__(self, method: str, url: str, code: int, detail: str):
        self.code, self.detail = code, detail
        super().__init__("%s %s -> HTTP %s\n%s" % (method, url[:120], code, detail))


def explain_http(code: int, detail: str) -> str:
    """把常见错误翻成能动手的话。"""
    if code == 401:
        return ("401：JWT 被拒。三个高频原因 —— ①Issuer ID/Key ID 填错或贴了空格 "
                "②.p8 是重新生成的旧 key ③本机时间不准（JWT 有 iat/exp）")
    if code == 403:
        return "403：这个 key 没有对应权限，或该 App 不在 key 所属团队下"
    if code == 409:
        return "409：冲突，通常同名 CPP 已存在"
    if code == 422:
        return "422：字段不合法，看 detail 里的 pointer"
    if code == 429:
        return "429：限流，等一会儿再跑"
    return "HTTP %d" % code
