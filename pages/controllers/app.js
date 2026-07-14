console.log("[HA Controller UI] app.js loaded");

let bridge = window.AstrBotPluginPage;
let bridgeContext = null;
let bridgeReadyPromise = null;
let pluginName = "astrbot_plugin_ha_control_layer";

renderBootScreen();

const state = {
  index: { controllers: [], pending: [] },
  rooms: [],
  selectedRoomId: "",
  selectedControllerId: "",
  status: "empty",
  error: "",
  lastScanAt: safeStorageGet("ha_controller_last_scan") || "",
  warnings: [],
  summary: {},
};

async function init() {
  await loadIndex();
}

async function pluginGet(endpoint, params = {}) {
  await ensureBridgeReady();
  if (!bridge?.apiGet) {
    throw new Error("AstrBotPluginPage bridge 不可用，请重载插件页面");
  }
  return bridge.apiGet(trimEndpoint(endpoint), params);
}

async function pluginPost(endpoint, body = {}) {
  await ensureBridgeReady();
  if (!bridge?.apiPost) {
    throw new Error("AstrBotPluginPage bridge 不可用，请重载插件页面");
  }
  return bridge.apiPost(trimEndpoint(endpoint), body);
}

async function ensureBridgeReady() {
  if (bridgeContext) {
    return bridgeContext;
  }
  bridge = window.AstrBotPluginPage;
  if (!bridge?.ready) {
    throw new Error("AstrBotPluginPage bridge 未加载");
  }
  if (!bridgeReadyPromise) {
    bridgeReadyPromise = withTimeout(bridge.ready(), 5000, "AstrBotPluginPage bridge 初始化超时");
  }
  bridgeContext = await bridgeReadyPromise;
  pluginName = bridgeContext?.pluginName || pluginName;
  return bridgeContext;
}

function withTimeout(promise, ms, message) {
  return Promise.race([
    promise,
    new Promise((_, reject) => {
      setTimeout(() => reject(new Error(message)), ms);
    }),
  ]);
}

async function loadIndex() {
  state.status = "loading";
  render();
  try {
    const data = await pluginGet("controllers");
    state.index = normalizeIndex(data);
    state.rooms = buildRooms(state.index.controllers);
    state.status = state.index.controllers.length ? "success" : "empty";
    state.lastScanAt = data?.last_scan_time || state.lastScanAt || "";
    state.warnings = state.index.warnings || [];
    state.summary = state.index.summary || {};
    state.error = "";
  } catch (error) {
    state.status = "failed";
    state.error = `${error?.message || String(error)}。请检查 window.AstrBotPluginPage 是否存在，以及 app.js 是否由 AstrBot Plugin Pages 加载。`;
  }
  render();
}

async function rescan() {
  state.status = "scanning";
  state.error = "";
  render();
  try {
    const result = await pluginPost("rescan", {});
    if (result?.success === false) {
      throw new Error(result.message || "扫描失败");
    }
    state.lastScanAt = new Date().toLocaleString();
    safeStorageSet("ha_controller_last_scan", state.lastScanAt);
    const data = await pluginGet("controllers");
    state.index = normalizeIndex(data);
    state.rooms = buildRooms(state.index.controllers);
    state.lastScanAt = data?.last_scan_time || state.lastScanAt;
    state.warnings = state.index.warnings || [];
    state.summary = state.index.summary || {};
    state.status = "success";
  } catch (error) {
    state.status = "failed";
    state.error = error?.message || String(error);
  }
  render();
}

function render() {
  try {
    renderSideNav();
    if (state.selectedControllerId) {
      renderControllerDetail(state.selectedControllerId);
      return;
    }
    if (state.selectedRoomId) {
      renderRoom(state.selectedRoomId);
      return;
    }
    renderOverview();
  } catch (error) {
    showFatalError(error);
  }
}

function renderBootScreen() {
  const app = document.getElementById("app");
  if (!app) {
    console.error("[HA Controller UI] #app not found during boot");
    return;
  }
  app.innerHTML = `
    <header class="page-header">
      <div>
        <p class="eyebrow">Home Assistant 控制器</p>
        <h1>app.js 已加载</h1>
        <p class="page-subtitle">正在初始化 WebUI。如果停在这里，说明真实 UI 渲染阶段报错。</p>
      </div>
    </header>
  `;
}

