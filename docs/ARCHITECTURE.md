# Home Assistant 控制器架构说明

本文面向开发者，说明当前版本的核心结构和数据流。用户安装和使用说明见 [README.md](../README.md)。

## 当前插件信息

- 插件注册名：`astrbot_plugin_ha_control_layer`
- 兼容旧页面/API 名称：`home_assistant_control_layer`
- 展示名称：`Home Assistant 控制器`
- 当前版本：`v1.1.6`
- 普通 LLM Tool：`ha_execute_intent`

插件的目标是把 Home Assistant 中分散的实体整理成 AstrBot 可以理解的控制器索引，并通过安全边界执行明确的设备控制。

## 总体数据流

```text
用户自然语言
↓
AstrBot Agent 调用 ha_execute_intent
↓
parse_intent 解析基础槽位
↓
IntentMatcher 在 ControllerIndex 中匹配控制器、能力和值
↓
SafeExecutor 校验 domain、危险实体和绑定
↓
HomeAssistantClient 调用 Home Assistant service
↓
返回结构化结果，由 Agent 组织自然语言回复
```

普通 LLM 工具只暴露 `ha_execute_intent`。低层 Home Assistant service/list/state 工具不作为普通 Agent 工具暴露，避免绕开控制器索引和安全校验。

## 主要模块

### `main.py`

插件入口，负责：

- 注册 AstrBot 插件。
- 读取配置。
- 注册 `ha_execute_intent`。
- 注册聊天命令：
  - `/ha_check`
  - `/ha_rescan`
  - `/ha_index`
  - `/ha_version`
- 注册 Plugin Page API。
- 调用扫描器、匹配器和执行器。

### `modules/homeassistant.py`

Home Assistant 客户端，负责：

- REST API：
  - `GET /api/`
  - `GET /api/states`
  - `GET /api/states/{entity_id}`
  - `POST /api/services/{domain}/{service}`
  - `POST /api/template`
- WebSocket API：
  - `/api/websocket`
  - `config/entity_registry/list_for_display`
  - `config/area_registry/list`
  - `config/device_registry/list`

REST API 用于状态读取和 service 执行。WebSocket API 用于读取 entity registry、area registry 和 device registry，以补充房间、设备和实体注册信息。

### `discovery/scanner.py`

扫描和归组模块，负责：

- 从 `/api/states` 读取实体状态。
- 合并 WebSocket registry 元数据。
- 生成 `NormalizedEntity`。
- 按设备、房间和名称前缀归组实体。
- 生成 `Controller`、`Capability`、`CapabilityValue` 和 `Binding`。
- 隐藏配置项、诊断项、遥控器槽位、参数重置等内部实体。
- 过滤 `automation`。
- 谨慎处理 `script`，只自动绑定明确属于设备能力的脚本。

当前扫描层关注的 domain：

```text
climate
fan
input_boolean
input_number
input_select
light
number
script
select
sensor
binary_sensor
switch
```

其中 `automation` 默认忽略。

### `index/models.py`

控制器索引的数据模型。

#### `ControllerIndex`

完整索引对象，包含：

- `controllers`
- `pending`
- `warnings`
- `summary`
- `last_scan_time`
- `scan_status`

#### `Controller`

代表一个被整理后的设备或家电，例如“卧室空调”“客厅灯”。

主要字段：

- `controller_id`
- `display_name`
- `aliases`
- `exposed`
- `area_id`
- `area_name`
- `source`
- `capabilities`

#### `Capability`

代表控制器的一项能力，例如电源、温度、模式、风速。

主要字段：

- `capability_id`
- `display_name`
- `type`
- `aliases`
- `exposed`
- `entity_id`
- `domain`
- `values`
- `binding`

#### `CapabilityValue`

代表能力的一个可选值，例如“开”“关”“除湿”“自然风”。

主要字段：

- `value`
- `display_name`
- `aliases`
- `binding`

#### `Binding`

代表最终执行时要调用的 Home Assistant service。

```json
{
  "domain": "input_boolean",
  "service": "turn_off",
  "service_data": {
    "entity_id": "input_boolean.bedroom_ac_power"
  }
}
```

### `index/store.py`

索引持久化和合并模块。

当前使用两个文件：

- `data/ha_index.generated.json`
- `data/ha_index.overrides.json`

`generated` 保存扫描自动生成的索引。`overrides` 保存用户在插件页面中整理过的显示名、别名、暴露开关和值别名。

`effective_index()` 会把两者合并。重新扫描只会覆盖 generated index，不会直接删除用户 overrides。

### `matcher/intent_parser.py`

轻量意图解析器，负责从用户文本中提取：

- 是否查询。
- 设备提示。
- 能力提示。
- 值提示。
- 数值。
- 开关动作。

它不负责执行，只产出匹配所需的基础槽位。

### `matcher/matcher.py`

控制器索引匹配器，负责：

- 按控制器名称和别名匹配设备。
- 按能力名称、别名和值匹配能力。
- 在匹配不确定时返回 `need_clarification`。
- 对开关类请求默认优先匹配电源能力。
- 返回最终可执行的 `Binding`。

如果匹配不到唯一且安全的能力，会要求用户补充，而不是直接执行。

### `executor/safe_executor.py`

执行器，负责最后一层安全校验和 service 调用。

校验内容包括：

- binding domain 是否在允许列表中。
- binding domain 是否被危险服务列表屏蔽。
- entity_id 是否在高风险实体黑名单中。

