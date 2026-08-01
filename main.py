"""快捷人格管理器 (Fast Profile Management) v2

一个功能更全面的 AstrBot 人格管理插件：
- 双语命令（/profile 与 /人格）
- 人格增删改查、复制、重命名、导入导出
- 人格文件夹管理
- 会话/对话管理
- 统计与 LLM 辅助生成
- 基于插件配置的权限控制

兼容 AstrBot 新旧两代 persona_manager 接口（同步/异步返回值）。
"""

from __future__ import annotations

import inspect
import json
import re
import time
from typing import Any

try:
    from astrbot.api import logger
except ImportError:  # 旧版本兼容
    from astrbot import logger

from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star, register

PLUGIN_VERSION = "2.0.0"

# ---------------------------------------------------------------------------
# 纯函数：便于单元测试，不依赖 AstrBot 运行时
# ---------------------------------------------------------------------------

SUBCOMMAND_ALIASES: dict[str, list[str]] = {
    "help": ["help", "帮助", "用法"],
    "list": ["list", "列表", "ls"],
    "view": ["view", "查看", "详情", "show"],
    "add": ["add", "添加", "新建", "create"],
    "edit": ["edit", "编辑", "修改", "update"],
    "remove": ["remove", "删除", "删", "rm"],
    "switch": ["switch", "切换", "使用", "use"],
    "rename": ["rename", "重命名", "改名"],
    "duplicate": ["duplicate", "复制", "克隆", "cp"],
    "export": ["export", "导出"],
    "import": ["import", "导入"],
    "recommend": ["recommend", "推荐", "生成", "ai"],
    "folder": ["folder", "文件夹", "目录"],
    "move": ["move", "移动"],
    "conv": ["conv", "对话", "conversation"],
    "stats": ["stats", "统计", "概况"],
}


def resolve_subcommand(word: str) -> str | None:
    """把用户输入的子命令词（中英文）解析为内部命令名。"""
    w = str(word).strip().lower()
    if not w:
        return None
    for cmd, aliases in SUBCOMMAND_ALIASES.items():
        if w in [a.lower() for a in aliases]:
            return cmd
    return None


def split_head(tail: str) -> tuple[str, str]:
    """取第一段作为子命令词，剩余部分作为参数。"""
    parts = str(tail).strip().split(None, 1)
    if not parts or not parts[0]:
        return "", ""
    return parts[0].lower(), (parts[1].strip() if len(parts) > 1 else "")


def parse_opts(tail: str) -> tuple[list[str], dict[str, str | bool]]:
    """解析尾部参数，支持 --key value / --flag 形式。"""
    parts = str(tail).split()
    rest: list[str] = []
    opts: dict[str, str | bool] = {}
    i = 0
    while i < len(parts):
        p = parts[i]
        if p.startswith("--"):
            key = p[2:].lower()
            vals: list[str] = []
            j = i + 1
            while j < len(parts) and not parts[j].startswith("--"):
                vals.append(parts[j])
                j += 1
            opts[key] = " ".join(vals) if vals else True
            i = j
        else:
            rest.append(p)
            i += 1
    return rest, opts


def chunk_text(text: str, size: int = 1500) -> list[str]:
    """按行拆分长文本为不超过 size 字符的多个片段。"""
    text = str(text)
    if len(text) <= size:
        return [text]
    chunks: list[str] = []
    cur = ""
    lines = text.split("\n")
    for idx, line in enumerate(lines):
        suffix = "\n" if idx < len(lines) - 1 else ""
        line_with_nl = line + suffix
        while len(line_with_nl) > size:
            if cur:
                space = size - len(cur)
                cur += line_with_nl[:space]
                line_with_nl = line_with_nl[space:]
                chunks.append(cur)
                cur = ""
            else:
                chunks.append(line_with_nl[:size])
                line_with_nl = line_with_nl[size:]
        if cur and len(cur) + len(line_with_nl) > size:
            chunks.append(cur)
            cur = line_with_nl
        else:
            cur += line_with_nl
    if cur:
        chunks.append(cur)
    return chunks


def validate_new_name(
    name: str,
    max_len: int = 32,
    reserved: tuple[str, ...] = ("default", "默认"),
) -> str | None:
    """校验新人格名称，返回错误信息或 None。"""
    if not name:
        return "人格名称不能为空。"
    if len(name) > int(max_len):
        return f"人格名称过长（最多 {max_len} 字）。"
    if re.search(r"\s", name):
        return "人格名称不能包含空格，请使用简短名称。"
    if name in reserved:
        return f"{name} 是保留名称，不能使用。"
    return None


def check_permission(
    sender_id: str,
    admin_ids: list[str] | tuple[str, ...] | None,
    allow_all_when_no_admin: bool = True,
) -> bool:
    """权限检查：admin_ids 为空时按 allow_all_when_no_admin 放行。"""
    ids = [str(x).strip() for x in (admin_ids or []) if str(x).strip()]
    if not ids:
        return bool(allow_all_when_no_admin)
    return str(sender_id) in ids


def format_tools_value(v: Any) -> str:
    """格式化 tools/skills 字段。None=全部，[]=无，list=指定。"""
    if v is None:
        return "全部（继承默认）"
    if not v:
        return "无"
    return ", ".join(str(x) for x in v)


