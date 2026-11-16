/* 网格页：按传感器过滤 + 单元格证据抽屉 */
(function () {
  "use strict";

  const FIELDS = [
    ["状态", "state"],
    ["值", "value"],
    ["单位", "unit"],
    ["原因", "reason_label"],
    ["原因码", "reason"],
    ["策略", "fill_policy"],
    ["来源行", "source_row"],
    ["质量位", "quality"],
    ["到达序", "ingest_seq"],
    ["偏移秒", "offset_seconds"],
    ["标记", "flags"]
  ];

  function render(payload) {
    const body = document.getElementById("inspect-body");
    const panel = document.getElementById("inspect");
    if (!body || !panel) {
      return;
    }
    body.textContent = "";
    FIELDS.forEach(function (item) {
      const value = payload[item[1]];
      const term = document.createElement("dt");
      term.textContent = item[0];
      const desc = document.createElement("dd");
      desc.textContent = value === null || value === undefined || value === "" ? "—" : String(value);
      body.appendChild(term);
      body.appendChild(desc);
    });
    if (payload.quarantine && payload.quarantine.length) {
      const term = document.createElement("dt");
      term.textContent = "隔离";
      const desc = document.createElement("dd");
      desc.textContent = payload.quarantine
        .map(function (row) {
          return row.code + " / " + (row.raw_value || "");
        })
        .join("；");
      body.appendChild(term);
      body.appendChild(desc);
    }
    panel.hidden = false;
  }

  function bindFilter() {
    const select = document.getElementById("sensor-filter");
    const table = document.getElementById("grid-table");
    if (!select || !table) {
      return;
    }
    select.addEventListener("change", function () {
      const value = select.value;
      const rows = table.querySelectorAll("tbody tr");
      Array.prototype.forEach.call(rows, function (row) {
        const match = !value || row.getAttribute("data-sensor") === value;
        row.hidden = !match;
      });
    });
  }

  function bindInspect() {
    const table = document.getElementById("grid-table");
    if (!table) {
      return;
    }
    table.addEventListener("click", function (event) {
      const row = event.target.closest("tr[data-bucket]");
      if (!row) {
        return;
      }
      const sensor = row.getAttribute("data-sensor");
      const bucket = row.getAttribute("data-bucket");
      const url =
        "/api/export/evidence?sensor_id=" +
        encodeURIComponent(sensor) +
        "&bucket=" +
        encodeURIComponent(bucket);
      fetch(url)
        .then(function (response) {
          if (!response.ok) {
            throw new Error("单元格不存在");
          }
          return response.json();
        })
        .then(render)
        .catch(function (error) {
          if (window.Gridlab) {
            window.Gridlab.setStatus("证据读取失败：" + error.message, "bad");
          }
        });
    });
  }

  document.addEventListener("DOMContentLoaded", function () {
    bindFilter();
    bindInspect();
  });
})();