function renderSideNav() {
  const root = document.getElementById("sideNav");
  pendingActions.clear();
  const roomLinks = state.rooms
    .map((room) => navButton(room.roomName, `${room.controllers.length} 个控制器`, () => openRoom(room.roomId), state.selectedRoomId === room.roomId))
    .join("");
  root.innerHTML = `
    ${navButton("总览", "扫描状态和房间", () => openOverview(), !state.selectedRoomId && !state.selectedControllerId)}
    <div class="nav-section">房间</div>
    ${roomLinks || '<div class="empty-nav">暂无房间</div>'}
  `;
  bindNavButtons(root);
}

function renderOverview() {
  const app = document.getElementById("app");
  const stats = calculateStats();
  app.innerHTML = `
    <header class="page-header">
      <div>
        <p class="eyebrow">Home Assistant 控制器</p>
        <h1>整理 AstrBot 可理解的家居控制器</h1>
        <p class="page-subtitle">这里不控制设备，只整理控制器、能力和值别名。真正控制仍然发生在聊天入口。</p>
      </div>
    </header>

    <section class="status-card card">
      <div>
        <span class="status-pill ${statusClass()}">${statusText()}</span>
        <h2>${statusHeadline(stats)}</h2>
        <p>${statusDescription(stats)}</p>
      </div>
      <button id="rescan" class="primary-button" type="button">${scanButtonText()}</button>
    </section>

    <section class="stats-grid">
      ${statCard("房间", stats.rooms)}
      ${statCard("控制器", stats.controllers)}
      ${statCard("实体", stats.entities)}
      ${statCard("已暴露", stats.exposedControllers)}
      ${statCard("待整理", stats.pending)}
      ${statCard("隐藏项", stats.hidden)}
    </section>

    <section class="section">
      <div class="section-title">
        <h2>房间</h2>
        <p>控制器指 AstrBot 可以理解和调用的家电或设备，例如卧室空调、客厅灯、冰箱。</p>
      </div>
      <div class="room-grid">
        ${state.rooms.map((room) => roomCard(room)).join("") || emptyState("还没有识别到房间。点击扫描 Home Assistant 后会在这里显示房间。")}
      </div>
    </section>
  `;
  document.getElementById("rescan").addEventListener("click", rescan);
  bindCards(app);
}

function showFatalError(error) {
  const app = document.getElementById("app");
  if (!app) {
    console.error("[HA Controller UI] render failed before #app mounted", error);
    return;
  }
  console.error("[HA Controller UI] render failed", error);
  window.__HA_CONTROLLER_SHOW_ERROR__?.("WebUI 渲染失败", error?.message || String(error));
  if (window.__HA_CONTROLLER_SHOW_ERROR__) {
    return;
  }
  app.innerHTML = `
    <header class="page-header">
      <div>
        <p class="eyebrow">Home Assistant 控制器</p>
        <h1>WebUI 渲染失败</h1>
        <p class="page-subtitle">${escapeHtml(error?.message || String(error))}</p>
      </div>
    </header>
    <section class="status-card card">
      <div>
        <span class="status-pill danger">页面错误</span>
        <h2>app.js 已加载，但渲染过程中报错。</h2>
        <p>请打开浏览器 DevTools Console 查看完整错误。</p>
      </div>
    </section>
  `;
}

function safeStorageGet(key) {
  try {
    return window.localStorage?.getItem(key) || "";
  } catch (error) {
    console.warn("[HA Controller UI] localStorage get failed", error);
    return "";
  }
}

function safeStorageSet(key, value) {
  try {
    window.localStorage?.setItem(key, value);
  } catch (error) {
    console.warn("[HA Controller UI] localStorage set failed", error);
  }
}

function renderRoom(roomId) {
  const room = state.rooms.find((item) => item.roomId === roomId);
  if (!room) {
    openOverview();
    return;
  }
  const app = document.getElementById("app");
  app.innerHTML = `
    ${breadcrumb([{ label: "首页", action: "overview" }, { label: room.roomName }])}
    <header class="page-header">
      <div>
        <p class="eyebrow">${room.roomName === "未分区" ? "未分区" : "来自 Home Assistant Area"}</p>
        <h1>${escapeHtml(room.roomName)}</h1>
        <p class="page-subtitle">${room.controllers.length} 个控制器 · ${room.entityCount} 个实体</p>
      </div>
    </header>
    <section class="controller-grid">
      ${room.controllers.map((controller) => controllerCard(controller)).join("") || emptyState("这个房间没有控制器。")}
    </section>
  `;
  bindCards(app);
  bindBreadcrumb(app);
}

