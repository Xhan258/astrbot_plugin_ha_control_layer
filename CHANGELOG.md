# 更新日志

## v1.1.11

- 将面板指示灯保留为隐藏的 `indicator_light` 能力，避免其替代设备真实的继电器电源绑定。
- 保留多路开关设备中各自命名的继电器，并为它们生成独立能力及独立绑定。
- 意图匹配时优先识别明确的设备名称；泛称灯具且存在多个候选时会要求澄清。
- 扫描标准 `climate.xxx` 的 `fan_modes`，生成已绑定的风速能力，不会凭空创建设备未支持的档位。

## v1.1.10

- 将标准 `climate.xxx` 实体扫描为独立的温度、模式和明确支持的电源能力。
- 将 `heat`、`cool`、`dry` 等标准 HVAC 模式映射为中文显示名和别名，同时保留其 Home Assistant 原始值与绑定。
- 仅当实体声明支持 `TURN_ON` 和/或 `TURN_OFF` 时，才暴露标准 climate 电源绑定。

## v1.1.9

- 将用户请求中的房间/区域词作为强匹配约束，降低跨房间误控设备的概率。
- 当多个同类型控制器匹配度相同、且用户未提及房间时，要求用户澄清。
- 改进房间环境中的温度、湿度和温湿度汇总查询匹配。
- 保持 Home Assistant 执行逻辑不变；本版本仅调整意图匹配和打包元数据。

## v1.1.8

- 新增只读 LLM 工具 `ha_query_weather`，天气问题可优先查询 Home Assistant，而非网络搜索。
- 优先尝试 `daily` 天气预报，必要时回退到 `hourly` 预报。
- 扫描时识别房间温度和湿度传感器，并归类为房间环境控制器。
- 改进房间温度、湿度和温湿度汇总查询的自然语言匹配。

## v1.1.7

- 通过唯一入口 `ha_execute_intent` 恢复 Home Assistant 天气查询。
- 将 `weather` 实体作为仅查询能力加入控制器索引。
- 通过 `GET /api/states/{entity_id}` 支持当前天气查询。
- 通过 Home Assistant `weather.get_forecasts` 支持天气预报查询。
- 当多个天气实体匹配泛称天气查询时，要求用户澄清。

## v1.1.6

- 将插件市场身份更新为 `astrbot_plugin_ha_control_layer`。
- 将作者更新为 `Xhan258`。
- 将仓库地址更新为 `https://github.com/Xhan258/astrbot_plugin_ha_control_layer`。
- 仅将 `home_assistant_control_layer` 保留为旧版插件页面/API 兼容名称。

## v1.1.4

- 移除对 `astrbot.api.web` 的导入期依赖，恢复与 AstrBot v4.25.6 的兼容性。
- 插件页面 API 返回普通字典，使旧版 Dashboard 能加载插件。
- 页面 POST JSON 采用兼容读取路径：存在时使用新版 `astrbot.api.web`，否则使用 Quart request。

## v1.1.3

- 按 AstrBot Plugin Pages 文档规范重写插件页面前端。
- 在页面模块前显式加载 `/api/plugin/page/bridge-sdk.js`。
- 页面脚本使用 `type="module"`。
- 移除 iframe 页面的直接 `fetch` 回退；所有 Dashboard API 调用均通过 `bridge.apiGet` 和 `bridge.apiPost`。
- 通过 `astrbot.api.web.json_response` 返回页面 API 响应。

## v1.1.2

- 将插件展示名称从 AI管家更名为 Home Assistant 控制器。

## v1.1.1

- 将插件展示名称更名为 AI管家。
- 修复插件页面 API 注册，使其使用 AstrBot 文档中的 `register_web_api(route, handler, methods, desc)` 签名。
- 修复插件页面前端，使用 `window.AstrBotPluginPage.ready()`、`apiGet` 和 `apiPost`，不再直接从 iframe 发起 fetch。
- 为控制器、能力和数值别名编辑新增兼容 POST 的保存端点。

## v1.1.0

- 围绕 `ControllerIndex + IntentMatcher + SafeExecutor` 重建插件。
- 仅暴露一个常规 LLM 工具：`ha_execute_intent`。
- 不再向 Agent 暴露底层 HA 服务、服务列表和状态工具。
- 新增 generated/overrides 索引存储，重新扫描不会覆盖用户整理结果。
- 新增内嵌 AstrBot 插件页面，用于整理控制器、能力和值别名。
- 页面仅作为索引编辑器：不提供设备控制按钮、滑块或服务测试框。
- 自动将常见 HA helper 整理为控制器，包括空调 `input_select`/`input_boolean` 及匹配的电源脚本。
- 默认忽略 automation 作为控制能力；不确定的 script 保留在待整理项。
- 当 HA 提供支持时，为通用灯具新增电源、亮度和色温能力。
- 使用模拟 HA 客户端验证空调电源、温度、模式、风速别名、冰箱 select、灯具暖光和温度查询流程。

