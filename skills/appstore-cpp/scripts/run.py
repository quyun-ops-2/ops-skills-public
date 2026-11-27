"""App Store 自定义产品页（CPP）流水线 —— 统一入口。

子命令：
  doctor    凭证 / 依赖 / 配置自检（读得到凭证时会顺带查 App 和现有 CPP 数）
  plan      素材 → 建页计划（不联网）
  create    建 CPP（**默认只打印请求体，不发送**；加 --yes 才真建）
  upload    上传 App Preview 视频（同样默认只打印计划，--yes 才真传）
  all       create + upload

★ 默认 dry-run 不是保守，是因为 CSL 那套的教训：配额和审核都不可回收。
  建一个 CPP 就占一个（上限 35），传错了还得走审核才能改。
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))

import asc  # noqa: E402
import plan as PL  # noqa: E402
import probe as P  # noqa: E402
import validate as V  # noqa: E402

DEFAULT_CFG = ROOT / "config" / "SLOT-01_casino.json"


def _cfg(path: str | None) -> dict:
    return PL.load_config(path or DEFAULT_CFG)


# ---------------------------------------------------------------- doctor
def cmd_doctor(a) -> int:
    print("=" * 74)
    print("  appstore-cpp 环境自检")
    print("=" * 74)
    ok = True

    creds = asc.load_creds(a.key_file, a.key_id, a.issuer_id)
    for key, label in (("key_file", ".p8 私钥"), ("key_id", "Key ID"), ("issuer_id", "Issuer ID")):
        v = creds.get(key) or ""
        if not v:
            print("  [FAIL] %-12s 未配置" % label)
            ok = False
        elif key == "key_file":
            p = Path(v).expanduser()
            print("  [%s] %-12s %s" % ("OK  " if p.exists() else "FAIL", label, v))
            ok = ok and p.exists()
        else:
            print("  [OK  ] %-12s %s" % (label, v[:8] + "..." if key == "issuer_id" else v))

    if creds.get("key_file") and Path(creds["key_file"]).expanduser().exists():
        try:
            t = asc.make_jwt(creds["key_file"], creds["key_id"], creds["issuer_id"])
            print("  [OK  ] %-12s 签名成功（%d 字符）" % ("JWT", len(t)))
        except SystemExit as e:
            print("  [FAIL] %-12s %s" % ("JWT", e))
            ok = False

    cfg = _cfg(a.config)
    for key, label in (("bundle_id", "bundle_id"), ("app_id", "app_id")):
        print("  [%s] %-12s %s" % ("OK  " if cfg.get(key) else "WARN", label, cfg.get(key) or "未填"))
    print("  [%s] %-12s %s" % ("OK  " if cfg.get("promotional_text") else "WARN",
                               "推广文本", "%d 字符" % len(cfg.get("promotional_text") or "")))
    ff = shutil.which("ffmpeg")
    print("  [%s] %-12s %s" % ("OK  " if ff else "WARN", "ffmpeg", ff or "未安装（只有转码需要）"))

    if ok and (cfg.get("bundle_id") or cfg.get("app_id")):
        try:
            c = asc.ASC(creds)
            app = ({"id": cfg["app_id"]} if cfg.get("app_id")
                   else c.app_by_bundle(cfg["bundle_id"]))
            if not app:
                print("  [FAIL] 找不到这个 App（bundle_id 写错？或 key 无权限）")
                return 1
            aid = app["id"]
            vers = c.ios_versions(aid)
            cpps = c.cpp_list(aid)
            print("  [OK  ] %-12s id=%s  IOS 版本 %d 个  现有 CPP %d/35"
                  % ("App", aid, len(vers), len(cpps)))
            for v in vers[:3]:
                at = v.get("attributes", {})
                print("         版本 %s  %s" % (at.get("versionString"), at.get("appStoreState")))
        except asc.ASCError as e:
            print("  [FAIL] 线上查询失败：%s" % asc.explain_http(e.code, e.detail))
            print("         %s" % e.detail[:300])
            return 1
    print()
    print("  结论：%s" % ("可以继续" if ok else "先把上面 FAIL 项补齐"))
    return 0 if ok else 1


# ---------------------------------------------------------------- plan
def cmd_plan(a) -> int:
    cfg = _cfg(a.config)
    r = PL.build(cfg, a.dir)
    if a.json:
        print(json.dumps(r, ensure_ascii=False, indent=2))
        return 0
    print("=" * 78)
    print("  建页计划  %s" % (r["app"]["product"] or "(未填产品)"))
    print("  目标 %s（%s）  素材 %d 条  可上传 %d  需修 %d"
          % (r["target_display"], r["target_px"], r["count"], r["ready"], r["blocked"]))
    print("=" * 78)
    for w in r["warnings"]:
        print("  [WARN] %s" % w)
    print()
    for it in r["items"]:
        mark = "OK  " if it["preview_ready"] else "FAIL"
        print("  [%s] %s" % (mark, it["stem"]))
        print("         CPP 名 %s | %s | %.2fs %sx%s %.0ffps %s"
              % (it["cpp_name"], it["locale"], it["probe"]["duration_s"] or 0,
                 it["probe"]["width"], it["probe"]["height"],
                 it["probe"]["fps"] or 0, it["probe"]["codec"]))
        for x in it["issues"]:
            print("         [%s] %s：%s" % (x["level"], x["code"], x["msg"]))
        if it.get("fit_command"):
            print("         修：%s" % it["fit_command"])
    return 0


# ---------------------------------------------------------------- create
def _cpp_body(app_id: str, ver_id: str, name: str, locale: str, promo: str) -> dict:
    """按 Apple 文档的 inline-create 形态拼建页请求。

    ★ 这里的形态来自官方 App Custom Product Pages 文档里的示例请求
      （app + appStoreVersionTemplate + inline 建 version 和 localization）。
      真机第一次跑如果 422，把返回的 detail 发我，按它的 pointer 改。
    """
    vid, lid = "${new-version}", "${new-localization}"
    return {
        "data": {
            "type": "appCustomProductPages",
            "attributes": {"name": name},
            "relationships": {
                "app": {"data": {"type": "apps", "id": app_id}},
                "appStoreVersionTemplate": {"data": {"type": "appStoreVersions", "id": ver_id}},
                "appCustomProductPageVersions": {
                    "data": [{"type": "appCustomProductPageVersions", "id": vid}]},
            },
        },
        "included": [
            {"type": "appCustomProductPageVersions", "id": vid,
             "relationships": {
                 "appCustomProductPage": {
                     "data": {"type": "appCustomProductPages", "id": "${new-page}"}},
                 "appCustomProductPageLocalizations": {
                     "data": [{"type": "appCustomProductPageLocalizations", "id": lid}]}}},
            {"type": "appCustomProductPageLocalizations", "id": lid,
             "attributes": {"locale": locale, "promotionalText": promo}},
        ],
    }


def cmd_create(a) -> int:
    cfg = _cfg(a.config)
    r = PL.build(cfg, a.dir)
    if not r["items"]:
        print("没有素材")
        return 2

    setup = []
    if a.dry or not a.yes:
        aid = cfg.get("app_id") or "<app_id 待解析>"
        ver = cfg.get("template_version") or "<最新 IOS 版本>"
    else:
        c = asc.ASC()
        app = ({"id": cfg["app_id"]} if cfg.get("app_id") else c.app_by_bundle(cfg["bundle_id"]))
        if not app:
            print("找不到 App，先跑 doctor")
            return 1
        aid = app["id"]
        ver = cfg.get("template_version")
        if not ver:
            vers = c.ios_versions(aid)
            if not vers:
                print("这个 App 没有任何 iOS 版本，CPP 必须指定一个模板版本")
                return 1
            ver = vers[0]["id"]
            print("模板版本 = %s（%s）" % (ver, vers[0].get("attributes", {}).get("versionString")))
        exist = {x["attributes"]["name"] for x in c.cpp_list(aid)}

    for it in r["items"]:
        setup.append(_cpp_body(aid, ver, it["cpp_name"], it["locale"], it["promotional_text"]))

    for it, body in zip(r["items"], setup):
        print("-" * 74)
        print("  %s  ->  CPP 「%s」" % (it["stem"], it["cpp_name"]))
        if not it["preview_ready"]:
            print("  [注意] 这条素材不合规，建出来的页没有可用的 preview 视频")
        if a.dry or not a.yes:
            print("  请求体（POST /v1/appCustomProductPages）：")
            print("  " + json.dumps(body, ensure_ascii=False, indent=2).replace("\n", "\n  "))
        else:
            if it["cpp_name"] in exist:
                print("  [跳过] 同名 CPP 已存在")
                continue
            try:
                res = c.post("/v1/appCustomProductPages", body)
                data = res.get("data", {})
                at = data.get("attributes", {})
                print("  [OK] 已建 id=%s  url=%s" % (data.get("id"), at.get("url") or "(审核后生成)"))
            except asc.ASCError as e:
                print("  [FAIL] %s" % asc.explain_http(e.code, e.detail))
                print("         %s" % e.detail[:500])
                return 1
    if a.dry or not a.yes:
        print()
        print("以上只是预览。确认无误后加 --yes 真建。")
    return 0


# ---------------------------------------------------------------- upload
def cmd_upload(a) -> int:
    cfg = _cfg(a.config)
    r = PL.build(cfg, a.dir)
    todo = [i for i in r["items"] if i["preview_ready"]] if not a.force else r["items"]
    if not todo:
        print("没有合规素材可传。先看 plan 里的 FAIL 项。")
        return 2

    ptype = cfg.get("preview_type", "IPHONE_69")
    frame = cfg.get("preview_frame_time_code", "00:00:05")
    print("预览类型 %s   海报帧 %s   共 %d 条" % (ptype, frame, len(todo)))

    if a.dry or not a.yes:
        for it in todo:
            size = Path(it["file"]).stat().st_size
            print("-" * 74)
            print("  %s  (%.1fMB)" % (it["stem"], size / 1048576))
            print("  步骤：")
            print("   1) 找到该 CPP localization 下 previewType=%s 的 appPreviewSet" % ptype)
            print("   2) POST /v1/appPreviews  {fileName, fileSize, previewFrameTimeCode:%s}" % frame)
            print("   3) 按 uploadOperations 分片 PUT")
            print("   4) PATCH /v1/appPreviews/{id} {uploaded:true}")
        print()
        print("★ POST /v1/appPreviews 在 Apple 文档里已标记 deprecated，")
        print("  替代是 POST /v1/appAssetLibraryVideos。两条路都要拿真凭证联调一次才能定，")
        print("  所以这里默认只打印计划。联调时加 --yes。")
        return 0

    c = asc.ASC()
    app = ({"id": cfg["app_id"]} if cfg.get("app_id") else c.app_by_bundle(cfg["bundle_id"]))
    if not app:
        print("找不到 App")
        return 1
    aid = app["id"]
    existing = {x["attributes"]["name"]: x for x in c.cpp_list(aid)}

    ok = 0
    for it in todo:
        name = it["cpp_name"]
        if name not in existing:
            print("  [跳过] %s：Console 里没有同名 CPP，先跑 create" % name)
            continue
        cid = existing[name]["id"]
        vers = c.cpp_versions(cid)
        if not vers:
            print("  [跳过] %s：CPP 没有版本" % name)
            continue
        locs = c.cpp_localizations(vers[0]["id"])
        if not locs:
            print("  [跳过] %s：版本没有 localization" % name)
            continue
        loc = locs[0]["id"]
        sets = c.get("/v1/appCustomProductPageLocalizations/%s/appPreviewSets" % loc,
                     params={"limit": 50}).get("data") or []
        target_set = None
        for s in sets:
            if s["attributes"].get("previewType") == ptype:
                target_set = s
                break
        if not target_set:
            print("  [跳过] %s：找不到 previewType=%s 的预览集（现有 %s）"
                  % (name, ptype, [s["attributes"].get("previewType") for s in sets]))
            continue

        blob = Path(it["file"]).read_bytes()
        body = {"data": {"type": "appPreviews",
                         "attributes": {"fileName": Path(it["file"]).name,
                                        "fileSize": len(blob),
                                        "previewFrameTimeCode": frame},
                         "relationships": {"appPreviewSet": {
                             "data": {"type": "appPreviewSets", "id": target_set["id"]}}}}}
        try:
            res = c.post("/v1/appPreviews", body)
            pid = res["data"]["id"]
            ops = res["data"]["attributes"].get("uploadOperations") or []
            print("  %s：已创建 appPreview id=%s，%d 片" % (name, pid, len(ops)))
            c.upload_operations(ops, blob)
            c.patch("/v1/appPreviews/%s" % pid,
                    {"data": {"type": "appPreviews", "id": pid, "attributes": {"uploaded": True}}})
            print("  %s：[OK] 上传完成" % name)
            ok += 1
        except asc.ASCError as e:
            print("  %s：[FAIL] %s" % (name, asc.explain_http(e.code, e.detail)))
            print("        %s" % e.detail[:400])
    print()
    print("完成 %d/%d" % (ok, len(todo)))
    return 0 if ok == len(todo) else 1


def main() -> int:
    ap = argparse.ArgumentParser(prog="run.py", description="App Store CPP 流水线")
    ap.add_argument("cmd", choices=["doctor", "probe", "validate", "plan", "create", "upload", "all"])
    ap.add_argument("--config", default=str(DEFAULT_CFG))
    ap.add_argument("--dir", default=None, help="素材目录（默认取 config.video_dir）")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--dry", action="store_true", help="只打印，不发送")
    ap.add_argument("--yes", action="store_true", help="真的发送")
    ap.add_argument("--force", action="store_true", help="上传时连不合规素材也处理")
    ap.add_argument("--key-file", default=None)
    ap.add_argument("--key-id", default=None)
    ap.add_argument("--issuer-id", default=None)
    a = ap.parse_args()

    if a.cmd == "doctor":
        return cmd_doctor(a)
    if a.cmd == "plan":
        return cmd_plan(a)
    if a.cmd == "probe":
        cfg = _cfg(a.config)
        d = Path(a.dir or cfg.get("video_dir"))
        for p in sorted(d.rglob("*")):
            if p.suffix.lower() in P.VIDEO_EXT:
                print(json.dumps(P.probe(p), ensure_ascii=False, indent=2))
        return 0
    if a.cmd == "validate":
        cfg = _cfg(a.config)
        d = Path(a.dir or cfg.get("video_dir"))
        rc = 0
        for p in sorted(d.rglob("*")):
            if p.suffix.lower() in P.VIDEO_EXT:
                r = V.validate(p)
                print("[%s] %s" % ("OK  " if r["ok"] else "FAIL", p.name))
                for x in r["issues"]:
                    print("       [%s] %s：%s" % (x["level"], x["code"], x["msg"]))
                rc = rc or (0 if r["ok"] else 1)
        return rc
    if a.cmd == "create":
        return cmd_create(a)
    if a.cmd == "upload":
        return cmd_upload(a)
    if a.cmd == "all":
        rc = cmd_create(a)
        return rc or cmd_upload(a)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
