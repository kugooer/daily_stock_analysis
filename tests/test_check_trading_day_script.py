# -*- coding: utf-8 -*-
"""Tests for scripts/check_trading_day.py (workflow 前置交易日检查)."""

import importlib.util
import io
import json
import os
import unittest
from contextlib import contextmanager
from unittest.mock import patch

_SCRIPT_PATH = os.path.join(
    os.path.dirname(__file__), "..", "scripts", "check_trading_day.py"
)


def _load_module():
    spec = importlib.util.spec_from_file_location("check_trading_day", _SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


mod = _load_module()


@contextmanager
def _env(**kwargs):
    """临时设置环境变量；值为 None 表示删除。"""
    saved = {}
    for key, value in kwargs.items():
        saved[key] = os.environ.get(key)
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value
    try:
        yield
    finally:
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


class _FakeResponse:
    def __init__(self, payload):
        self._payload = json.dumps(payload).encode("utf-8")

    def read(self):
        return self._payload

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def _trade_cal_response(is_open):
    return {
        "request_id": "test",
        "code": 0,
        "msg": "",
        "data": {
            "fields": ["exchange", "cal_date", "is_open"],
            "items": [["SSE", "20261002", is_open]],
        },
    }


class CheckTradingDayTest(unittest.TestCase):
    def _run_main(self, env, urlopen_side_effect=None):
        """运行 main()，返回 (exit_code, github_output_dict, stdout)。"""
        output_path = os.path.join(self._tmp_dir(), "github_output.txt")
        with _env(GITHUB_OUTPUT=output_path, **env):
            with patch.object(
                mod.urllib.request, "urlopen", side_effect=urlopen_side_effect
            ) as mock_urlopen:
                buf = io.StringIO()
                with patch.object(mod.sys, "stdout", buf):
                    code = mod.main()
        outputs = {}
        if os.path.exists(output_path):
            with open(output_path, encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if "=" in line:
                        k, v = line.split("=", 1)
                        outputs[k] = v
        return code, outputs, buf.getvalue(), mock_urlopen

    def _tmp_dir(self):
        import tempfile

        if not hasattr(self, "_tmpdir"):
            self._tmpdir = tempfile.mkdtemp(prefix="trading_day_test_")
        return self._tmpdir

    def _base_env(self):
        return {
            "TUSHARE_TOKEN": "test-token",
            "TUSHARE_HTTP_URL": None,
            "FORCE_RUN": None,
            "TRADING_DAY_CHECK_ENABLED": None,
        }

    def test_trading_day_continues(self):
        code, outputs, out, mock = self._run_main(
            self._base_env(),
            urlopen_side_effect=lambda *a, **k: _FakeResponse(
                _trade_cal_response(1)
            ),
        )
        self.assertEqual(code, 0)
        self.assertEqual(outputs.get("is_trading_day"), "true")
        self.assertIn("交易日", out)
        mock.assert_called_once()

    def test_holiday_skips(self):
        code, outputs, out, mock = self._run_main(
            self._base_env(),
            urlopen_side_effect=lambda *a, **k: _FakeResponse(
                _trade_cal_response(0)
            ),
        )
        self.assertEqual(code, 0)
        self.assertEqual(outputs.get("is_trading_day"), "false")
        self.assertIn("休市", out)
        mock.assert_called_once()

    def test_api_error_fails_open(self):
        def boom(*a, **k):
            raise OSError("connection reset")

        code, outputs, out, _ = self._run_main(self._base_env(), boom)
        self.assertEqual(code, 0)
        self.assertEqual(outputs.get("is_trading_day"), "true")
        self.assertIn("fail-open", out)

    def test_error_code_fails_open(self):
        code, outputs, out, _ = self._run_main(
            self._base_env(),
            urlopen_side_effect=lambda *a, **k: _FakeResponse(
                {"code": -2001, "msg": "token invalid", "data": {}}
            ),
        )
        self.assertEqual(code, 0)
        self.assertEqual(outputs.get("is_trading_day"), "true")

    def test_missing_token_fails_open_without_request(self):
        env = self._base_env()
        env["TUSHARE_TOKEN"] = ""
        code, outputs, out, mock = self._run_main(env)
        self.assertEqual(code, 0)
        self.assertEqual(outputs.get("is_trading_day"), "true")
        mock.assert_not_called()

    def test_invalid_http_url_fails_open(self):
        env = self._base_env()
        env["TUSHARE_HTTP_URL"] = "api.tushare.pro"
        code, outputs, out, mock = self._run_main(env)
        self.assertEqual(code, 0)
        self.assertEqual(outputs.get("is_trading_day"), "true")
        mock.assert_not_called()

    def test_force_run_skips_check(self):
        env = self._base_env()
        env["FORCE_RUN"] = "true"
        code, outputs, out, mock = self._run_main(env)
        self.assertEqual(code, 0)
        self.assertEqual(outputs.get("is_trading_day"), "true")
        mock.assert_not_called()
        self.assertIn("FORCE_RUN", out)

    def test_check_disabled_skips(self):
        env = self._base_env()
        env["TRADING_DAY_CHECK_ENABLED"] = "false"
        code, outputs, out, mock = self._run_main(env)
        self.assertEqual(code, 0)
        self.assertEqual(outputs.get("is_trading_day"), "true")
        mock.assert_not_called()


if __name__ == "__main__":
    unittest.main()