## v1.0.4

- 当用户省略设备时推断能力目标，例如“开成制冷模式”“风速开到自然风”。
- 映射常用选项别名，包括“自然风” -> “自由风”。
- 修复能力开关排序，使“风向打开”控制风向 helper，而不是误触发空调开机。
- 要求脚本服务回退候选与目标/能力匹配，降低误调用电源脚本的风险。
- 新增省略设备的模式控制、风向和风速别名行为测试。

## v1.0.3

- 在 `ha_execute_intent` 内新增通用数值/选项执行。
- 支持 `select` 和 `input_select` 选项匹配，例如空调温度 `25℃`、空调模式 `除湿` 和冰箱分区 `蛋类`。
- 支持 `number`/`input_number` 数值设置和标准 `climate.set_temperature` 候选。
- 新增按请求过滤：温度命令优先温度实体，模式命令优先模式实体，避免执行无关的 select 实体。
- 修复 Home Assistant 原始 `/api/services` 字典结构的脚本服务发现。
- 使用模拟 Home Assistant 新增温度、模式、冰箱选项、关机和只查询不执行的端到端测试。

## v1.0.2

- 让 `ha_execute_intent` 在内部执行高置信度的 Home Assistant 控制操作，Agent 不再需要第二次调用 `ha_call_service` 工具。
- 返回包含 HA 执行结果的 `executed=true`，Agent 只需组织自然语言回复。
- 在内部获取 Home Assistant 天气预报，无需第二次工具调用。
- 查询、提问和否定语句不会自动执行。
- 降低 Agent 通过 shell、Python、文件读取或手工处理 Token 绕开插件的可能性。

## v1.0.1

- 改进意图上下文排序，优先选择可操作的 script、switch、light、climate 实体和 helper，而非同步 automation。
- 为 `ha_execute_intent` 新增 `suggested_calls`，提供直接的下一步 `ha_call_service` 候选，减少反复要求补充上下文。
- 为 Home Assistant 天气预报返回同类 `next_step` 指引，使 Agent 可获取预报后自然组织回复。
- 允许明确的 Home Assistant script 服务，例如 `script.bedroom_ac_power_off`，无需伪造 `entity_id`。
- 未匹配实体时不再输出无关服务域。
- 新增少量口语化目标清理，例如“我屋空调” -> “卧室空调”。

## v1.0.0

- 将核心重建为 Hermes 风格的 Home Assistant 上下文和安全服务层。
- 移除遥控器式 LLM 工具：`ha_control_device`、`ha_climate_control`、`ha_select_option`、`ha_schedule_action` 以及场景/script 快捷工具。
- 保留聚焦发现和执行的默认工具：`ha_execute_intent`、`ha_list_entities`、`ha_get_state`、`ha_list_services` 和 `ha_call_service`。
- 让 `ha_execute_intent` 准备实体/状态/服务上下文，而非猜测固定的设备动作。
- 从 README 和设置中移除面向用户的定时脚本设置流程。

## v0.8.0

- 移除旧版第三方延迟集成路径及相关设置。
- 通过 `/ha_install_schedule` 和首次定时家居命令，自动安装 Home Assistant 定时脚本。
- 让 `/ha_check_schedule` 自动检查并安装定时脚本。
- 将插件设置页面简化为连接、可选天气/别名和必要安全控制。
- 仅将 YAML 脚本输出保留为通过 `/ha_schedule_template` 手工使用的回退方案。

## v0.7.4

- 将 README 替换为简短的用户指南，聚焦可说的话、首次设置、定时设置和常用命令。
- 从插件帮助视图中移除 README 目录和开发者说明。

## v0.7.3

- 将 README 重写为更清晰的发布式结构：功能优先，其后是快速开始、定时、配置、命令和注意事项。
- 移除用户侧对未完成的专用 HA 定时器方案的引用。
- 将默认 HA 定时脚本模板简化为仅启动的延迟执行。
- 配置的 HA script 实体缺失时，不再错误报告定时设置成功。
- 让定时功能依赖 HA script 后端。

## v0.7.2

- 新增家居定时工具路由保护：当 Agent 尝试用 `future_task`、提醒、任务或 cron 处理延迟家居控制时，插件会返回结果并要求调用 `ha_execute_intent`。
- 正常用户消息仍由 Agent 处理；新保护在工具调用时生效，不作为遥控器式消息拦截器。
- 新增基础设置 `guard_home_schedule_tools`，默认启用。
- 将消息级定时意图拦截改为高级回退设置 `protect_timed_home_intents`。

## v0.7.1

- 在提醒/任务插件可选后，放宽定时家居意图拦截。
- 将 `protect_timed_home_intents` 默认改为关闭，使普通延迟家居命令可通过 Agent 和 HA 控制层工具处理。
- 启用保护时，忽略“你确定真设置了吗”等后续确认提问，不将其视为新的设备控制命令。

