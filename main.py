from astrbot.api.event import filter, AstrMessageEvent, MessageEventResult
from astrbot.api.star import Context, Star, register
from astrbot.api import logger
from astrbot.api import AstrBotConfig

@register("plugin_upload_Fast_Profile_Management", "浅月tniay", "快捷人格管理器", "1.0.0")
class FastProfileManagement(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.context = context
        self.config = config

    async def initialize(self):
        """插件初始化方法"""
        # 初始化配置
        if not self.config.get("admin_ids"):
            self.config["admin_ids"] = []
            self.config.save_config()

    async def is_admin(self, event: AstrMessageEvent) -> bool:
        """检查用户是否为管理员"""
        user_id = event.get_sender_id()
        admin_ids = self.config.get("admin_ids", [])
        return str(user_id) in admin_ids

    @filter.command("profile")
    @filter.command("人格")
    async def profile_command(self, event: AstrMessageEvent):
        """人格管理指令，支持查看、切换、添加、删除人格"""
        # 检查权限
        if not await self.is_admin(event):
            yield event.plain_result("权限不足，仅限管理员使用")
            return

        message_str = event.message_str.strip()
        args = message_str.split(" ")

        if len(args) < 2:
            yield event.plain_result("用法：/profile|/人格 list|switch|add|remove <参数> 或 /profile|/人格 列表|切换|添加|删除 <参数>")
            return

        subcommand = args[1]

        # 中文命令映射
        subcommand_map = {
            "列表": "list",
            "切换": "switch",
            "添加": "add",
            "删除": "remove"
        }

        if subcommand in subcommand_map:
            subcommand = subcommand_map[subcommand]

        if subcommand == "list":
            await self.list_profiles(event)
        elif subcommand == "switch":
            if len(args) < 3:
                yield event.plain_result("用法：/profile switch <人格名称> 或 /人格 切换 <人格名称>")
                return
            await self.switch_profile(event, args[2])
        elif subcommand == "add":
            if len(args) < 4:
                yield event.plain_result("用法：/profile add <人格名称> <人格描述> 或 /人格 添加 <人格名称> <人格描述>")
                return
            profile_name = args[2]
            profile_desc = " ".join(args[3:])
            await self.add_profile(event, profile_name, profile_desc)
        elif subcommand == "remove":
            if len(args) < 3:
                yield event.plain_result("用法：/profile remove <人格名称> 或 /人格 删除 <人格名称>")
                return
            await self.remove_profile(event, args[2])
        else:
            yield event.plain_result("用法：/profile|/人格 list|switch|add|remove <参数> 或 /profile|/人格 列表|切换|添加|删除 <参数>")

    async def list_profiles(self, event: AstrMessageEvent):
        """查看当前人格列表"""
        try:
            # 使用 persona_manager 获取人格列表
            personas = self.context.persona_manager.get_all_personas()
            if not personas:
                yield event.plain_result("当前没有人格")
                return

            # 获取当前会话的人格
            umo = event.unified_msg_origin
            conv_mgr = self.context.conversation_manager
            curr_cid = await conv_mgr.get_curr_conversation_id(umo)
            conversation = await conv_mgr.get_conversation(umo, curr_cid)
            current_persona_id = conversation.persona_id if conversation else None

            response = "当前人格列表：\n"
            for persona in personas:
                if persona.persona_id == current_persona_id:
                    response += f"• {persona.persona_id} (当前)\n"
                else:
                    response += f"• {persona.persona_id}\n"
            yield event.plain_result(response)
        except Exception as e:
            logger.error(f"获取人格列表失败: {e}")
            yield event.plain_result("获取人格列表失败")

    async def switch_profile(self, event: AstrMessageEvent, profile_name: str):
        """切换人格"""
        try:
            # 检查人格是否存在
            persona = self.context.persona_manager.get_persona(profile_name)
            if not persona:
                yield event.plain_result(f"切换人格失败，人格 {profile_name} 不存在")
                return

            # 切换到指定人格
            umo = event.unified_msg_origin
            conv_mgr = self.context.conversation_manager
            curr_cid = await conv_mgr.get_curr_conversation_id(umo)
            await conv_mgr.update_conversation(umo, curr_cid, persona_id=profile_name)
            yield event.plain_result(f"成功切换到人格：{profile_name}")
        except Exception as e:
            logger.error(f"切换人格失败: {e}")
            yield event.plain_result("切换人格失败")

    async def add_profile(self, event: AstrMessageEvent, profile_name: str, profile_desc: str):
        """添加人格"""
        try:
            # 检查人格是否已存在
            existing_persona = self.context.persona_manager.get_persona(profile_name)
            if existing_persona:
                yield event.plain_result(f"添加人格失败，人格 {profile_name} 已存在")
                return

            # 添加新人格
            self.context.persona_manager.create_persona(
                persona_id=profile_name,
                system_prompt=profile_desc,
                begin_dialogs=[],
                tools=None
            )
            yield event.plain_result(f"成功添加人格：{profile_name}")
        except Exception as e:
            logger.error(f"添加人格失败: {e}")
            yield event.plain_result("添加人格失败")

    async def remove_profile(self, event: AstrMessageEvent, profile_name: str):
        """删除人格"""
        try:
            # 检查人格是否存在
            persona = self.context.persona_manager.get_persona(profile_name)
            if not persona:
                yield event.plain_result(f"删除人格失败，人格 {profile_name} 不存在")
                return

            # 删除人格
            self.context.persona_manager.delete_persona(profile_name)
            yield event.plain_result(f"成功删除人格：{profile_name}")
        except Exception as e:
            logger.error(f"删除人格失败: {e}")
            yield event.plain_result("删除人格失败")

    async def terminate(self):
        """插件销毁方法"""
