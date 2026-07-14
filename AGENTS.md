当用户讨论插件、代码、配置或实现方案时，除非用户明确说“开始写”“直接改”“执行”“开工”“帮我实现”“生成文件/插件包”，否则不要修改文件、不要写代码、不要打包、不要运行会改变项目状态的命令。

默认先停在方案讨论阶段：

1. 先解释可行性、风险、实现路径。
2. 给出清晰方案或伪代码。
3. 等用户明确确认后，再开始实际修改和执行。

如果用户像是在询问“能不能”“是不是”“怎么做”“你觉得方案如何”“写段话给别人”，只回答分析或文本，不要擅自实施。

## 本项目身份

本项目是 AstrBot 插件：

- 插件市场身份名：`astrbot_plugin_ha_control_layer`
- 展示名：`Home Assistant 控制器`
- 作者：`Xhan258`
- GitHub 仓库：`https://github.com/Xhan258/astrbot_plugin_ha_control_layer`
- 当前版本：以 `metadata.yaml` 为准；当前文件显示为 `v1.1.7`

发布、打包或改版本前，必须重新读取 `metadata.yaml`、`main.py`、`README.md`、`CHANGELOG.md` 和 `docs/ARCHITECTURE.md`，不要只相信本文件中的版本提示。

## 本项目兼容规则

- `astrbot_plugin_ha_control_layer` 是插件市场身份名。
- `home_assistant_control_layer` 只能作为旧兼容名、旧页面/API 兼容路径、旧数据兼容逻辑或架构说明出现。
- 不要为了清理名字而盲目修改模块名、类名、数据目录、旧配置读取或兼容逻辑。
- 不要把“本地版本号已修改”当成“GitHub 已发布”。
- 不要把“main 分支已推送”当成“AstrBot 能安装到最新版本”。
- 发布新版本时必须确认 GitHub tag 和 GitHub latest release。

## 通用 Skill

开发、调试、文档、配置或打包 AstrBot 插件时，读取用户级通用 Skill：

`C:\Users\Administrator\.agents\skills\astrbot-plugin-development\SKILL.md`

提交、推送、Tag、Release、删除旧版本、改写历史或排查 GitHub 版本问题时，读取用户级通用 Skill：

`C:\Users\Administrator\.agents\skills\astrbot-plugin-publish\SKILL.md`

这些 Skill 是跨仓库通用流程；本文件只保存当前仓库的专属身份和兼容边界。

## 危险 Git 操作

涉及删除 Tag、删除 Release、重写 Git 历史、强制推送、删除远程分支、让某个版本成为“初始版本”时，必须先列出影响并等待用户明确批准。
