# -*- coding: utf-8 -*-
"""快捷人格管理器 v2 单元测试（不依赖 AstrBot 运行时）。"""

import sys
import types
import unittest
from types import SimpleNamespace

# ---- 注入假的 astrbot 模块，使 main.py 可被导入 ----

def _make_module(name: str, **attrs):
    mod = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(mod, k, v)
    return mod


_logger = _make_module("logger", info=lambda *a, **k: None, error=lambda *a, **k: None, warning=lambda *a, **k: None)
_astrbot = _make_module("astrbot", logger=_logger)
_api = _make_module("astrbot.api", logger=_logger)
_event = _make_module(
    "astrbot.api.event",
    filter=_make_module(
        "filter",
        command=lambda *a, **k: (lambda fn: fn),
    ),
    AstrMessageEvent=object,
)
_star = _make_module(
    "astrbot.api.star",
    Context=object,
    Star=object,
    register=lambda *a, **k: (lambda cls: cls),
)

sys.modules["astrbot"] = _astrbot
sys.modules["astrbot.api"] = _api
sys.modules["astrbot.api.event"] = _event
sys.modules["astrbot.api.star"] = _star

import main  # noqa: E402

FENCE = chr(96) * 3


class TestResolveSubcommand(unittest.TestCase):
    def test_english(self):
        self.assertEqual(main.resolve_subcommand("list"), "list")
        self.assertEqual(main.resolve_subcommand("LIST"), "list")
        self.assertEqual(main.resolve_subcommand("view"), "view")

    def test_chinese(self):
        self.assertEqual(main.resolve_subcommand("列表"), "list")
        self.assertEqual(main.resolve_subcommand("查看"), "view")
        self.assertEqual(main.resolve_subcommand("添加"), "add")
        self.assertEqual(main.resolve_subcommand("切换"), "switch")

    def test_unknown(self):
        self.assertIsNone(main.resolve_subcommand("haha"))
        self.assertIsNone(main.resolve_subcommand(""))


class TestSplitHead(unittest.TestCase):
    def test_normal(self):
        self.assertEqual(main.split_head("list"), ("list", ""))
        self.assertEqual(main.split_head("list 2 猫"), ("list", "2 猫"))

    def test_empty(self):
        self.assertEqual(main.split_head(""), ("", ""))
        self.assertEqual(main.split_head("   "), ("", ""))


class TestParseOpts(unittest.TestCase):
    def test_rest_and_opts(self):
        rest, opts = main.parse_opts("助手 描述 --tools none --begin a|b")
        self.assertEqual(rest, ["助手", "描述"])
        self.assertEqual(opts["tools"], "none")
        self.assertEqual(opts["begin"], "a|b")

    def test_flag(self):
        rest, opts = main.parse_opts("助手 --force")
        self.assertEqual(rest, ["助手"])
        self.assertIs(opts["force"], True)


class TestChunkText(unittest.TestCase):
    def test_short(self):
        self.assertEqual(main.chunk_text("abc", 10), ["abc"])

    def test_long(self):
        chunks = main.chunk_text("a\n" + "b" * 2000, 500)
        self.assertGreater(len(chunks), 1)
        self.assertTrue(all(len(c) <= 500 for c in chunks))
        self.assertEqual("".join(chunks), "a\n" + "b" * 2000)


class TestValidateNewName(unittest.TestCase):
    def test_errors(self):
        self.assertIsNotNone(main.validate_new_name("", 32))
        self.assertIsNotNone(main.validate_new_name("a" * 33, 32))
        self.assertIsNotNone(main.validate_new_name("a b", 32))
        self.assertIsNotNone(main.validate_new_name("default", 32))

    def test_ok(self):
        self.assertIsNone(main.validate_new_name("助手", 32))


class TestCheckPermission(unittest.TestCase):
    def test_empty_admin_ids(self):
        self.assertTrue(main.check_permission("1", [], True))
        self.assertFalse(main.check_permission("1", [], False))

    def test_with_ids(self):
        self.assertTrue(main.check_permission("10001", ["10001", "10002"], False))
        self.assertFalse(main.check_permission("10003", ["10001"], True))
        self.assertTrue(main.check_permission(10001, [10001], False))  # 数字也能匹配


class TestToolsAndBegin(unittest.TestCase):
    def test_format_tools_value(self):
        self.assertEqual(main.format_tools_value(None), "全部（继承默认）")
        self.assertEqual(main.format_tools_value([]), "无")
        self.assertEqual(main.format_tools_value(["a", "b"]), "a, b")

    def test_parse_tools_opt(self):
        self.assertIsNone(main.parse_tools_opt("all"))
        self.assertEqual(main.parse_tools_opt("none"), [])
        self.assertEqual(main.parse_tools_opt("a,b"), ["a", "b"])
        self.assertIsNone(main.parse_tools_opt(None))

    def test_parse_begin_opt(self):
        self.assertEqual(main.parse_begin_opt("你好|你好呀"), ["你好", "你好呀"])
        with self.assertRaises(ValueError):
            main.parse_begin_opt("只有一句")


class TestExportImport(unittest.TestCase):
    def test_build_export(self):
        persona = SimpleNamespace(
            persona_id="助手",
            system_prompt="你是助手",
            begin_dialogs=["a", "b"],
            tools=None,
            skills=[],
            custom_error_message="出错了",
        )
        data = main.build_persona_export(persona)
        self.assertEqual(data["persona_id"], "助手")
        self.assertEqual(data["system_prompt"], "你是助手")
        self.assertIsNone(data["tools"])

    def test_parse_import_payload(self):
        payload = '{"persona_id": "助手", "system_prompt": "你好", "begin_dialogs": ["a", "b"]}'
        data = main.parse_import_payload(payload)
        self.assertEqual(data["persona_id"], "助手")
        self.assertEqual(data["begin_dialogs"], ["a", "b"])

    def test_parse_import_payload_fenced(self):
        payload = FENCE + "\n{\"name\": \"猫娘\", \"prompt\": \"喵\"}\n" + FENCE
        data = main.parse_import_payload(payload)
        self.assertEqual(data["persona_id"], "猫娘")
        self.assertEqual(data["system_prompt"], "喵")

    def test_parse_import_payload_missing(self):
        with self.assertRaises(ValueError):
            main.parse_import_payload('{"persona_id": "x"}')


class TestFmtTime(unittest.TestCase):
    def test_none(self):
        self.assertEqual(main.fmt_time(None), "未知")

    def test_int(self):
        self.assertIn("202", main.fmt_time(1700000000))

    def test_str(self):
        self.assertEqual(main.fmt_time("2026-03-14 22:01:04"), "2026-03-14 22:01")


if __name__ == "__main__":
    unittest.main()

