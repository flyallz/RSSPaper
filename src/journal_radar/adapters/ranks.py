"""easyScholar adapter: fixed HTTPS origin, redacted failures and serialized requests."""

import json
import threading
import time
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import HTTPRedirectHandler, Request

from ..config import MAX_DOWNLOAD, USER_AGENT
from ..domain.models import PublicationRank
from .http import build_http_opener

RANK_FIELDS = {
    "sci": "SCI / JCR",
    "ssci": "SSCI / JCR",
    "sciUp": "中科院升级版（大类）",
    "sciUpSmall": "中科院升级版（小类）",
    "sciBase": "中科院基础版",
    "sciUpTop": "中科院 Top",
    "cssci": "CSSCI",
    "pku": "北大核心",
    "cscd": "CSCD",
    "ccf": "CCF",
    "eii": "EI",
    "ahci": "A&HCI",
    "sciif": "影响因子",
    "sciif5": "5 年影响因子",
    "jci": "JCI",
    "ajg": "AJG",
    "sciwarn": "期刊预警",
}
_LOCK = threading.Lock()
_LAST_START = 0.0


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError("期刊接口发生重定向，已停止以保护密钥")


def parse_ranks(payload: bytes, name: str) -> PublicationRank:
    try:
        data = json.loads(payload.decode("utf-8-sig"))
        if not isinstance(data, dict):
            raise ValueError()
        if data.get("code") != 200:
            # Do not echo third-party messages: they may contain the keyed URL.
            code = data.get("code")
            if code in (40002, 40005):
                raise PermissionError("easyScholar 密钥缺失或无效，请在应用设置中核对")
            raise RuntimeError("easyScholar 拒绝查询，请检查账户权限、配额或稍后重试")
        content = data.get("data")
        if not isinstance(content, dict):
            raise ValueError()
        official = content.get("officialRank")
        if not isinstance(official, dict):
            raise ValueError()
        values = official.get("all") if isinstance(official, dict) else None
        if values is None and isinstance(official, dict):
            values = official.get("select") or {}
        if not isinstance(values, dict):
            raise ValueError()
        labels = []
        for key, value in values.items():
            if type(value) in (str, int, float) and str(value).strip():
                labels.append(
                    {
                        "key": str(key),
                        "label": RANK_FIELDS.get(key, str(key)),
                        "value": str(value).strip(),
                        "year": "",
                    }
                )
        custom = content.get("customRank") or {}
        if isinstance(custom, dict):
            definitions = {
                str(record.get("uuid")): record
                for record in custom.get("rankInfo", [])
                if isinstance(record, dict)
            }
            fields = (
                "",
                "oneRankText",
                "twoRankText",
                "threeRankText",
                "fourRankText",
                "fiveRankText",
            )
            for item in custom.get("rank", []) if isinstance(custom.get("rank"), list) else []:
                if not isinstance(item, str) or "&&&" not in item:
                    continue
                uuid, level = item.rsplit("&&&", 1)
                record = definitions.get(uuid)
                if record and level in ("1", "2", "3", "4", "5"):
                    value = record.get(fields[int(level)])
                    if isinstance(value, str) and value.strip():
                        labels.append(
                            {
                                "key": "custom:" + uuid,
                                "label": str(record.get("abbName") or uuid),
                                "value": value.strip(),
                                "year": "",
                            }
                        )
        return {"name": name, "labels": labels}
    except (UnicodeError, json.JSONDecodeError, AttributeError, TypeError, ValueError):
        raise ValueError("easyScholar 返回格式无效，未保存标签") from None


def fetch_ranks(name: str, key: str, proxy: str = "", cancelled=None) -> PublicationRank:
    global _LAST_START
    if not key.strip():
        raise ValueError("请在应用设置中填写 easyScholar 密钥")
    if not name.strip():
        raise ValueError("请填写正式期刊或会议名称")

    def check():
        if cancelled and cancelled():
            raise ValueError("期刊查询已取消")

    while not _LOCK.acquire(timeout=0.1):
        check()
    try:
        check()
        # Conservative <= 2 starts/sec, across all dialogs and worker threads.
        while time.monotonic() - _LAST_START < 0.65:
            check()
            time.sleep(0.05)
        check()
        _LAST_START = time.monotonic()
        url = "https://www.easyscholar.cc/open/getPublicationRank?" + urlencode(
            {"secretKey": key.strip(), "publicationName": name.strip()}
        )
        opener = build_http_opener(proxy)
        opener.add_handler(_NoRedirect())
        request = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
        try:
            with opener.open(request, timeout=22) as response:
                payload = response.read(MAX_DOWNLOAD + 1)
        except HTTPError as error:
            if error.code == 429:
                raise RuntimeError("easyScholar 请求频率受限，请稍后重试") from None
            raise RuntimeError("easyScholar HTTP 请求失败，请检查权限或网络") from None
        except Exception:
            check()
            raise RuntimeError("easyScholar 连接失败，请检查网络、代理或证书") from None
        check()
        if len(payload) > MAX_DOWNLOAD:
            raise ValueError("期刊接口响应过大")
        return parse_ranks(payload, name.strip())
    finally:
        _LOCK.release()