校验通过后，才会调用 Home Assistant service。

### `modules/permissions.py`

权限模块，负责判断当前会话是否允许查询或控制。

配置来源：

- `admin_users`
- `admin_groups`
- `allow_query_without_admin`

当用户和群都未配置时，默认不限制控制者。

## Plugin Page API

插件页面通过 AstrBot 的 Plugin Page bridge 调用后端 API。

注册路径包含当前插件名和旧插件名：

```text
/astrbot_plugin_ha_control_layer/controllers
/astrbot_plugin_ha_control_layer/rescan
/astrbot_plugin_ha_control_layer/pending
/astrbot_plugin_ha_control_layer/controllers/<controller_id>
/astrbot_plugin_ha_control_layer/controllers/<controller_id>/capabilities/<capability_id>
/astrbot_plugin_ha_control_layer/controllers/<controller_id>/capabilities/<capability_id>/values/<value_id>
```

旧路径前缀：

```text
/home_assistant_control_layer/...
```

页面文件位于：

```text
pages/controllers/index.html
pages/controllers/app.js
pages/controllers/style.css
```

页面打开时读取 `controllers`，不会自动触发 `rescan`。点击重新扫描时调用 `rescan`。

## Discovery 与 Registry 合并

扫描时 REST `/api/states` 提供：

- `entity_id`
- `state`
- `attributes`
- `friendly_name`
- `options`

WebSocket entity registry 提供：

- `entity_id`
- `area_id`
- `device_id`
- `entity_category`
- `hidden_by`
- `platform`
- `name`

area registry 提供：

- `area_id`
- `name`

device registry 提供：

- `device_id`
- `area_id`
- `name_by_user`
- `name`
- `original_name`

合并 key 是 `entity_id`。实体自身没有 `area_id` 时，会尝试通过 `device_id` 找到设备所属房间。

如果 WebSocket registry 失败，扫描会降级使用 `/api/states`，并把相关 warning 放进索引。

## 控制器归组策略

扫描器按以下优先级归组：

1. 有 `device_id` 时，优先按 `device_id` 归组。
2. 没有 `device_id` 时，尝试从 friendly name 提取共同前缀，例如“客厅灯 * 功能设置 dimming”归到“客厅灯”。
3. 仍然无法归组时，生成单独控制器。

同一个 HA 设备下的大量实体不会直接暴露成几十个控制器。配置项、诊断项、遥控器槽位和参数重置等会进入隐藏或高级信息。

## 能力生成策略

常见能力包括：

- `power`：电源或开关。
- `temperature`：温度。
- `mode`：模式。
- `fan`：风速或风量。
- `swing`：风向。
- `brightness`：亮度。
- `color_temperature`：色温。
- `color`：颜色。
- `effect`：灯效。
- `query`：状态查询。

灯类设备如果存在 `light` 实体，会优先从 `light` 实体生成开关、亮度、色温、颜色和灯效能力。

空调、风扇、select、number、input helper 会按 domain 和实体属性生成对应能力。

## Script 与 Automation

`automation` 默认不作为可执行能力。

`script` 默认不全量暴露。扫描器会把 script 放入 pending，并只在脚本能明确匹配到已有控制器和能力时自动绑定。

电源脚本有额外严格规则：

- 优先使用 `input_boolean.xxx_power` 或 `switch.xxx_power`。
- 没有 power helper 时，才考虑明确的 power/on/off、开机、关机脚本。
- 含有 strong、quiet、sleep、formaldehyde、aux_heat、swing、fan、mode 等关键词的脚本不会被当作电源绑定。

这样可以降低“关闭空调”误调用“关闭静眠/强力安静/风向”等脚本的风险。

## 安全边界

执行前会经过三层边界：

1. 权限判断：当前用户或群是否允许查询/控制。
2. 匹配判断：是否唯一、明确地匹配到控制器、能力和值。
3. 执行判断：binding 是否属于允许 domain，是否命中危险 domain 或危险实体。

默认允许控制的 domain：

```text
climate
fan
input_boolean
input_number
input_select
light
number
scene
script
select
switch
```

默认屏蔽的危险 domain：

```text
alarm_control_panel
camera
command_line
hassio
lock
python_script
pyscript
rest_command
shell_command
siren
```

## 降级行为

- WebSocket registry 失败：保留 states 扫描结果，房间可能显示为“未分区”，索引中记录 warning。
- 匹配不确定：返回 `need_clarification`，让 Agent 追问。
- 匹配到能力但没有 binding：不执行，返回错误。
- HA service 调用失败：返回失败结果，由 Agent 组织自然语言回复。

## 配置读取

配置支持嵌套结构：

- `basic`
- `advanced`

同时保留部分旧 key 兼容，例如 `ha_url`、`token`。

当前 schema 中的配置项：

- `home_assistant_url`
- `ha_token`
- `confidence_threshold`
- `admin_users`
- `admin_groups`
- `allow_query_without_admin`
- `dangerous_entities`
- `allowed_control_domains`
- `blocked_service_domains`
- `request_timeout`

## 设计原则

- Home Assistant 负责真实设备接入和 service 执行。
- 插件负责把 HA 的实体整理成 AstrBot 可理解的控制器和能力。
- AstrBot Agent 负责理解用户表达并调用 `ha_execute_intent`。
- 不把底层 HA service 工具直接暴露给普通 Agent。
- 不确定、不安全、不唯一时优先追问或拒绝。
