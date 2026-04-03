const state = {
  page: 1,
  rows: 4,
  columns: 8,
  includeEmpty: false,
  selected: null,
  lastInventory: null,
  activity: [],
};

const els = {
  page: document.querySelector("#page"),
  rows: document.querySelector("#rows"),
  columns: document.querySelector("#columns"),
  includeEmpty: document.querySelector("#include-empty"),
  refreshGrid: document.querySelector("#refresh-grid"),
  pageGrid: document.querySelector("#page-grid"),
  healthDot: document.querySelector("#health-dot"),
  healthStatus: document.querySelector("#health-status"),
  healthDetail: document.querySelector("#health-detail"),
  targetHost: document.querySelector("#target-host"),
  targetDetail: document.querySelector("#target-detail"),
  selectedCoords: document.querySelector("#selected-coords"),
  buttonPreview: document.querySelector("#button-preview"),
  buttonSummary: document.querySelector("#button-summary"),
  pressVerified: document.querySelector("#press-verified"),
  refreshButton: document.querySelector("#refresh-button"),
  styleForm: document.querySelector("#style-form"),
  styleText: document.querySelector("#style-text"),
  styleColor: document.querySelector("#style-color"),
  styleBgcolor: document.querySelector("#style-bgcolor"),
  styleSize: document.querySelector("#style-size"),
  styleWaitMs: document.querySelector("#style-wait-ms"),
  stylePollMs: document.querySelector("#style-poll-ms"),
  snapshotName: document.querySelector("#snapshot-name"),
  snapshotList: document.querySelector("#snapshot-list"),
  saveSnapshot: document.querySelector("#save-snapshot"),
  loadSnapshot: document.querySelector("#load-snapshot"),
  diffSnapshot: document.querySelector("#diff-snapshot"),
  deleteSnapshot: document.querySelector("#delete-snapshot"),
  previewRestoreAll: document.querySelector("#preview-restore-all"),
  restoreAll: document.querySelector("#restore-all"),
  previewRestoreSelected: document.querySelector("#preview-restore-selected"),
  restoreSelected: document.querySelector("#restore-selected"),
  presetName: document.querySelector("#preset-name"),
  presetList: document.querySelector("#preset-list"),
  savePreset: document.querySelector("#save-preset"),
  previewPreset: document.querySelector("#preview-preset"),
  applyPreset: document.querySelector("#apply-preset"),
  deletePreset: document.querySelector("#delete-preset"),
  transactionName: document.querySelector("#transaction-name"),
  applyTransaction: document.querySelector("#apply-transaction"),
  rollbackTransaction: document.querySelector("#rollback-transaction"),
  searchQuery: document.querySelector("#search-query"),
  runSearch: document.querySelector("#run-search"),
  searchResults: document.querySelector("#search-results"),
  lastResponse: document.querySelector("#last-response"),
  activityLog: document.querySelector("#activity-log"),
};

function setLastResponse(payload) {
  els.lastResponse.textContent = JSON.stringify(payload, null, 2);
  state.activity.unshift({
    at: new Date().toISOString(),
    ok: payload?.ok,
    summary: payload?.error || payload?.action || payload?.path || payload?.probe_path || "response",
  });
  state.activity = state.activity.slice(0, 25);
  els.activityLog.textContent = JSON.stringify(state.activity, null, 2);
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: {"Content-Type": "application/json"},
    ...options,
  });
  const payload = await response.json();
  setLastResponse(payload);
  return payload;
}

function currentGridQuery() {
  return new URLSearchParams({
    page: String(state.page),
    rows: String(state.rows),
    columns: String(state.columns),
    include_empty: state.includeEmpty ? "1" : "0",
  });
}

function renderGridButton(button) {
  const element = document.createElement("button");
  element.className = "grid-button";
  const selected = state.selected &&
    button.page === state.selected.page &&
    button.row === state.selected.row &&
    button.column === state.selected.column;
  if (selected) element.classList.add("selected");

  const text = button.style_meta?.text || button.control_id || "Empty";
  const controlType = button.control?.config?.type || button.control_type || "empty";
  const preview = button.preview?.image;
  element.innerHTML = `
    ${preview ? `<img src="${preview}" alt="">` : ""}
    <strong>${text}</strong>
    <small>${button.row}/${button.column}</small>
  `;
  element.addEventListener("click", () => selectButton(button));
  return element;
}

function renderPreview(button) {
  const image = button.preview?.image;
  if (!image) {
    els.buttonPreview.textContent = "No preview available";
    return;
  }
  els.buttonPreview.innerHTML = `<img src="${image}" alt="Preview">`;
}

function syncStyleForm(button) {
  const style = button.style_meta || {};
  els.styleText.value = style.text || "";
  els.styleColor.value = style.color != null ? String(style.color).padStart(6, "0") : "";
  els.styleBgcolor.value = style.bgcolor != null ? String(style.bgcolor).padStart(6, "0") : "";
  els.styleSize.value = style.size || "";
}

