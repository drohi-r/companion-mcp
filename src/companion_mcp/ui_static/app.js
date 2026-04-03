const state = {
  page: 1,
  rows: 4,
  columns: 8,
  includeEmpty: false,
  selected: null,
  lastInventory: null,
};

const els = {
  page: document.querySelector("#page"),
  rows: document.querySelector("#rows"),
  columns: document.querySelector("#columns"),
  includeEmpty: document.querySelector("#include-empty"),
  refreshGrid: document.querySelector("#refresh-grid"),
  pageGrid: document.querySelector("#page-grid"),
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
  deleteSnapshot: document.querySelector("#delete-snapshot"),
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
};

function setLastResponse(payload) {
  els.lastResponse.textContent = JSON.stringify(payload, null, 2);
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
    ${preview ? `<img src="${preview}" alt="">` : `<div class="button-preview empty">No preview</div>`}
    <strong>${text}</strong>
    <small>${button.row}/${button.column} · ${controlType}</small>
  `;
  element.addEventListener("click", () => selectButton(button));
  return element;
}

function renderPreview(button) {
  const image = button.preview?.image;
  if (!image) {
    els.buttonPreview.textContent = "No preview image available.";
    return;
  }
  els.buttonPreview.innerHTML = `<img src="${image}" alt="Button preview">`;
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
  els.selectedCoords.textContent = `Page ${button.page} · Row ${button.row} · Column ${button.column}`;
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
  els.targetDetail.textContent = `Writes ${config.write_enabled ? "enabled" : "disabled"} · UI ${window.location.host}`;
  els.healthStatus.textContent = health.ok ? "Reachable" : "Unavailable";
  els.healthDetail.textContent = `Probe ${health.status_code} · ${health.app_info?.body || "no app info"}`;
}

async function refreshGrid(selectFirst = true) {
  state.page = Number(els.page.value);
  state.rows = Number(els.rows.value);
  state.columns = Number(els.columns.value);
  state.includeEmpty = els.includeEmpty.checked;
  const payload = await api(`/api/page?${currentGridQuery().toString()}`);
  state.lastInventory = payload;
  els.pageGrid.style.gridTemplateColumns = `repeat(${state.columns}, minmax(92px, 1fr))`;
  els.pageGrid.innerHTML = "";
  const buttons = payload.buttons || [];
  buttons.forEach((button) => els.pageGrid.appendChild(renderGridButton(button)));
  if (selectFirst && buttons.length && !state.selected) {
    await selectButton(buttons[0]);
  }
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
  const payload = await api("/api/snapshots/save", {
    method: "POST",
    body: JSON.stringify({
      name: els.snapshotName.value || `page-${state.page}`,
      page: state.page,
      rows: state.rows,
      columns: state.columns,
      include_empty: state.includeEmpty,
    }),
  });
  await refreshSnapshots();
  return payload;
}

async function savePreset() {
  const payload = await api("/api/presets/save", {
    method: "POST",
    body: JSON.stringify({
      name: els.presetName.value || `page-${state.page}`,
      page: state.page,
      rows: state.rows,
      columns: state.columns,
      include_empty: state.includeEmpty,
    }),
  });
  await refreshPresets();
  return payload;
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
      page: state.page,
      origin_row: 0,
      origin_column: 0,
    }),
  });
}

async function applyPreset() {
  await api("/api/presets/apply", {
    method: "POST",
    body: JSON.stringify({
      name: els.presetList.value,
      page: state.page,
      origin_row: 0,
      origin_column: 0,
      wait_ms: 1000,
      poll_ms: 200,
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

async function runSearch() {
  const payload = await api(`/api/search?${new URLSearchParams({
    query: els.searchQuery.value,
    page: String(state.page),
    rows: String(state.rows),
    columns: String(state.columns),
    include_empty: state.includeEmpty ? "1" : "0",
  }).toString()}`);
  els.searchResults.textContent = JSON.stringify(payload, null, 2);
}

async function applyTransaction() {
  const {row, column} = selectedCoords();
  await api("/api/transactions/apply", {
    method: "POST",
    body: JSON.stringify({
      snapshot_name: els.transactionName.value || `txn-page-${state.page}`,
      page: state.page,
      rows: state.rows,
      columns: state.columns,
      styles: [{
        row,
        column,
        text: els.styleText.value,
        color: els.styleColor.value,
        bgcolor: els.styleBgcolor.value,
        size: els.styleSize.value,
      }],
      wait_ms: 1000,
      poll_ms: 200,
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
      wait_ms: 1000,
      poll_ms: 200,
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
  els.deleteSnapshot.addEventListener("click", deleteSnapshot);
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