function renderControllerDetail(controllerId) {
  const controller = state.index.controllers.find((item) => item.controller_id === controllerId);
  if (!controller) {
    openOverview();
    return;
  }
  const room = roomForController(controller);
  const normalCaps = controller.capabilities.filter((cap) => !isAdvancedCapability(cap));
  const advancedCaps = controller.capabilities.filter((cap) => isAdvancedCapability(cap));
  const app = document.getElementById("app");
  app.innerHTML = `
    ${breadcrumb([{ label: "首页", action: "overview" }, { label: room.roomName, roomId: room.roomId }, { label: controller.display_name }])}
    <header class="page-header detail-header">
      <div>
        <p class="eyebrow">控制器详情</p>
        <h1>${escapeHtml(controller.display_name)}</h1>
        <p class="page-subtitle">房间：${escapeHtml(room.roomName)} · 来源实体：${sourceEntities(controller).length} 个</p>
      </div>
      <button id="saveController" class="primary-button" type="button">保存当前控制器</button>
    </header>

    <section class="card edit-card" data-controller-id="${escapeAttr(controller.controller_id)}">
      <div class="form-grid">
        <label>控制器显示名 <input data-controller-field="display_name" value="${escapeAttr(controller.display_name)}" /></label>
        <label>控制器别名 <input data-controller-field="aliases" value="${escapeAttr((controller.aliases || []).join(", "))}" placeholder="例如：空调, 冷气, 我房间空调" /></label>
        <label class="toggle-row"><input data-controller-field="exposed" type="checkbox" ${controller.exposed ? "checked" : ""} /> 暴露给 AstrBot</label>
      </div>
    </section>

    <section class="section">
      <div class="section-title">
        <h2>能力</h2>
        <p>展开能力后可以整理名称、别名和值别名。底层实体信息默认收起。</p>
      </div>
      <div class="accordion">
        ${normalCaps.map((cap, index) => capabilityPanel(controller, cap, index === 0)).join("") || emptyState("没有可展示的日常能力。")}
      </div>
    </section>

    ${advancedCaps.length ? `
      <section class="section">
        <details class="card advanced-group">
          <summary>隐藏项 / 高级项 <span>${advancedCaps.length} 项</span></summary>
          <div class="accordion">
            ${advancedCaps.map((cap) => capabilityPanel(controller, cap, false)).join("")}
          </div>
        </details>
      </section>
    ` : ""}

    <section class="section">
      <details class="card advanced-group">
        <summary>控制器高级信息 <span>默认收起</span></summary>
        <dl class="tech-list">
          <dt>controller_id</dt><dd>${escapeHtml(controller.controller_id)}</dd>
          <dt>area_name</dt><dd>${escapeHtml(controller.area_name || "未分区")}</dd>
          <dt>source confidence</dt><dd>${escapeHtml(controller.source?.confidence ?? "未知")}</dd>
          <dt>source entities</dt><dd>${chips(sourceEntities(controller), "mono")}</dd>
        </dl>
      </details>
    </section>
  `;
  document.getElementById("saveController").addEventListener("click", () => saveCurrentController(controller));
  bindBreadcrumb(app);
}

function roomCard(room) {
  const names = room.controllers.slice(0, 4).map((item) => item.display_name).join("、") || "暂无控制器";
  return `
    <article class="card room-card clickable" data-room-id="${escapeAttr(room.roomId)}">
      <div>
        <h3>${escapeHtml(room.roomName)}</h3>
        <p>${room.controllers.length} 个控制器 · ${room.entityCount} 个实体</p>
      </div>
      <div class="chip-row">${chips(room.controllers.slice(0, 6).map((item) => item.display_name))}</div>
      <p class="muted">${escapeHtml(names)}</p>
    </article>
  `;
}

