# 快捷人格管理器 (Fast Profile Management)

![GitHub license](https://img.shields.io/github/license/tniay/plugin_upload_Fast_Profile_Management)
![GitHub release](https://img.shields.io/github/v/release/tniay/plugin_upload_Fast_Profile_Management)

## 插件介绍

快捷人格管理器是一个专为 AstrBot 设计的插件，支持管理员快速管理 AI 人格，包括查看人格列表、切换人格、添加和删除人格等操作。

## 功能特性

- ✅ 查看当前人格列表，标记当前使用的人格
- ✅ 快速切换到指定人格
- ✅ 添加新的人格
- ✅ 删除不需要的人格
- ✅ 支持中英文双语指令
- ✅ 仅限管理员使用，权限控制安全
- ✅ 支持插件页面配置功能

## 安装方法

1. 下载插件压缩包
2. 解压到 AstrBot 的插件目录
3. 重启 AstrBot 或使用插件管理命令加载插件

## 使用指令

### 英文指令
- **查看人格列表**：`/profile list`
- **切换人格**：`/profile switch <人格名称>`
- **添加人格**：`/profile add <人格名称> <人格描述>`
- **删除人格**：`/profile remove <人格名称>`

### 中文指令
- **查看人格列表**：`/人格 列表`
- **切换人格**：`/人格 切换 <人格名称>`
- **添加人格**：`/人格 添加 <人格名称> <人格描述>`
- **删除人格**：`/人格 删除 <人格名称>`

## 配置方法

1. 在 AstrBot 的插件管理页面找到「快捷人格管理器」
2. 点击「配置」按钮
3. 在「管理员ID列表」中添加允许使用此插件的用户ID
4. 保存配置

## 示例

### 查看人格列表
```
/profile list
# 或
/人格 列表
```

### 切换人格
```
/profile switch 助手
# 或
/人格 切换 助手
```

### 添加人格
```
/profile add 助手 你是一个智能助手，善于回答各种问题
# 或
/人格 添加 助手 你是一个智能助手，善于回答各种问题
```

### 删除人格
```
/profile remove 助手
# 或
/人格 删除 助手
```

## 权限说明

- 此插件仅限管理员使用
- 管理员ID需要在插件配置页面中设置
- 非管理员使用指令会收到权限不足的提示

## 技术支持

如果遇到问题，请在 GitHub 仓库提交 issue，或联系作者：浅月tniay

## 许可证

[MIT License](LICENSE)
