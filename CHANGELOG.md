# Changelog

## v1.1.9

- Treat room/area words in user requests as strong matching constraints, reducing cross-room device mistakes.
- Ask for clarification when multiple same-type controllers match equally well and the user did not mention a room.
- Improve room environment matching for temperature, humidity, and temperature/humidity summary queries.
- Keep Home Assistant execution unchanged; this release only adjusts intent matching and packaging metadata.

## v1.1.8

- Add a read-only `ha_query_weather` LLM tool so weather questions can prefer Home Assistant instead of web search.
- Try `daily` weather forecasts first and fall back to `hourly` forecasts when needed.
- Detect room temperature and humidity sensors during scanning and group them into room environment controllers.
- Improve natural-language matching for room temperature, humidity, and temperature/humidity summary queries.

## v1.1.7

- Restore Home Assistant weather queries through the single `ha_execute_intent` entry point.
- Add `weather` entities to the controller index as query-only capabilities.
- Support current weather through `GET /api/states/{entity_id}`.
- Support forecast queries through Home Assistant `weather.get_forecasts`.
- Ask for clarification when multiple weather entities match a generic weather query.

## v1.1.6

- Update marketplace identity to `astrbot_plugin_ha_control_layer`.
- Update author to `Xhan258`.
- Update repository URL to `https://github.com/Xhan258/astrbot_plugin_ha_control_layer`.
- Keep `home_assistant_control_layer` as a legacy Plugin Page/API compatibility name only.

## v1.1.4

- Restore compatibility with AstrBot v4.25.6 by removing import-time dependency on `astrbot.api.web`.
- Return plain dictionaries from Plugin Page APIs so older Dashboard versions can load the plugin.
- Read page POST JSON with a compatibility path: new `astrbot.api.web` when present, otherwise Quart request.

## v1.1.3

- Rewrite the Plugin Page frontend to follow AstrBot Plugin Pages docs exactly.
- Explicitly load `/api/plugin/page/bridge-sdk.js` before the page module.
- Use `type="module"` for the page script.
- Remove direct `fetch` fallback from the iframe page; all Dashboard API calls now go through `bridge.apiGet` and `bridge.apiPost`.
- Return page API responses through `astrbot.api.web.json_response`.

## v1.1.2

- Rename the plugin display name from AI管家 to Home Assistant 控制器.

## v1.1.1

- Rename the plugin display name to AI管家.
- Fix Plugin Page API registration to use AstrBot's documented `register_web_api(route, handler, methods, desc)` signature.
- Fix the Plugin Page frontend to use `window.AstrBotPluginPage.ready()`, `apiGet`, and `apiPost` instead of direct iframe fetch calls.
- Add POST-compatible save endpoints for controller, capability, and value-alias edits.

## v1.1.0

- Rebuild the plugin around `ControllerIndex + IntentMatcher + SafeExecutor`.
- Expose only one ordinary LLM tool: `ha_execute_intent`.
- Stop exposing low-level HA service/list/state tools to the Agent.
- Add generated/overrides index storage so rescans do not overwrite user整理结果.
- Add an embedded AstrBot Plugin Page for controller, capability, and value-alias整理.
- Keep the page as an index editor only: no device control buttons, no sliders, no service test box.
- Auto-group common HA helpers into controllers, including AC input_select/input_boolean plus matching power scripts.
- Ignore automation as control ability by default, and keep uncertain scripts in pending.
- Add generic light capabilities for power, brightness, and color temperature when HA exposes them.
- Verify AC power, temperature, mode, fan alias, fridge select, light warm color, and temperature query flows with a fake HA client.

## v1.0.4

- Infer feature targets when the user omits the device, such as “开成制冷模式” and “风速开到自然风”.
- Map common option aliases, including “自然风” -> “自由风”.
- Fix feature switch ranking so “风向打开” controls the wind-direction helper instead of accidentally triggering AC power-on.
- Require script-service fallback candidates to match the target/feature, reducing accidental power script execution.
- Add tests for omitted-device mode control, wind direction, and fan-speed alias behavior.

## v1.0.3