function controllerCard(controller) {
  const caps = controller.capabilities.filter((cap) => !isAdvancedCapability(cap));
  const advancedCount = controller.capabilities.length - caps.length;
  return `
    <article class="card controller-card clickable" data-controller-id="${escapeAttr(controller.controller_id)}">
      <div class="card-head">
        <div>
          <h3>${escapeHtml(controller.display_name)}</h3>
          <p>来源实体：${sourceEntities(controller).length} 个</p>
        </div>
        <span class="expose-badge ${controller.exposed ? "on" : "off"}">${controller.exposed ? "已暴露" : "已隐藏"}</span>
      </div>
      <div class="meta-block">
        <span>别名</span>
        <div class="chip-row">${chips(controller.aliases || [], "soft") || '<span class="muted">无</span>'}</div>
      </div>
      <div class="meta-block">
        <span>能力</span>
        <div class="chip-row">${chips(caps.map((cap) => cap.display_name)) || '<span class="muted">无</span>'}</div>
      </div>
      ${advancedCount ? `<p class="muted">${advancedCount} 个隐藏/高级项已收起</p>` : ""}
    </article>
  `;
}

function capabilityPanel(controller, cap, open) {
  return `
    <details class="cap-panel card" data-capability-id="${escapeAttr(cap.capability_id)}" ${open ? "open" : ""}>
      <summary>
        <span>${escapeHtml(cap.display_name)}</span>
        <small>${cap.exposed ? "已暴露" : "未暴露"} · ${escapeHtml(cap.type || "能力")}</small>
      </summary>
      <div class="cap-body">
        <div class="form-grid compact">
          <label>能力名称 <input data-cap-field="display_name" value="${escapeAttr(cap.display_name)}" /></label>
          <label>能力别名 <input data-cap-field="aliases" value="${escapeAttr((cap.aliases || []).join(", "))}" placeholder="例如：风量, 开关" /></label>
          <label class="toggle-row"><input data-cap-field="exposed" type="checkbox" ${cap.exposed ? "checked" : ""} /> 暴露给 AstrBot</label>
        </div>
        ${valueAliasEditor(cap)}
        <details class="tech-details">
          <summary>高级信息</summary>
          <dl class="tech-list">
            <dt>capability_id</dt><dd>${escapeHtml(cap.capability_id)}</dd>
            <dt>entity_id</dt><dd>${escapeHtml(cap.entity_id || "")}</dd>
            <dt>domain</dt><dd>${escapeHtml(cap.domain || "")}</dd>
            <dt>service</dt><dd>${escapeHtml(cap.service || "")}</dd>
            <dt>binding</dt><dd><code>${escapeHtml(JSON.stringify(cap.binding || {}, null, 2))}</code></dd>
            <dt>values</dt><dd><code>${escapeHtml(JSON.stringify((cap.values || []).map((item) => ({ value: item.value, binding: item.binding })), null, 2))}</code></dd>
          </dl>
        </details>
      </div>
    </details>
  `;
}

function valueAliasEditor(cap) {
  const values = cap.values || [];
  if (!values.length) {
    return '<p class="muted">这个能力没有可选值。</p>';
  }
  return `
    <div class="value-list">
      <h4>值别名</h4>
      ${values.map((value) => `
        <div class="value-row" data-value-id="${escapeAttr(value.value)}">
          <span class="value-chip">${escapeHtml(value.display_name)}</span>
          <input data-value-field="aliases" value="${escapeAttr((value.aliases || []).join(", "))}" placeholder="别名，用逗号分隔" />
        </div>
      `).join("")}
    </div>
  `;
}

async function saveCurrentController(controller) {
  const detail = document.querySelector("[data-controller-id]");
  const saveButton = document.getElementById("saveController");
  saveButton.disabled = true;
  saveButton.textContent = "保存中";
  try {
    await pluginPost(`controllers/${encodeURIComponent(controller.controller_id)}`, readControllerEdit(detail));
    for (const panel of document.querySelectorAll("[data-capability-id]")) {
      const capabilityId = panel.dataset.capabilityId;
      await pluginPost(`controllers/${encodeURIComponent(controller.controller_id)}/capabilities/${encodeURIComponent(capabilityId)}`, readCapabilityEdit(panel));
      for (const row of panel.querySelectorAll("[data-value-id]")) {
        await pluginPost(
          `controllers/${encodeURIComponent(controller.controller_id)}/capabilities/${encodeURIComponent(capabilityId)}/values/${encodeURIComponent(row.dataset.valueId)}`,
          { aliases: splitAliases(row.querySelector('[data-value-field="aliases"]').value) },
        );
      }
    }
    saveButton.textContent = "已保存";
    await refreshAfterSave(controller.controller_id);
  } catch (error) {
    saveButton.textContent = `保存失败：${error?.message || error}`;
  } finally {
    setTimeout(() => {
      saveButton.disabled = false;
      saveButton.textContent = "保存当前控制器";
    }, 1400);
  }
}

