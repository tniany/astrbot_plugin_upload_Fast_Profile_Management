from astrbot.api.event import filter, AstrMessageEvent, MessageEventResult
from astrbot.api.star import Context, Star, register
from astrbot.api import logger

@register("plugin_upload_Fast_Profile_Management", "浅月tniay", "快捷人格管理器", "1.0.0")
class FastProfileManagement(Star):
    def __init__(self, context: Context):
        super().__init__(context)
        # 使用 context 的配置管理功能
        self.context = context

    async def initialize(self):
        """插件初始化方法"""
        # 初始化配置
        if not await self.context.config.get("admin_ids"):
            await self.context.config.set("admin_ids", [])

    async def is_admin(self, event: AstrMessageEvent) -> bool:
        """检查用户是否为管理员"""
        user_id = event.get_sender_id()
        admin_ids = await self.context.config.get("admin_ids", [])
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
            # 使用 context 提供的方法获取人格列表
            profiles = await self.context.ai.get_profiles()
            if not profiles:
                yield event.plain_result("当前没有人格")
                return

            current_profile = await self.context.ai.get_current_profile()
            response = "当前人格列表：\n"
            for profile in profiles:
                if profile["name"] == current_profile["name"]:
                    response += f"• {profile['name']} (当前)\n"
                else:
                    response += f"• {profile['name']}\n"
            yield event.plain_result(response)
        except Exception as e:
            logger.error(f"获取人格列表失败: {e}")
            yield event.plain_result("获取人格列表失败")

    async def switch_profile(self, event: AstrMessageEvent, profile_name: str):
        """切换人格"""
        try:
            # 使用 context 提供的方法切换人格
            success = await self.context.ai.switch_profile(profile_name)
            if success:
                yield event.plain_result(f"成功切换到人格：{profile_name}")
            else:
                yield event.plain_result(f"切换人格失败，人格 {profile_name} 不存在")
        except Exception as e:
            logger.error(f"切换人格失败: {e}")
            yield event.plain_result("切换人格失败")

    async def add_profile(self, event: AstrMessageEvent, profile_name: str, profile_desc: str):
        """添加人格"""
        try:
            # 使用 context 提供的方法添加人格
            success = await self.context.ai.add_profile(profile_name, profile_desc)
            if success:
                yield event.plain_result(f"成功添加人格：{profile_name}")
            else:
                yield event.plain_result(f"添加人格失败，人格 {profile_name} 已存在")
        except Exception as e:
            logger.error(f"添加人格失败: {e}")
            yield event.plain_result("添加人格失败")

    async def remove_profile(self, event: AstrMessageEvent, profile_name: str):
        """删除人格"""
        try:
            # 使用 context 提供的方法删除人格
            success = await self.context.ai.remove_profile(profile_name)
            if success:
                yield event.plain_result(f"成功删除人格：{profile_name}")
            else:
                yield event.plain_result(f"删除人格失败，人格 {profile_name} 不存在")
        except Exception as e:
            logger.error(f"删除人格失败: {e}")
            yield event.plain_result("删除人格失败")

    def get_config_schema(self):
        """获取插件配置schema"""
        return {
            "admin_ids": {
                "type": "array",
                "title": "管理员ID列表",
                "description": "只有列表中的用户可以使用此插件",
                "default": []
            }
        }

    async def terminate(self):
        """插件销毁方法"""