- Add generic value/option execution inside `ha_execute_intent`.
- Support `select` and `input_select` option matching, such as AC temperature `25℃`, AC mode `除湿`, and fridge zone `蛋类`.
- Support `number`/`input_number` value setting and standard `climate.set_temperature` candidates.
- Add request-specific filtering so temperature commands prefer temperature entities, mode commands prefer mode entities, and unrelated select entities are not executed.
- Fix script service discovery for Home Assistant's raw `/api/services` dict shape.
- Add end-to-end fake Home Assistant tests for temperature, mode, fridge option, power off, and query-no-execute behavior.

## v1.0.2

- Make `ha_execute_intent` execute high-confidence Home Assistant control actions internally, so the Agent no longer needs a second `ha_call_service` tool call.
- Return `executed=true` with the HA execution result, allowing the Agent to only compose a natural reply.
- Fetch Home Assistant weather forecasts internally instead of requiring a second tool call.
- Keep query/question/negative messages from auto-executing.
- Reduce the chance of Agent bypassing the plugin through shell, Python, file reads, or manual token handling.

## v1.0.1

- Improve intent context ranking so actionable scripts, switches, lights, climate entities, and helpers are preferred over sync automations.
- Add `suggested_calls` to `ha_execute_intent`, giving the Agent a direct next `ha_call_service` candidate instead of repeatedly asking for more context.
- Add the same `next_step` guidance to Home Assistant weather forecasts so the Agent can fetch forecasts and then phrase the reply naturally.
- Allow concrete Home Assistant script services such as `script.bedroom_ac_power_off` to run without forcing a fake `entity_id`.
- Stop dumping unrelated service domains when no entity matched.
- Add small colloquial target cleanup such as “我屋空调” -> “卧室空调”.

## v1.0.0

- Rebuild the core as a Hermes-style Home Assistant context and safe service layer.
- Remove remote-control style LLM tools: `ha_control_device`, `ha_climate_control`, `ha_select_option`, `ha_schedule_action`, and scene/script shortcut tools.
- Keep default tools focused on discovery and execution: `ha_execute_intent`, `ha_list_entities`, `ha_get_state`, `ha_list_services`, and `ha_call_service`.
- Make `ha_execute_intent` prepare entity/state/service context instead of guessing fixed device actions.
- Remove user-facing schedule-script setup flow from the README and settings.

## v0.8.0

- Remove the old third-party delay integration path and related settings.
- Add automatic Home Assistant schedule script installation through `/ha_install_schedule` and on first timed home command.
- Make `/ha_check_schedule` check and install the schedule script automatically.
- Simplify the plugin settings page to connection, optional weather/aliases, and essential safety controls.
- Keep YAML script output only as a manual fallback via `/ha_schedule_template`.

## v0.7.4

- Replace the README with a short user-facing guide focused on what to say, first setup, scheduling setup, and common commands.
- Remove the README table of contents and developer-facing explanations from the plugin help view.

## v0.7.3

- Rewrite the README into a clearer release-style structure: capabilities first, then quick start, scheduling, configuration, commands, and notes.
- Remove user-facing references to the unfinished dedicated HA scheduler idea.
- Simplify the default HA schedule script template to start-only delayed execution.
- Stop reporting scheduling success when the configured HA script entity is missing.
- Make scheduling rely on the HA script backend.

## v0.7.2

- Add a tool-route guard for home scheduling: when the Agent tries to use `future_task`, reminders, tasks, or cron for delayed home control, the plugin returns a tool result telling it to call `ha_execute_intent` instead.
- Keep normal user messages flowing through the Agent; the new guard works at tool-call time rather than acting like a remote-control message interceptor.
- Add `guard_home_schedule_tools` as a basic setting, enabled by default.
- Move message-level timed-intent interception to the advanced fallback setting `protect_timed_home_intents`.

## v0.7.1

- Relax timed home-intent interception now that reminder/task plugins are optional.
- Change `protect_timed_home_intents` default to off so normal delayed home commands can flow through the Agent and HA control-layer tool.
- When the protection is enabled, ignore follow-up confirmation questions such as “你确定真设置了吗” instead of treating them as new device-control commands.

## v0.7.0