async function refreshAfterSave(controllerId) {
  const data = await pluginGet("controllers");
  state.index = normalizeIndex(data);
  state.rooms = buildRooms(state.index.controllers);
  state.selectedControllerId = controllerId;
  render();
}

function readControllerEdit(root) {
  return {
    display_name: root.querySelector('[data-controller-field="display_name"]').value.trim(),
    aliases: splitAliases(root.querySelector('[data-controller-field="aliases"]').value),
    exposed: Boolean(root.querySelector('[data-controller-field="exposed"]').checked),
  };
}

function readCapabilityEdit(root) {
  return {
    display_name: root.querySelector('[data-cap-field="display_name"]').value.trim(),
    aliases: splitAliases(root.querySelector('[data-cap-field="aliases"]').value),
    exposed: Boolean(root.querySelector('[data-cap-field="exposed"]').checked),
  };
}

function normalizeIndex(data) {
  return {
    controllers: Array.isArray(data?.controllers) ? data.controllers : [],
    pending: Array.isArray(data?.pending) ? data.pending : [],
    warnings: Array.isArray(data?.warnings) ? data.warnings : [],
    summary: data?.summary && typeof data.summary === "object" ? data.summary : {},
    last_scan_time: data?.last_scan_time || "",
    scan_status: data?.scan_status || "",
  };
}

function buildRooms(controllers) {
  const groups = new Map();
  for (const controller of controllers) {
    const name = controller.area_name || "未分区";
    const id = controller.area_id || slugify(name);
    if (!groups.has(id)) {
      groups.set(id, { roomId: id, roomName: name, controllers: [], entityCount: 0 });
    }
    const room = groups.get(id);
    room.controllers.push(controller);
    room.entityCount += sourceEntities(controller).length;
  }
  return [...groups.values()].sort((a, b) => {
    if (a.roomName === "未分区") return 1;
    if (b.roomName === "未分区") return -1;
    return a.roomName.localeCompare(b.roomName, "zh-CN");
  });
}

function calculateStats() {
  const controllers = state.index.controllers;
  const capabilities = controllers.flatMap((controller) => controller.capabilities || []);
  return {
    rooms: state.rooms.length,
    controllers: controllers.length,
    entities: controllers.reduce((total, controller) => total + sourceEntities(controller).length, 0),
    exposedControllers: controllers.filter((controller) => controller.exposed).length,
    exposedCapabilities: capabilities.filter((cap) => cap.exposed).length,
    pending: state.index.pending.length,
    hidden: controllers.filter((controller) => !controller.exposed).length + capabilities.filter((cap) => !cap.exposed || isAdvancedCapability(cap)).length,
  };
}

function sourceEntities(controller) {
  return Array.isArray(controller.source?.entities) ? controller.source.entities : [];
}

function roomForController(controller) {
  return state.rooms.find((room) => room.controllers.some((item) => item.controller_id === controller.controller_id)) || {
    roomId: "unknown",
    roomName: "未分区",
  };
}

function isAdvancedCapability(cap) {
  const text = `${cap.display_name || ""} ${cap.capability_id || ""} ${cap.entity_id || ""}`.toLowerCase();
  return [
    "功能设置",
    "参数重置",
    "默认上电",
    "遥控器",
    "添加遥控器",
    "删除遥控器",
    "dimming",
    "factory_reset",
    "default_power",
    "diagnostic",
    "config",
    "sync",
    "同步",
  ].some((keyword) => text.includes(keyword.toLowerCase()));
}

function statusText() {
  return {
    loading: "加载中",
    scanning: "扫描中",
    success: "扫描成功",
    failed: "扫描失败",
    empty: "尚未扫描",
  }[state.status] || "未知";
}

function statusClass() {
  return {
    loading: "pending",
    scanning: "pending",
    success: "success",
    failed: "danger",
    empty: "neutral",
  }[state.status] || "neutral";
}