async function selectButton(button) {
  state.selected = {page: button.page, row: button.row, column: button.column};
  els.selectedCoords.textContent = `P${button.page} R${button.row} C${button.column}`;
  renderPreview(button);
  syncStyleForm(button);

  const runtime = await api(`/api/button/runtime?page=${button.page}&row=${button.row}&column=${button.column}`);
  els.buttonSummary.textContent = JSON.stringify({
    info: button,
    runtime,
  }, null, 2);
  await refreshGrid(false);
}

async function refreshHealth() {
  const config = await api("/api/config");
  const health = await api("/api/health");
  els.targetHost.textContent = `${config.host}:${config.port}`;
  els.targetDetail.textContent = config.write_enabled ? "Read / Write" : "Read Only";
  const ok = health.ok;
  els.healthStatus.textContent = ok ? "Online" : "Offline";
  els.healthDot.className = `indicator ${ok ? "ok" : "err"}`;
  els.healthDetail.textContent = `${health.status_code || "?"} ${health.app_info?.body || ""}`.trim();
}

async function refreshGrid(selectFirst = true) {
  state.page = Number(els.page.value);
  state.rows = Number(els.rows.value);
  state.columns = Number(els.columns.value);
  state.includeEmpty = els.includeEmpty.checked;
  const payload = await api(`/api/page?${currentGridQuery().toString()}`);
  state.lastInventory = payload;
  els.pageGrid.style.gridTemplateColumns = `repeat(${state.columns}, 1fr)`;
  els.pageGrid.innerHTML = "";
  const buttons = payload.buttons || [];
  buttons.forEach((button) => els.pageGrid.appendChild(renderGridButton(button)));
  if (selectFirst && buttons.length && !state.selected) {
    await selectButton(buttons[0]);
  }
}

function renderSearchResults(payload) {
  const matches = payload.matches || [];
  if (!matches.length) {
    els.searchResults.textContent = JSON.stringify(payload, null, 2);
    return;
  }
  els.searchResults.innerHTML = "";
  matches.forEach((match) => {
    const row = document.createElement("div");
    row.className = "search-result";
    row.innerHTML = `
      <strong>${match.style_meta?.text || match.control_id || "Unnamed"}</strong>
      <small>P${match.page} R${match.row} C${match.column} · ${match.control_type || "?"}</small>
    `;
    row.addEventListener("click", async () => {
      const payload = await api(`/api/button?page=${match.page}&row=${match.row}&column=${match.column}`);
      await selectButton(payload.body || payload);
    });
    els.searchResults.appendChild(row);
  });
}

async function refreshSnapshots() {
  const payload = await api("/api/snapshots");
  els.snapshotList.innerHTML = "";
  for (const item of payload.snapshots || []) {
    const option = document.createElement("option");
    option.value = item.name;
    option.textContent = item.name;
    els.snapshotList.appendChild(option);
  }
}

async function refreshPresets() {
  const payload = await api("/api/presets");
  els.presetList.innerHTML = "";
  for (const item of payload.presets || []) {
    const option = document.createElement("option");
    option.value = item.name;
    option.textContent = item.name;
    els.presetList.appendChild(option);
  }
}

function selectedCoords() {
  if (!state.selected) throw new Error("Select a button first.");
  return state.selected;
}

async function saveSnapshot() {
  await api("/api/snapshots/save", {
    method: "POST",
    body: JSON.stringify({
      name: els.snapshotName.value || `page-${state.page}`,
      page: state.page, rows: state.rows, columns: state.columns,
      include_empty: state.includeEmpty,
    }),
  });
  await refreshSnapshots();
}

async function savePreset() {
  await api("/api/presets/save", {
    method: "POST",
    body: JSON.stringify({
      name: els.presetName.value || `page-${state.page}`,
      page: state.page, rows: state.rows, columns: state.columns,
      include_empty: state.includeEmpty,
    }),
  });
  await refreshPresets();
}

async function applyVerifiedStyle(event) {
  event.preventDefault();
  const {page, row, column} = selectedCoords();
  await api("/api/button/style-verified", {
    method: "POST",
    body: JSON.stringify({
      page, row, column,
      text: els.styleText.value,
      color: els.styleColor.value,
      bgcolor: els.styleBgcolor.value,
      size: els.styleSize.value,
      wait_ms: Number(els.styleWaitMs.value),
      poll_ms: Number(els.stylePollMs.value),
    }),
  });
  await refreshGrid(false);
}

async function pressVerified() {
  const {page, row, column} = selectedCoords();
  await api("/api/button/press-verified", {
    method: "POST",
    body: JSON.stringify({page, row, column, wait_ms: 1000, poll_ms: 200}),
  });
  await refreshGrid(false);
}

async function previewPreset() {
  await api("/api/presets/preview-apply", {
    method: "POST",
    body: JSON.stringify({
      name: els.presetList.value,
      page: state.page, origin_row: 0, origin_column: 0,
    }),
  });
}