- Rename the plugin card to `Home Assistant 控制层` and refresh the user-facing description.
- Rework `_conf_schema.json` into `普通设置` and `高级设置`, keeping only connection, weather, schedule script, timed-intent protection, and optional aliases in the basic section.
- Add `protect_timed_home_intents` so delayed home commands such as “一分钟后关空调” are caught by the HA control layer before reminder/task tools claim them.
- Keep nested config compatible with older flat config keys.
- Update the README around first-run setup, schedule script setup, and the control-layer positioning.

## v0.6.1

- Rebuild the upload package as a flat AstrBot-compatible archive to avoid upload extraction failures in AstrBot v4.25.x.

## v0.6.0

- Add `ha_execute_intent` as the default single LLM entry point for Home Assistant requests.
- Hide advanced HA LLM tools by default behind `expose_advanced_llm_tools`, while keeping `/ha_xxx` debug commands.
- Route natural-language home intents internally to state query, device control, climate control, select option, weather, scene/script/automation, or HA scheduling.
- Convert intercepted HA shell/curl/sleep attempts into guarded HA control-layer calls when possible instead of only returning a warning.
- Stop direct shell-bypass chat notices by default so the Agent remains responsible for natural replies.
- Tighten script-style device classification so feature scripts such as fan direction or formaldehyde modes are not grouped as power scripts.

## v0.5.0

- Add Hermes-style `ha_get_overview` and `/ha_overview` for compact Home Assistant inventory, domain summaries, and script-device hints.
- Add structured disambiguation results for entity searches and state queries so the Agent can ask a clarifying question instead of guessing.
- Add shell-bypass guard: HA-related shell/curl/sleep attempts are neutralized and redirected back to HA tools.
- Enrich entity summaries with logical device hints for script-style devices.

## v0.4.0

- Change default behavior back to control-layer mode: natural-language direct select/control interception is now disabled by default, so Agent keeps intent understanding and reply composition.
- Return structured JSON for control tools with a concise `message`, execution metadata, and `recent_action` context for the Agent.
- Add short-term in-memory action context so follow-up queries can see recent HA actions and avoid contradicting freshly executed controls.
- Support script-style AC setups backed by `input_select/select` helpers for temperature, mode, fan, and swing when no standard `climate.*` entity is available.
- Add `input_select`, `input_boolean`, `button`, `input_button`, `number`, and `input_number` as supported HA control domains.

## v0.3.2

- Add direct handling for clear home on/off intents such as “打开卧室空调” and “一分钟后关空调”.
- Add script-device discovery for remote-control style devices, mapping scripts such as “卧室空调-开机/关机” to logical on/off actions.
- Keep standard entities such as `climate.*` as the first choice; script-device discovery is a fallback.
- Schedule script-device actions through `ha_schedule_action` instead of shell `sleep`/`curl`.

## v0.3.1

- Disable natural-language weather interception by default so the Agent can use HA data and compose the reply.
- Parse Home Assistant `service_response` wrappers from `weather.get_forecasts`.
- Add `/ha_state <target> [domain]` as a real manual state-query command.

## v0.3.0

- Add `/ha_schedule_template` for manual HA schedule script fallback.
- Add `/ha_check_schedule` and selectable schedule backends.
- Add an early experimental third-party delay backend. Removed in v0.8.0.
- Add `ha_weather_forecast`, `/ha_weather`, HA weather query interception, and `weather.get_forecasts` service-response support.
- Treat `allowed_query_services` such as `weather.get_forecasts` as query operations instead of device control.

## v0.2.0

- Replace per-device `timer_bindings` with one Home Assistant schedule script entry point.
- Rename `ha_schedule_timer` to `ha_schedule_action`.
- Send scheduled action variables to HA: operation, schedule_key, target entity, service, delay, and service_data.

## v0.1.5

- Add Hermes-style HA tools: `ha_list_entities`, `ha_get_state`, and `ha_list_services`.
- Make `ha_call_service` usable as a guarded generic Home Assistant service caller.
- Block dangerous service domains and require explicit entity targets for generic calls by default.

## v0.1.4

- Add direct handling for clear Home Assistant `select` option intents such as “把珍品变温从熟食改成蛋类”.
- Add `/ha_select <target> <option>` as a no-Agent fallback command.
- Keep failed HA tool calls visible to the current chat.