## v0.7.0

- 将插件卡片名称更改为 `Home Assistant 控制层`，并更新面向用户的说明。
- 将 `_conf_schema.json` 重组为 `普通设置` 和 `高级设置`，基础部分仅保留连接、天气、定时脚本、定时意图保护和可选别名。
- 新增 `protect_timed_home_intents`，使“一分钟后关空调”等延迟家居命令在提醒/任务工具处理前由 HA 控制层捕获。
- 保持嵌套配置与旧版平铺配置键兼容。
- 围绕首次运行、定时脚本设置和控制层定位更新 README。

## v0.6.1

- 重建上传包为扁平的 AstrBot 兼容压缩包，避免 AstrBot v4.25.x 的上传解压失败。

## v0.6.0

- 新增 `ha_execute_intent` 作为 Home Assistant 请求的默认单一 LLM 入口。
- 默认隐藏高级 HA LLM 工具至 `expose_advanced_llm_tools` 后，同时保留 `/ha_xxx` 调试命令。
- 在内部将自然语言家居意图路由到状态查询、设备控制、空调控制、选项选择、天气、场景/script/automation 或 HA 定时。
- 在可能时将拦截到的 HA shell/curl/sleep 尝试转换为受保护的 HA 控制层调用，而非仅返回警告。
- 默认停止直接的 shell 绕过聊天提示，使 Agent 仍负责自然语言回复。
- 收紧脚本式设备分类，避免将风向、除甲醛等功能脚本归类为电源脚本。

## v0.5.0

- 新增 Hermes 风格的 `ha_get_overview` 和 `/ha_overview`，用于紧凑的 Home Assistant 清单、域汇总和脚本式设备提示。
- 为实体搜索和状态查询新增结构化消歧结果，使 Agent 可要求澄清而非猜测。
- 新增 shell 绕过保护：与 HA 相关的 shell/curl/sleep 尝试会被中和并重定向到 HA 工具。
- 为脚本式设备的实体摘要补充逻辑设备提示。

## v0.4.0

- 将默认行为改回控制层模式：默认关闭自然语言直接 select/control 拦截，使 Agent 保持意图理解和回复组织职责。
- 控制工具返回结构化 JSON，包含简明 `message`、执行元数据和 `recent_action` 上下文。
- 新增短期内存动作上下文，使后续查询可看到最近 HA 操作，避免与刚执行的控制相矛盾。
- 当不存在标准 `climate.*` 实体时，支持由 `input_select/select` helper 支撑的脚本式空调温度、模式、风速和风向设置。
- 将 `input_select`、`input_boolean`、`button`、`input_button`、`number` 和 `input_number` 加入支持的 HA 控制域。

## v0.3.2

- 新增对“打开卧室空调”“一分钟后关空调”等明确家居开关意图的直接处理。
- 新增遥控器式设备的脚本发现，将“卧室空调-开机/关机”等 script 映射到逻辑开关动作。
- 保持标准实体如 `climate.*` 为首选；脚本式设备发现仅作为回退。
- 通过 `ha_schedule_action` 调度脚本式设备动作，而不是 shell `sleep`/`curl`。

## v0.3.1

- 默认关闭自然语言天气拦截，使 Agent 可使用 HA 数据并组织回复。
- 解析 Home Assistant `weather.get_forecasts` 的 `service_response` 包装结构。
- 新增 `/ha_state <target> [domain]` 作为真实的手工状态查询命令。

## v0.3.0

- 新增 `/ha_schedule_template` 作为手工 HA 定时脚本回退方案。
- 新增 `/ha_check_schedule` 和可选的定时后端。
- 新增早期实验性的第三方延迟后端，已于 v0.8.0 移除。
- 新增 `ha_weather_forecast`、`/ha_weather`、HA 天气查询拦截，以及 `weather.get_forecasts` 服务响应支持。
- 将 `weather.get_forecasts` 等 `allowed_query_services` 视为查询操作，而不是设备控制。

## v0.2.0

- 将按设备的 `timer_bindings` 替换为一个 Home Assistant 定时脚本入口。
- 将 `ha_schedule_timer` 更名为 `ha_schedule_action`。
- 向 HA 发送定时动作变量：操作、定时键、目标实体、服务、延迟和服务数据。

## v0.1.5

- 新增 Hermes 风格的 HA 工具：`ha_list_entities`、`ha_get_state` 和 `ha_list_services`。
- 使 `ha_call_service` 可作为受保护的通用 Home Assistant 服务调用器使用。
- 默认阻止危险服务域，并要求通用调用明确指定实体目标。

## v0.1.4

- 新增对“把珍品变温从熟食改成蛋类”等明确 Home Assistant `select` 选项意图的直接处理。
- 新增 `/ha_select <target> <option>` 作为不经 Agent 的回退命令。
- 保持失败的 HA 工具调用对当前聊天可见。