async function applyPreset() {
  await api("/api/presets/apply", {
    method: "POST",
    body: JSON.stringify({
      name: els.presetList.value,
      page: state.page, origin_row: 0, origin_column: 0,
      wait_ms: 1000, poll_ms: 200,
    }),
  });
  await refreshGrid(false);
}

async function deleteSnapshot() {
  await api(`/api/snapshots?name=${encodeURIComponent(els.snapshotList.value)}`, {method: "DELETE"});
  await refreshSnapshots();
}

async function deletePreset() {
  await api(`/api/presets?name=${encodeURIComponent(els.presetList.value)}`, {method: "DELETE"});
  await refreshPresets();
}

async function loadSnapshot() {
  const payload = await api(`/api/snapshots/load?name=${encodeURIComponent(els.snapshotList.value)}`);
  els.searchResults.textContent = JSON.stringify(payload, null, 2);
}

async function diffSnapshot() {
  const payload = await api("/api/snapshots/diff-current", {
    method: "POST",
    body: JSON.stringify({
      name: els.snapshotList.value,
      page: state.page, rows: state.rows, columns: state.columns,
      include_empty: state.includeEmpty,
    }),
  });
  els.searchResults.textContent = JSON.stringify(payload.diff || payload, null, 2);
}

async function previewRestoreSnapshot(selectedOnly) {
  const selected = selectedOnly ? selectedCoords() : {};
  const payload = await api("/api/snapshots/preview-restore", {
    method: "POST",
    body: JSON.stringify({
      name: els.snapshotList.value,
      selected_only: selectedOnly,
      ...selected,
    }),
  });
  els.searchResults.textContent = JSON.stringify(payload, null, 2);
}

async function restoreSnapshot(selectedOnly) {
  const selected = selectedOnly ? selectedCoords() : {};
  await api("/api/snapshots/restore", {
    method: "POST",
    body: JSON.stringify({
      name: els.snapshotList.value,
      selected_only: selectedOnly,
      ...selected,
      wait_ms: 1000, poll_ms: 200,
    }),
  });
  await refreshGrid(false);
}

async function runSearch() {
  const payload = await api(`/api/search?${new URLSearchParams({
    query: els.searchQuery.value,
    page: String(state.page),
    rows: String(state.rows),
    columns: String(state.columns),
    include_empty: state.includeEmpty ? "1" : "0",
  }).toString()}`);
  renderSearchResults(payload);
}

async function applyTransaction() {
  const {row, column} = selectedCoords();
  await api("/api/transactions/apply", {
    method: "POST",
    body: JSON.stringify({
      snapshot_name: els.transactionName.value || `txn-page-${state.page}`,
      page: state.page, rows: state.rows, columns: state.columns,
      styles: [{
        row, column,
        text: els.styleText.value,
        color: els.styleColor.value,
        bgcolor: els.styleBgcolor.value,
        size: els.styleSize.value,
      }],
      wait_ms: 1000, poll_ms: 200,
    }),
  });
  await refreshSnapshots();
  await refreshGrid(false);
}

async function rollbackTransaction() {
  await api("/api/transactions/rollback", {
    method: "POST",
    body: JSON.stringify({
      snapshot_name: els.transactionName.value || `txn-page-${state.page}`,
      wait_ms: 1000, poll_ms: 200,
    }),
  });
  await refreshGrid(false);
}

function bind() {
  els.refreshGrid.addEventListener("click", () => refreshGrid(false));
  els.refreshButton.addEventListener("click", () => {
    if (state.selected) {
      api(`/api/button?page=${state.selected.page}&row=${state.selected.row}&column=${state.selected.column}`)
        .then(selectButton);
    }
  });
  els.pressVerified.addEventListener("click", () => pressVerified());
  els.styleForm.addEventListener("submit", applyVerifiedStyle);
  els.saveSnapshot.addEventListener("click", saveSnapshot);
  els.loadSnapshot.addEventListener("click", loadSnapshot);
  els.diffSnapshot.addEventListener("click", diffSnapshot);
  els.deleteSnapshot.addEventListener("click", deleteSnapshot);
  els.previewRestoreAll.addEventListener("click", () => previewRestoreSnapshot(false));
  els.restoreAll.addEventListener("click", () => restoreSnapshot(false));
  els.previewRestoreSelected.addEventListener("click", () => previewRestoreSnapshot(true));
  els.restoreSelected.addEventListener("click", () => restoreSnapshot(true));
  els.savePreset.addEventListener("click", savePreset);
  els.previewPreset.addEventListener("click", previewPreset);
  els.applyPreset.addEventListener("click", applyPreset);
  els.deletePreset.addEventListener("click", deletePreset);
  els.runSearch.addEventListener("click", runSearch);
  els.applyTransaction.addEventListener("click", applyTransaction);
  els.rollbackTransaction.addEventListener("click", rollbackTransaction);
}

async function init() {
  bind();
  await refreshHealth();
  await refreshSnapshots();
  await refreshPresets();
  await refreshGrid();
}

init().catch((error) => {
  setLastResponse({ok: false, error: error.message, detail: String(error)});
});