def parse_tools_opt(v: str | bool | None) -> list[str] | None:
    """解析 --tools 选项：all->None，none->[]，否则按逗号拆分。"""
    if v is None or v is True:
        return None
    s = str(v).strip().lower()
    if s in ("all", "*", "全部"):
        return None
    if s in ("none", "无", "0"):
        return []
    return [x.strip() for x in str(v).split(",") if x.strip()]


def parse_begin_opt(v: str | bool | None) -> list[str] | None:
    """解析 --begin 开场白：用户|助手 成对出现，用 | 分隔。"""
    if v is None or v is True:
        return None
    parts = [x.strip() for x in str(v).split("|") if x.strip()]
    if len(parts) % 2 != 0:
        raise ValueError("开场白必须是成对内容（用户|助手），用 | 分隔")
    return parts


def build_persona_export(persona: Any) -> dict:
    """把 Persona 对象转成可导入的字典。"""
    return {
        "persona_id": getattr(persona, "persona_id", ""),
        "system_prompt": getattr(persona, "system_prompt", "") or "",
        "begin_dialogs": getattr(persona, "begin_dialogs", None) or [],
        "tools": getattr(persona, "tools", None),
        "skills": getattr(persona, "skills", None),
        "custom_error_message": getattr(persona, "custom_error_message", None),
        "exported_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "source": "astrbot_plugin_upload_Fast_Profile_Management",
    }


def parse_import_payload(payload: str) -> dict:
    """解析导入文本：支持裸 JSON 或 markdown 代码块围栏。"""
    fence = chr(96) * 3
    s = str(payload).strip()
    if s.startswith(fence):
        lines = s.splitlines()
        if lines and lines[0].startswith(fence):
            lines = lines[1:]
        if lines and lines[-1].strip() == fence:
            lines = lines[:-1]
        s = "\n".join(lines).strip()
    data = json.loads(s)
    if not isinstance(data, dict):
        raise ValueError("导入内容必须是 JSON 对象")
    name = data.get("persona_id") or data.get("name") or data.get("id")
    prompt = (
        data.get("system_prompt")
        or data.get("prompt")
        or data.get("description")
    )
    if not name or not prompt:
        raise ValueError("缺少 persona_id/name 或 system_prompt/prompt 字段")
    return {
        "persona_id": str(name),
        "system_prompt": str(prompt),
        "begin_dialogs": data.get("begin_dialogs") or [],
        "tools": data.get("tools"),
        "skills": data.get("skills"),
        "custom_error_message": data.get("custom_error_message"),
    }


def fmt_time(value: Any) -> str:
    """格式化时间戳/日期，尽量兼容 int、datetime、str。"""
    if value is None:
        return "未知"
    try:
        if isinstance(value, (int, float)) and value > 0:
            return time.strftime("%Y-%m-%d %H:%M", time.localtime(value))
        return str(value)[:16]
    except Exception:
        return "未知"

# ---------------------------------------------------------------------------
# 帮助文本
# ---------------------------------------------------------------------------

HELP_MAIN = [
    "快捷人格管理器 v2（/profile 或 /人格）",
    "人格管理：列表 | 查看 <名称> | 添加 <名称> <描述> | 编辑 <名称> <字段> <值> | 删除 <名称>",
    "切换/派生：切换 <名称> | 复制 <源> <新名> | 重命名 <旧名> <新名>",
    "导入导出：导出 <名称> | 导入 <JSON> | 推荐 <主题>（LLM 辅助）",
    "文件夹：文件夹 list|create|rename|delete | 移动 <人格> <文件夹>",
    "对话：对话 list|switch|new|rename|delete|clear|clearall",
    "其他：统计 | 帮助 <子命令>",
    "所有子命令均支持中文，例如「/人格 列表」「/人格 切换 助手」。",
]

HELP_DETAIL: dict[str, list[str]] = {
    "list": ["用法：/人格 列表 [页码] [关键词]", "示例：/人格 列表 2 猫", "列出人格并标记当前会话正在使用的人格。"],
    "view": ["用法：/人格 查看 <人格名称>", "查看人格的系统提示、开场白、工具、技能等完整信息。"],
    "add": [
        "用法：/人格 添加 <名称> <描述> [--tools all|none|工具1,工具2] [--begin 用户话|助手话]",
        "示例：/人格 添加 助手 你是一个智能助手 --tools none --begin 你好|你好，有什么可以帮你？",
        "--tools 默认 all（全部工具）；--begin 必须成对，用 | 分隔。",
    ],
    "edit": [
        "用法：/人格 编辑 <名称> <字段> <值>",
        "字段：prompt(描述) / begin(开场白) / tools(工具) / skills(技能) / error(错误提示)",
        "示例：/人格 编辑 助手 prompt 你是一个乐于助人的AI",
    ],
    "remove": ["用法：/人格 删除 <名称> [--force]", "default 人格默认受保护，需 --force 才能删除。"],
    "switch": ["用法：/人格 切换 <人格名称>", "把当前会话切换到指定人格。"],
    "rename": ["用法：/人格 重命名 <旧名称> <新名称>", "复制旧人格为新名称后删除旧人格。"],
    "duplicate": ["用法：/人格 复制 <源人格> <新名称>", "完整复制一个人格（包括描述、开场白、工具设置）。"],
    "export": ["用法：/人格 导出 <人格名称>", "输出可导入的 JSON 文本。"],
    "import": ["用法：/人格 导入 <JSON>", "导入 JSON 格式的人格（可用导出命令生成）。"],
    "recommend": ["用法：/人格 推荐 <主题>", "让当前 LLM 生成人格建议（需 allow_llm_assist 开启）。"],
    "folder": [
        "用法：/人格 文件夹 <动作> <参数>",
        "动作：list / create <名称> / rename <名称或ID> <新名称> / delete <名称或ID>",
        "删除文件夹不会删除人格，内部人格会移回根目录。",
    ],
    "move": ["用法：/人格 移动 <人格名称> <文件夹名称|文件夹ID|根>", "把人格移动到指定文件夹或根目录。"],
    "conv": [
        "用法：/人格 对话 <动作> <参数>",
        "list / switch <序号或ID前缀> / new [标题] [--persona 人格]",
        "rename <序号或ID前缀> <新标题> / delete <序号或ID前缀>",
        "clear（清空当前对话历史）/ clearall --yes（删除当前会话全部对话）",
    ],
    "stats": ["用法：/人格 统计", "显示人格、文件夹、对话、token 等统计信息。"],
    "help": ["用法：/人格 帮助 [子命令]", "查看总帮助或某个子命令的详细帮助。"],
}


