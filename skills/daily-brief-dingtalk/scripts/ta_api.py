"""
ta_api.py —— TA 取数客户端（ae-cli 版，2026-11-25 起）

旧实现走 `POST /querySql` + token 直连，已随数数系统升级废弃。
现在统一委托给 ta-query skill 的 ta_probe（内部调本机 ae-cli）。

对外接口保持不变：
    get_client(project).query(sql) -> list[dict]
    get_client(project).query_async(...) -> list[dict]   # 已退化为同步
    get_client(project).project_id / event_table / user_table / desc
"""

from __future__ import annotations

import json
import os
import sys

# 依赖 ta-query skill 的客户端，避免两份实现漂移
_TA_QUERY_SCRIPTS = os.path.join(
    os.path.expanduser("~"), ".workbuddy", "skills", "ta-query", "scripts"
)
if _TA_QUERY_SCRIPTS not in sys.path:
    sys.path.insert(0, _TA_QUERY_SCRIPTS)

try:
    from ta_probe import AeClient, get_client as _get_client, AeError  # noqa: F401
except ImportError as e:  # pragma: no cover
    raise ImportError(
        "需要 ta-query skill（ae-cli 客户端）。请确认 ~/.workbuddy/skills/ta-query/scripts/ta_probe.py 存在。"
    ) from e


PROJECTS = {
    "prod_a_android": {"project_id": "<YOUR_PROJECT_ID>", "desc": "SLOT-01-Android"},
    "prod_a_ios": {"project_id": "<YOUR_PROJECT_ID>", "desc": "SLOT-01-iOS"},
    "prod_d_android": {"project_id": "<YOUR_PROJECT_ID>", "desc": "SLOT-04 Android"},
    "prod_c_ios": {"project_id": "<YOUR_PROJECT_ID>", "desc": "SLOT-03 iOS"},
    "prod-b_android": {"project_id": "<YOUR_PROJECT_ID>", "desc": "SLOT-02 Android / PROD_C Android"},
    "prod_e_android": {"project_id": "<YOUR_PROJECT_ID>", "desc": "BUBBLE-01 Android"},
    "prod_e_android": {"project_id": "<YOUR_PROJECT_ID>", "desc": "SLOT-05 Android"},
}

DEFAULT_PROJECT = "prod_a_android"


class TAClient(AeClient):
    """保留旧类名，实际是 ae-cli 客户端"""

    def __init__(self, project: str = DEFAULT_PROJECT):
        alias = {"wc": "prod_a_android", "wc_android": "prod_a_android",
                 "wc_ios": "prod_a_ios", "grc": "prod_d_android",
                 "prod-b": "prod-b_android", "tw": "prod_c_ios",
                 "flow_blast": "prod_e_android", "blast_flow": "prod_e_android"}
        key = alias.get(project, project)
        cfg = PROJECTS.get(key)
        if cfg is None:
            raise KeyError(f"未知项目 {project!r}；可用：{sorted(PROJECTS)}")
        super().__init__(cfg["desc"], cfg["project_id"])
        self.desc = cfg["desc"]


def get_client(project: str = DEFAULT_PROJECT) -> TAClient:
    return TAClient(project)


if __name__ == "__main__":
    sql = sys.argv[1] if len(sys.argv) > 1 else "SELECT 1 AS v"
    rows = TAClient().query(sql)
    print(json.dumps(rows[:5], ensure_ascii=False, indent=2))
