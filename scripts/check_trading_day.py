# -*- coding: utf-8 -*-
"""
===================================
交易日历前置检查（GitHub Actions workflow 用）
===================================

在 analyze job 开头调用 Tushare Pro 的 trade_cal 接口，判断今天
（A股，Asia/Shanghai）是否为交易日。休市日输出 is_trading_day=false，
workflow 跳过 main.py，job 优雅退出（exit 0，不计为失败）。

设计要点：
1. 仅用标准库（urllib/json），可以在 pip install 之前运行，休市日
   连依赖安装都省了。
2. fail-open：TUSHARE_TOKEN 缺失、网络异常、接口报错、返回解析失败、
   TUSHARE_HTTP_URL 非法时，一律视为交易日（is_trading_day=true），
   绝不误杀正常交易日。
3. 尊重 --force-run（FORCE_RUN=true）和 TRADING_DAY_CHECK_ENABLED=false，
   与 main.py 内置的 Issue #373 交易日检查保持一致。
"""

import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime
from zoneinfo import ZoneInfo

TUSHARE_DEFAULT_URL = "http://api.tushare.pro"
REQUEST_TIMEOUT_SECONDS = 30


def _log(msg: str) -> None:
    print(msg, flush=True)


def _github_output(key: str, value: str) -> None:
    path = os.environ.get("GITHUB_OUTPUT")
    line = f"{key}={value}"
    if path:
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    else:
        # 本地调试时直接打印
        _log(f"[GITHUB_OUTPUT] {line}")


def _check_enabled() -> bool:
    """是否需要执行交易日检查。"""
    if os.environ.get("FORCE_RUN", "").strip().lower() == "true":
        _log("⚡ FORCE_RUN=true，跳过交易日检查")
        return False
    raw = os.environ.get("TRADING_DAY_CHECK_ENABLED", "true").strip().lower()
    enabled = raw not in ("0", "false", "no", "off", "")
    if not enabled:
        _log("TRADING_DAY_CHECK_ENABLED 已关闭，跳过交易日检查")
    return enabled


def _resolve_api_url() -> str:
    """复用仓库约定的 TUSHARE_HTTP_URL（见 data_provider/tushare_fetcher.py）。"""
    raw = (os.environ.get("TUSHARE_HTTP_URL") or "").strip()
    if not raw:
        return TUSHARE_DEFAULT_URL
    if not (raw.startswith("http://") or raw.startswith("https://")):
        raise ValueError(
            f"TUSHARE_HTTP_URL 必须以 http:// 或 https:// 开头，当前值: {raw!r}"
        )
    return raw


def _is_trading_day_today(api_url: str, token: str) -> bool:
    """查询 Tushare trade_cal，返回今天是否为 A 股交易日。失败时抛异常。"""
    today = datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y%m%d")
    payload = {
        "api_name": "trade_cal",
        "token": token,
        "params": {"exchange": "SSE", "start_date": today, "end_date": today},
        "fields": "exchange,cal_date,is_open",
    }
    req = urllib.request.Request(
        api_url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT_SECONDS) as resp:
        body = json.loads(resp.read().decode("utf-8"))
    if body.get("code") != 0:
        raise RuntimeError(
            f"Tushare 接口返回错误: code={body.get('code')} msg={body.get('msg')}"
        )
    data = body.get("data") or {}
    fields = data.get("fields") or []
    items = data.get("items") or []
    if "is_open" not in fields or not items:
        raise RuntimeError(f"Tushare trade_cal 返回为空: {body}")
    is_open = items[0][fields.index("is_open")]
    return str(is_open) == "1"


def main() -> int:
    if not _check_enabled():
        _github_output("is_trading_day", "true")
        return 0

    token = (os.environ.get("TUSHARE_TOKEN") or "").strip()
    if not token:
        _log("⚠️ 未配置 TUSHARE_TOKEN，无法查询交易日历；按交易日继续执行（fail-open）")
        _github_output("is_trading_day", "true")
        return 0

    try:
        api_url = _resolve_api_url()
    except ValueError as exc:
        _log(f"⚠️ {exc}；按交易日继续执行（fail-open）")
        _github_output("is_trading_day", "true")
        return 0

    try:
        trading = _is_trading_day_today(api_url, token)
    except Exception as exc:  # noqa: BLE001 - 交易日查询失败必须 fail-open
        _log(f"⚠️ 交易日历查询失败（{exc}）；按交易日继续执行（fail-open）")
        _github_output("is_trading_day", "true")
        return 0

    today = datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y-%m-%d")
    if trading:
        _log(f"✅ {today} 为 A 股交易日，继续执行分析")
        _github_output("is_trading_day", "true")
    else:
        _log(f"🏖️ {today} A 股休市，跳过本次分析（优雅退出，不计为失败）")
        _github_output("is_trading_day", "false")
    return 0


if __name__ == "__main__":
    sys.exit(main())