# ---------------------------------------------------------------------------
# 插件主体
# ---------------------------------------------------------------------------

@register(
    "plugin_upload_Fast_Profile_Management",
    "浅月tniay",
    "快捷人格管理器",
    PLUGIN_VERSION,
)
class FastProfileManagement(Star):
    def __init__(self, context: Context, config: Any = None):
        super().__init__(context)
        self.context = context
        self.config = config if config is not None else {}

    # ---------------- 配置与权限 ----------------

    def _cfg(self, key: str, default: Any) -> Any:
        try:
            if hasattr(self.config, "get"):
                return self.config.get(key, default)
        except Exception:
            pass
        return default

    def _is_enabled(self) -> bool:
        return bool(self._cfg("enabled", True))

    def _admin_ids(self) -> list[str]:
        v = self._cfg("admin_ids", [])
        if isinstance(v, (list, tuple, set)):
            return [str(x) for x in v]
        return []

    def _allow_all(self) -> bool:
        return bool(self._cfg("allow_all_when_no_admin", True))

    async def _is_allowed(self, event: AstrMessageEvent) -> bool:
        return check_permission(
            str(event.get_sender_id()),
            self._admin_ids(),
            self._allow_all(),
        )

    # ---------------- 兼容层 ----------------

    @staticmethod
    async def _safe(fn, *args, **kwargs):
        """调用可能同步也可能异步的框架方法。"""
        ret = fn(*args, **kwargs)
        if inspect.isawaitable(ret):
            return await ret
        return ret

    def _pm(self):
        return getattr(self.context, "persona_manager", None)

    def _cm(self):
        return getattr(self.context, "conversation_manager", None)

    async def _get_persona(self, persona_id: str):
        """获取人格；新版框架不存在时抛异常，统一转成 None。"""
        pm = self._pm()
        if not pm or not hasattr(pm, "get_persona"):
            return None
        try:
            return await self._safe(pm.get_persona, persona_id)
        except Exception as e:
            msg = str(e).lower()
            if "not exist" in msg or "不存在" in msg:
                return None
            raise

    async def _create_persona(
        self,
        persona_id: str,
        system_prompt: str,
        begin_dialogs: list[str] | None = None,
        tools: list[str] | None = None,
        skills: list[str] | None = None,
        custom_error_message: str | None = None,
    ):
        pm = self._pm()
        try:
            await self._safe(
                pm.create_persona,
                persona_id=persona_id,
                system_prompt=system_prompt,
                begin_dialogs=begin_dialogs,
                tools=tools,
                skills=skills,
                custom_error_message=custom_error_message,
            )
        except TypeError:  # 旧版 create_persona 参数较少
            await self._safe(
                pm.create_persona,
                persona_id=persona_id,
                system_prompt=system_prompt,
                begin_dialogs=begin_dialogs,
                tools=tools,
            )

    async def _update_persona(self, persona_id: str, **kwargs):
        pm = self._pm()
        try:
            await self._safe(pm.update_persona, persona_id, **kwargs)
        except TypeError:  # 旧版 update_persona 参数较少
            base = {}
            if "system_prompt" in kwargs:
                base["system_prompt"] = kwargs["system_prompt"]
            if "begin_dialogs" in kwargs:
                base["begin_dialogs"] = kwargs["begin_dialogs"]
            await self._safe(pm.update_persona, persona_id, **base)

    async def _current_persona_id(self, event: AstrMessageEvent) -> str | None:
        cm = self._cm()
        if not cm:
            return None
        try:
            umo = event.unified_msg_origin
            cid = await self._safe(cm.get_curr_conversation_id, umo)
            if not cid:
                return None
            conv = await self._safe(cm.get_conversation, umo, cid)
            return getattr(conv, "persona_id", None) if conv else None
        except Exception:
            return None

    async def _find_folder(self, pm, key: str):
        if not hasattr(pm, "get_all_folders"):
            return None
        key = str(key)
        try:
            folders = await self._safe(pm.get_all_folders) or []
            for f in folders:
                if str(getattr(f, "folder_id", "")) == key or str(getattr(f, "name", "")) == key:
                    return f
        except Exception:
            return None
        return None

    async def _resolve_conv(self, cm, umo: str, target: str):
        """按序号或 ID 前缀解析对话，返回 (conversation, conversations)。"""
        convs = await self._safe(cm.get_conversations, umo) or []
        if not convs:
            return None, []
        if target.isdigit():
            i = int(target)
            if 1 <= i <= len(convs):
                return convs[i - 1], convs
            return None, convs
        matches = [c for c in convs if str(getattr(c, "cid", "")).startswith(target)]
        if len(matches) == 1:
            return matches[0], convs
        return None, convs

    # ---------------- 命令入口 ----------------

    @filter.command("profile", alias={"人格", "人设"})
    async def profile_command(self, event: AstrMessageEvent):
        if not self._is_enabled():
            return
        if not await self._is_allowed(event):
            yield event.plain_result("权限不足：本插件仅限管理员使用。")
            return

        msg = event.get_message_str().strip()
        parts = msg.split(None, 1)
        rest = parts[1].strip() if len(parts) > 1 else ""
        sub, tail = split_head(rest)
        cmd = resolve_subcommand(sub)
        try:
            if cmd is None:
                results = await self._cmd_help(event, "")
            else:
                results = await self._dispatch(event, cmd, tail)
            for part in chunk_text("\n".join(results)):
                yield event.plain_result(part)
        except Exception as e:
            logger.error(f"快捷人格管理器命令执行失败: {e}", exc_info=True)
            yield event.plain_result(f"命令执行失败：{e}")

    async def _dispatch(self, event: AstrMessageEvent, cmd: str, tail: str) -> list[str]:
        if cmd == "help":
            return await self._cmd_help(event, tail)
        if cmd == "list":
            return await self._cmd_list(event, tail)
        if cmd == "view":
            return await self._cmd_view(event, tail)
        if cmd == "add":
            return await self._cmd_add(event, tail)
        if cmd == "edit":
            return await self._cmd_edit(event, tail)
        if cmd == "remove":
            return await self._cmd_remove(event, tail)
        if cmd == "switch":
            return await self._cmd_switch(event, tail)
        if cmd == "rename":
            return await self._cmd_rename(event, tail)
        if cmd == "duplicate":
            return await self._cmd_duplicate(event, tail)
        if cmd == "export":
            return await self._cmd_export(event, tail)
        if cmd == "import":
            return await self._cmd_import(event, tail)
        if cmd == "recommend":
            return await self._cmd_recommend(event, tail)
        if cmd == "folder":
            return await self._cmd_folder(event, tail)
        if cmd == "move":
            return await self._cmd_move(event, tail)
        if cmd == "conv":
            return await self._cmd_conv(event, tail)
        if cmd == "stats":
            return await self._cmd_stats(event)
        return ["未知子命令，输入「/人格 帮助」查看用法。"]

    # ---------------- 人格：查看/列表 ----------------

    async def _cmd_list(self, event: AstrMessageEvent, tail: str) -> list[str]:
        args, _ = parse_opts(tail)
        page = 1
        keyword = ""
        if args and args[0].isdigit():
            page = max(1, int(args[0]))
            keyword = " ".join(args[1:])
        else:
            keyword = " ".join(args)

        pm = self._pm()
        if not pm or not hasattr(pm, "get_all_personas"):
            return ["人格管理不可用：persona_manager 不存在。"]
        personas = list(await self._safe(pm.get_all_personas) or [])
        if not personas:
            return ["当前没有人格。" + (f"（关键词：{keyword}）" if keyword else "")]

        folders = {}
        if hasattr(pm, "get_all_folders"):
            try:
                fl = await self._safe(pm.get_all_folders) or []
                folders = {getattr(f, "folder_id", ""): getattr(f, "name", "") for f in fl}
            except Exception:
                pass

        if keyword:
            k = keyword.lower()
            personas = [
                p
                for p in personas
                if k in str(getattr(p, "persona_id", "")).lower()
                or k in str(getattr(p, "system_prompt", "")).lower()
            ]
            if not personas:
                return [f"没有找到包含「{keyword}」的人格。"]

        curr_pid = await self._current_persona_id(event)
        page_size = max(1, min(50, int(self._cfg("page_size", 10))))
        total_pages = max(1, (len(personas) + page_size - 1) // page_size)
        page = min(page, total_pages)
        start = (page - 1) * page_size
        items = personas[start : start + page_size]

        lines = [f"人格列表（共 {len(personas)} 个，第 {page}/{total_pages} 页）："]
        for p in items:
            pid = getattr(p, "persona_id", "?")
            mark = "（当前）" if pid == curr_pid else ""
            prompt = str(getattr(p, "system_prompt", "") or "").strip().replace("\n", " ")
            summary = prompt[:24] + ("…" if len(prompt) > 24 else "")
            fid = getattr(p, "folder_id", None)
            fname = folders.get(fid) if fid else ""
            folder_txt = f"（{fname}）" if fname else ""
            lines.append(f"• {pid}{mark}：{summary}{folder_txt}")
        lines.append("提示：「/人格 列表 <页码> <关键词>」翻页搜索；「/人格 查看 <名称>」看详情。")
        return lines

    async def _cmd_view(self, event: AstrMessageEvent, tail: str) -> list[str]:
        args, _ = parse_opts(tail)
        if not args:
            return ["用法：/人格 查看 <人格名称>"]
        name = args[0]
        p = await self._get_persona(name)
        if not p:
            return [f"人格 {name} 不存在。"]
        lines = [f"人格详情：{getattr(p, 'persona_id', '?')}"]
        prompt = str(getattr(p, "system_prompt", "") or "")
        lines.append(f"系统提示（{len(prompt)} 字）：")
        lines.append(prompt if prompt else "（未设置）")
        bd = getattr(p, "begin_dialogs", None) or []
        if bd:
            lines.append(f"开场白（{len(bd)} 条）：")
            for i, d in enumerate(bd, 1):
                lines.append(f"  {i}. {d}")
        lines.append(f"工具：{format_tools_value(getattr(p, 'tools', None))}")
        lines.append(f"技能：{format_tools_value(getattr(p, 'skills', None))}")
        err = getattr(p, "custom_error_message", None)
        lines.append(f"错误提示：{err if err else '（未设置）'}")
        fid = getattr(p, "folder_id", None)
        if fid:
            folder = await self._find_folder(self._pm(), fid)
            lines.append(f"文件夹：{getattr(folder, 'name', fid) if folder else fid}")
        lines.append(f"创建时间：{fmt_time(getattr(p, 'created_at', None))}")
        lines.append(f"更新时间：{fmt_time(getattr(p, 'updated_at', None))}")
        return lines

    # ---------------- 人格：添加/编辑/删除/切换 ----------------

    async def _cmd_add(self, event: AstrMessageEvent, tail: str) -> list[str]:
        args, opts = parse_opts(tail)
        if len(args) < 2:
            return [
                "用法：/人格 添加 <名称> <描述> [--tools all|none|工具1,工具2] [--begin 用户话|助手话]",
            ]
        name, desc = args[0], " ".join(args[1:])
        err = validate_new_name(name, int(self._cfg("max_persona_name_length", 32)))
        if err:
            return [err]
        max_prompt = int(self._cfg("max_prompt_length", 2000))
        if len(desc) > max_prompt:
            return [f"描述过长（{len(desc)} 字），最多 {max_prompt} 字。"]
        if await self._get_persona(name):
            return [f"人格 {name} 已存在，如需修改请使用「/人格 编辑」。"]
        try:
            begin = parse_begin_opt(opts.get("begin"))
        except ValueError as e:
            return [str(e)]
        tools = parse_tools_opt(opts.get("tools"))
        await self._create_persona(name, desc, begin_dialogs=begin, tools=tools)
        return [
            f"已添加人格：{name}",
            f"切换：/人格 切换 {name}；查看：/人格 查看 {name}",
        ]

    async def _cmd_edit(self, event: AstrMessageEvent, tail: str) -> list[str]:
        args, _ = parse_opts(tail)
        if len(args) < 3:
            return [
                "用法：/人格 编辑 <名称> <字段> <值>",
                "字段：prompt(描述) / begin(开场白) / tools(工具) / skills(技能) / error(错误提示)",
            ]
        name, field, value = args[0], args[1].lower(), " ".join(args[2:])
        if not await self._get_persona(name):
            return [f"人格 {name} 不存在。"]
        kwargs: dict[str, Any] = {}
        if field in ("prompt", "desc", "system", "描述", "提示"):
            max_prompt = int(self._cfg("max_prompt_length", 2000))
            if len(value) > max_prompt:
                return [f"描述过长（{len(value)} 字），最多 {max_prompt} 字。"]
            kwargs["system_prompt"] = value
        elif field in ("begin", "dialogs", "开场", "开场白"):
            try:
                kwargs["begin_dialogs"] = parse_begin_opt(value.replace("，", "|"))
            except ValueError as e:
                return [str(e)]
        elif field in ("tools", "工具"):
            kwargs["tools"] = parse_tools_opt(value)
        elif field in ("skills", "技能"):
            kwargs["skills"] = parse_tools_opt(value)
        elif field in ("error", "err", "错误", "错误提示"):
            kwargs["custom_error_message"] = value
        else:
            return [f"不支持的字段：{field}"]
        await self._update_persona(name, **kwargs)
        return [f"已更新人格 {name} 的「{field}」字段。"]

    async def _cmd_remove(self, event: AstrMessageEvent, tail: str) -> list[str]:
        args, opts = parse_opts(tail)
        if not args:
            return ["用法：/人格 删除 <名称> [--force]"]
        name = args[0]
        if self._cfg("protect_default_persona", True) and name.lower() == "default" and not opts.get("force"):
            return ["default 是系统默认人格，受保护。如确需删除请加 --force（不推荐）。"]
        if not await self._get_persona(name):
            return [f"人格 {name} 不存在。"]
        pm = self._pm()
        await self._safe(pm.delete_persona, name)
        return [
            f"已删除人格：{name}",
            "提示：使用该人格的对话仍保留原 persona_id，如需清理请手动切换对话人格。",
        ]

    async def _cmd_switch(self, event: AstrMessageEvent, tail: str) -> list[str]:
        args, _ = parse_opts(tail)
        if not args:
            return ["用法：/人格 切换 <人格名称>"]
        name = args[0]
        if not await self._get_persona(name):
            return [f"人格 {name} 不存在。"]
        cm = self._cm()
        if not cm:
            return ["会话管理不可用：conversation_manager 不存在。"]
        umo = event.unified_msg_origin
        cid = await self._safe(cm.get_curr_conversation_id, umo)
        if cid:
            await self._safe(cm.update_conversation, umo, cid, persona_id=name)
        else:
            await self._safe(cm.new_conversation, umo, persona_id=name)
        return [f"已切换当前会话人格：{name}"]

    # ---------------- 人格：重命名/复制/导入导出/推荐 ----------------

    async def _cmd_rename(self, event: AstrMessageEvent, tail: str) -> list[str]:
        args, _ = parse_opts(tail)
        if len(args) < 2:
            return ["用法：/人格 重命名 <旧名称> <新名称>"]
        old, new = args[0], args[1]
        if self._cfg("protect_default_persona", True) and old.lower() == "default":
            return ["default 人格受保护，不能重命名。"]
        err = validate_new_name(new, int(self._cfg("max_persona_name_length", 32)))
        if err:
            return [err]
        p = await self._get_persona(old)
        if not p:
            return [f"人格 {old} 不存在。"]
        if await self._get_persona(new):
            return [f"人格 {new} 已存在。"]
        await self._create_persona(
            new,
            getattr(p, "system_prompt", "") or "",
            begin_dialogs=getattr(p, "begin_dialogs", None) or [],
            tools=getattr(p, "tools", None),
            skills=getattr(p, "skills", None),
            custom_error_message=getattr(p, "custom_error_message", None),
        )
        await self._safe(self._pm().delete_persona, old)
        return [
            f"已将人格 {old} 重命名为 {new}（复制后删除原人格）。",
            "提示：正在使用旧名称的对话需重新执行切换。",
        ]

    async def _cmd_duplicate(self, event: AstrMessageEvent, tail: str) -> list[str]:
        args, _ = parse_opts(tail)
        if len(args) < 2:
            return ["用法：/人格 复制 <源人格> <新名称>"]
        src, dst = args[0], args[1]
        err = validate_new_name(dst, int(self._cfg("max_persona_name_length", 32)))
        if err:
            return [err]
        p = await self._get_persona(src)
        if not p:
            return [f"人格 {src} 不存在。"]
        if await self._get_persona(dst):
            return [f"人格 {dst} 已存在。"]
        await self._create_persona(
            dst,
            getattr(p, "system_prompt", "") or "",
            begin_dialogs=getattr(p, "begin_dialogs", None) or [],
            tools=getattr(p, "tools", None),
            skills=getattr(p, "skills", None),
            custom_error_message=getattr(p, "custom_error_message", None),
        )
        return [f"已复制人格：{src} -> {dst}"]

    async def _cmd_export(self, event: AstrMessageEvent, tail: str) -> list[str]:
        args, _ = parse_opts(tail)
        if not args:
            return ["用法：/人格 导出 <人格名称>"]
        name = args[0]
        p = await self._get_persona(name)
        if not p:
            return [f"人格 {name} 不存在。"]
        text_out = json.dumps(build_persona_export(p), ensure_ascii=False, indent=2)
        return [f"人格 {name} 导出（可直接用于「/人格 导入」，如被截断请拼接完整）：", text_out]

    async def _cmd_import(self, event: AstrMessageEvent, tail: str) -> list[str]:
        if not tail:
            return ["用法：/人格 导入 <JSON>（可用「/人格 导出」生成）"]
        try:
            data = parse_import_payload(tail)
        except Exception as e:
            return [f"导入内容解析失败：{e}"]
        name = data["persona_id"]
        err = validate_new_name(name, int(self._cfg("max_persona_name_length", 32)))
        if err:
            return [err]
        if await self._get_persona(name):
            return [f"人格 {name} 已存在，请先删除或重命名。"]
        await self._create_persona(
            name,
            data["system_prompt"],
            begin_dialogs=data.get("begin_dialogs") or [],
            tools=data.get("tools"),
            skills=data.get("skills"),
            custom_error_message=data.get("custom_error_message"),
        )
        return [f"已导入人格：{name}（可用「/人格 切换 {name}」使用）"]

    async def _cmd_recommend(self, event: AstrMessageEvent, tail: str) -> list[str]:
        if not tail:
            return ["用法：/人格 推荐 <主题>，例如：/人格 推荐 猫娘"]
        if not self._cfg("allow_llm_assist", True):
            return ["LLM 辅助功能未启用（请在插件配置中开启 allow_llm_assist）。"]
        try:
            prov = self.context.get_using_provider(umo=event.unified_msg_origin)
        except Exception as e:
            logger.warning(f"获取 LLM Provider 失败: {e}")
            prov = None
        if not prov:
            return ["当前没有可用的 LLM 提供商，无法生成人格建议。"]
        prompt = (
            f"请为主题「{tail}」设计一个 AI 人格。\n"
            "要求：\n"
            "1. 给出一个简短建议名称（不含空格）；\n"
            "2. 写 200-400 字的中文系统提示词，说明人设、语气、行为准则；\n"
            "3. 按以下格式输出：\n名称：xxx\n描述：xxx"
        )
        try:
            resp = await prov.text_chat(
                prompt=prompt,
                system_prompt="你是一名 AI 人格设计专家，只输出中文，格式清晰。",
            )
            result = getattr(resp, "result", None)
            if not result:
                result = str(resp)
            return [
                f"为「{tail}」生成的人格建议：",
                str(result),
                "保存：/人格 添加 <名称> <描述>",
            ]
        except Exception as e:
            logger.error(f"LLM 生成人格建议失败: {e}", exc_info=True)
            return [f"LLM 生成失败：{e}"]

    # ---------------- 文件夹管理 ----------------

    async def _cmd_folder(self, event: AstrMessageEvent, tail: str) -> list[str]:
        pm = self._pm()
        if not pm:
            return ["人格管理不可用。"]
        if not tail:
            return ["用法：/人格 文件夹 list|create|rename|delete <参数>（也可用中文）"]
        sub, rest = split_head(tail)
        if sub in ("list", "列表", "ls"):
            return await self._folder_list(pm)
        if sub in ("create", "创建", "新建"):
            if not rest:
                return ["用法：/人格 文件夹 create <名称>"]
            try:
                f = await self._safe(pm.create_folder, name=rest)
                fid = getattr(f, "folder_id", "?")
                return [f"已创建文件夹：{rest}（ID: {str(fid)[:8]}）"]
            except TypeError:
                f = await self._safe(pm.create_folder, rest)
                fid = getattr(f, "folder_id", "?")
                return [f"已创建文件夹：{rest}（ID: {str(fid)[:8]}）"]
        if sub in ("rename", "重命名", "改名"):
            args, _ = parse_opts(rest)
            if len(args) < 2:
                return ["用法：/人格 文件夹 rename <名称或ID> <新名称>"]
            f = await self._find_folder(pm, args[0])
            if not f:
                return [f"文件夹 {args[0]} 不存在。"]
            await self._safe(pm.update_folder, getattr(f, "folder_id"), name=args[1])
            return [f"已重命名文件夹：{args[0]} -> {args[1]}"]
        if sub in ("delete", "删除", "删"):
            if not rest:
                return ["用法：/人格 文件夹 delete <名称或ID>"]
            f = await self._find_folder(pm, rest)
            if not f:
                return [f"文件夹 {rest} 不存在。"]
            await self._safe(pm.delete_folder, getattr(f, "folder_id"))
            return [f"已删除文件夹：{getattr(f, 'name', rest)}（内部人格已移回根目录）"]
        return [f"未知文件夹动作：{sub}，支持 list/create/rename/delete"]

    async def _folder_list(self, pm) -> list[str]:
        if not hasattr(pm, "get_all_folders"):
            return ["当前 AstrBot 版本不支持人格文件夹功能。"]
        try:
            folders = await self._safe(pm.get_all_folders) or []
        except Exception:
            return ["读取文件夹列表失败。"]
        lines = [f"人格文件夹（{len(folders)} 个）："]
        if not folders:
            lines.append("暂无文件夹，可用「/人格 文件夹 create <名称>」创建。")
            return lines
        for f in folders:
            fid = getattr(f, "folder_id", "?")
            fname = getattr(f, "name", "?")
            parent = getattr(f, "parent_id", None)
            try:
                cnt = len(await self._safe(pm.get_personas_by_folder, fid) or [])
            except Exception:
                cnt = "?"
            parent_txt = f"，父级 {str(parent)[:8]}" if parent else ""
            lines.append(f"• {fname}（ID: {str(fid)[:8]}，人格 {cnt} 个{parent_txt}）")
        return lines

    async def _cmd_move(self, event: AstrMessageEvent, tail: str) -> list[str]:
        args, _ = parse_opts(tail)
        if len(args) < 2:
            return ["用法：/人格 移动 <人格名称> <文件夹名称|文件夹ID|根>"]
        pname, target = args[0], args[1]
        if not await self._get_persona(pname):
            return [f"人格 {pname} 不存在。"]
        pm = self._pm()
        if not hasattr(pm, "move_persona_to_folder"):
            return ["当前 AstrBot 版本不支持人格文件夹移动。"]
        if target in ("根", "root", "无", "-"):
            await self._safe(pm.move_persona_to_folder, pname, None)
            return [f"已将人格 {pname} 移动到根目录。"]
        f = await self._find_folder(pm, target)
        if not f:
            return [f"文件夹 {target} 不存在。"]
        await self._safe(pm.move_persona_to_folder, pname, getattr(f, "folder_id"))
        return [f"已将人格 {pname} 移动到文件夹「{getattr(f, 'name', target)}」。"]

    # ---------------- 对话管理 ----------------

    async def _cmd_conv(self, event: AstrMessageEvent, tail: str) -> list[str]:
        cm = self._cm()
        if not cm:
            return ["会话管理不可用：conversation_manager 不存在。"]
        if not tail:
            return ["用法：/人格 对话 list|switch|new|rename|delete|clear|clearall <参数>（也可用中文）"]
        sub, rest = split_head(tail)
        umo = event.unified_msg_origin
        if sub in ("list", "列表", "ls"):
            return await self._conv_list(cm, umo)
        if sub in ("switch", "切换", "切"):
            if not rest:
                return ["用法：/人格 对话 switch <序号|ID前缀>"]
            target = rest.split()[0]
            conv, _ = await self._resolve_conv(cm, umo, target)
            if not conv:
                return [f"未找到唯一匹配的对话：{target}"]
            await self._safe(cm.switch_conversation, umo, getattr(conv, "cid"))
            title = getattr(conv, "title", "") or getattr(conv, "cid")
            return [f"已切换当前对话：{title}"]
        if sub in ("new", "新建", "新"):
            args, opts = parse_opts(rest)
            title = " ".join(args) or None
            pid = opts.get("persona") if isinstance(opts.get("persona"), str) else None
            if pid and not await self._get_persona(pid):
                return [f"人格 {pid} 不存在。"]
            cid = await self._safe(cm.new_conversation, umo, title=title, persona_id=pid)
            return [f"已新建对话（ID: {str(cid)[:8]}）并切换为当前对话。"]
        if sub in ("rename", "重命名", "改名"):
            args, _ = parse_opts(rest)
            if len(args) < 2:
                return ["用法：/人格 对话 rename <序号|ID前缀> <新标题>"]
            conv, _ = await self._resolve_conv(cm, umo, args[0])
            if not conv:
                return [f"未找到唯一匹配的对话：{args[0]}"]
            new_title = " ".join(args[1:])
            await self._safe(cm.update_conversation, umo, getattr(conv, "cid"), title=new_title)
            return [f"已将对话重命名为：{new_title}"]
        if sub in ("delete", "删除", "删"):
            if not rest:
                return ["用法：/人格 对话 delete <序号|ID前缀>"]
            target = rest.split()[0]
            conv, _ = await self._resolve_conv(cm, umo, target)
            if not conv:
                return [f"未找到唯一匹配的对话：{target}"]
            title = getattr(conv, "title", "") or getattr(conv, "cid")
            await self._safe(cm.delete_conversation, umo, getattr(conv, "cid"))
            return [f"已删除对话：{title}"]
        if sub in ("clear", "清空"):
            cid = await self._safe(cm.get_curr_conversation_id, umo)
            if not cid:
                return ["当前没有对话。"]
            await self._safe(cm.update_conversation, umo, cid, history=[])
            return ["已清空当前对话的历史记录。"]
        if sub in ("clearall", "清空全部", "全部删除"):
            _, opts = parse_opts(rest)
            if not opts.get("yes"):
                return ["此操作将删除当前会话的全部对话，确认请加 --yes：/人格 对话 clearall --yes"]
            await self._safe(cm.delete_conversations_by_user_id, umo)
            return ["已删除当前会话的全部对话。"]
        return [f"未知对话动作：{sub}，支持 list/switch/new/rename/delete/clear/clearall"]

    async def _conv_list(self, cm, umo: str) -> list[str]:
        try:
            convs = await self._safe(cm.get_conversations, umo) or []
        except Exception:
            return ["当前 AstrBot 版本不支持对话列表查询。"]
        if not convs:
            return ["当前会话还没有对话，可用「/人格 对话 new」新建。"]
        curr = await self._safe(cm.get_curr_conversation_id, umo)
        lines = [f"当前会话对话列表（{len(convs)} 个）："]
        for i, c in enumerate(convs, 1):
            cid = getattr(c, "cid", "?")
            title = getattr(c, "title", "") or "（无标题）"
            pid = getattr(c, "persona_id", "") or "默认"
            tok = getattr(c, "token_usage", 0) or 0
            mark = "（当前）" if cid == curr else ""
            created = fmt_time(getattr(c, "created_at", None))
            lines.append(f"{i}. {title}{mark} | ID:{str(cid)[:8]} | 人格:{pid} | tokens:{tok} | {created}")
        return lines

    # ---------------- 统计与帮助 ----------------

    async def _cmd_stats(self, event: AstrMessageEvent) -> list[str]:
        pm, cm = self._pm(), self._cm()
        lines = ["快捷人格管理器统计："]
        if pm:
            try:
                personas = await self._safe(pm.get_all_personas) or []
                lines.append(f"• 人格数量：{len(personas)}")
            except Exception:
                lines.append("• 人格数量：未知")
            try:
                folders = await self._safe(pm.get_all_folders) or []
                lines.append(f"• 文件夹数量：{len(folders)}")
            except Exception:
                pass
        else:
            lines.append("• 人格管理：不可用")
        if cm:
            umo = event.unified_msg_origin
            try:
                convs = await self._safe(cm.get_conversations, umo) or []
                lines.append(f"• 当前会话对话数：{len(convs)}")
                cid = await self._safe(cm.get_curr_conversation_id, umo)
                if cid:
                    conv = await self._safe(cm.get_conversation, umo, cid)
                    if conv:
                        tok = getattr(conv, "token_usage", 0) or 0
                        hist = getattr(conv, "history", "") or ""
                        try:
                            cnt = len(json.loads(hist)) if isinstance(hist, str) else len(hist or [])
                        except Exception:
                            cnt = 0
                        lines.append(
                            f"• 当前对话：{getattr(conv, 'title', '') or '无标题'}（消息 {cnt} 条，tokens {tok}）"
                        )
            except Exception as e:
                lines.append(f"• 会话统计失败：{e}")
        return lines

    async def _cmd_help(self, event: AstrMessageEvent, tail: str) -> list[str]:
        sub, _ = split_head(tail)
        if sub:
            cmd = resolve_subcommand(sub)
            if cmd and cmd in HELP_DETAIL:
                return [f"「{sub}」使用帮助："] + HELP_DETAIL[cmd]
            return [f"未知子命令：{sub}"] + HELP_MAIN
        return list(HELP_MAIN)

    # ---------------- 生命周期 ----------------

    async def initialize(self):
        """插件初始化"""
        logger.info("快捷人格管理器 v2 已加载")

    async def terminate(self):
        """插件卸载"""
        logger.info("快捷人格管理器已卸载")