function statusHeadline(stats) {
  if (state.status === "success") {
    return `发现 ${stats.rooms} 个房间、${stats.controllers} 个控制器、${stats.entities} 个实体。`;
  }
  if (state.status === "failed") {
    return `扫描失败：${escapeHtml(state.error || "无法加载控制器索引")}`;
  }
  if (state.status === "scanning") {
    return "正在从 Home Assistant 重新扫描。";
  }
  if (state.status === "empty") {
    return "尚未扫描到控制器。";
  }
  return "正在加载控制器索引。";
}

function statusDescription() {
  if (state.status === "failed") {
    return "请检查 HA 地址、Token、网络连接，或查看 AstrBot 后台日志。";
  }
  if (state.warnings.length) {
    return `上次扫描时间：${state.lastScanAt || "未知"} · ${state.warnings[0]}`;
  }
  if (state.status === "loading") {
    return "正在读取已保存索引，不会重新扫描 Home Assistant。";
  }
  return `上次扫描时间：${state.lastScanAt || "未知"}`;
}

function scanButtonText() {
  if (state.status === "scanning") {
    return "扫描中";
  }
  if (state.status === "success") {
    return "重新扫描";
  }
  if (state.status === "failed") {
    return "重试扫描";
  }
  return "扫描 Home Assistant";
}

function statCard(label, value) {
  return `<article class="stat-card card"><span>${label}</span><strong>${value}</strong></article>`;
}

function breadcrumb(items) {
  return `
    <nav class="breadcrumb">
      ${items.map((item) => item.action || item.roomId ? `<button type="button" data-breadcrumb="${escapeAttr(item.action || "")}" data-room-id="${escapeAttr(item.roomId || "")}">${escapeHtml(item.label)}</button>` : `<span>${escapeHtml(item.label)}</span>`).join("<span>/</span>")}
    </nav>
  `;
}

function bindBreadcrumb(root) {
  for (const button of root.querySelectorAll("[data-breadcrumb], [data-room-id]")) {
    button.addEventListener("click", () => {
      if (button.dataset.breadcrumb === "overview") {
        openOverview();
      } else if (button.dataset.roomId) {
        openRoom(button.dataset.roomId);
      }
    });
  }
}

function navButton(title, subtitle, action, active) {
  const id = `nav_${Math.random().toString(36).slice(2)}`;
  pendingActions.set(id, action);
  return `
    <button class="nav-item ${active ? "active" : ""}" type="button" data-action-id="${id}">
      <span>${escapeHtml(title)}</span>
      <small>${escapeHtml(subtitle)}</small>
    </button>
  `;
}

const pendingActions = new Map();

function bindNavButtons(root) {
  for (const button of root.querySelectorAll("[data-action-id]")) {
    button.addEventListener("click", () => pendingActions.get(button.dataset.actionId)?.());
  }
}

function bindCards(root) {
  for (const card of root.querySelectorAll("[data-room-id]")) {
    card.addEventListener("click", () => openRoom(card.dataset.roomId));
  }
  for (const card of root.querySelectorAll("[data-controller-id]")) {
    if (card.matches(".edit-card")) continue;
    card.addEventListener("click", () => openController(card.dataset.controllerId));
  }
}

function openOverview() {
  state.selectedRoomId = "";
  state.selectedControllerId = "";
  render();
}

function openRoom(roomId) {
  state.selectedRoomId = roomId;
  state.selectedControllerId = "";
  render();
}

function openController(controllerId) {
  state.selectedControllerId = controllerId;
  render();
}

function chips(values, variant = "") {
  return (values || [])
    .filter(Boolean)
    .map((value) => `<span class="chip ${variant}">${escapeHtml(value)}</span>`)
    .join("");
}

function emptyState(text) {
  return `<div class="empty-state">${escapeHtml(text)}</div>`;
}

function splitAliases(value) {
  return String(value || "")
    .split(/[,，、]/)
    .map((item) => item.trim())
    .filter(Boolean);
}

function trimEndpoint(endpoint) {
  return String(endpoint || "").replace(/^\/+/, "");
}

function slugify(value) {
  return String(value || "unknown").replace(/\s+/g, "_");
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function escapeAttr(value) {
  return escapeHtml(value).replaceAll("'", "&#39;");
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", init, { once: true });
} else {
  init();
}
