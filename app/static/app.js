/* 页面级交互：导入样例、状态行、错误反馈 */
(function () {
  "use strict";

  const STATUS = { text: null, dot: null };

  function ready() {
    STATUS.text = document.getElementById("status-text");
    STATUS.dot = document.getElementById("status-dot");
  }

  function setStatus(text, kind) {
    if (!STATUS.text) {
      ready();
    }
    if (STATUS.text) {
      STATUS.text.textContent = text;
    }
    if (STATUS.dot) {
      STATUS.dot.className = "dot" + (kind ? " " + kind : "");
    }
  }

  function setHint(node, text, kind) {
    if (!node) {
      return;
    }
    node.textContent = text;
    node.className = "hint" + (kind ? " " + kind : "");
  }

  async function postJSON(url, payload) {
    const response = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload || {})
    });
    const body = await response.json().catch(function () {
      return {};
    });
    if (!response.ok) {
      const message = body.message || body.error || "HTTP " + response.status;
      throw new Error(message);
    }
    return body;
  }

  function bindImport() {
    const form = document.getElementById("import-form");
    if (!form) {
      return;
    }
    const hint = document.getElementById("import-hint");
    const button = document.getElementById("import-btn");
    const sample = document.getElementById("sample-select");
    const offsets = document.getElementById("offsets-select");

    form.addEventListener("submit", async function (event) {
      event.preventDefault();
      if (button.disabled) {
        return;
      }
      button.disabled = true;
      setHint(hint, "读入中", "");
      setStatus("导入中", "");
      try {
        const result = await postJSON("/api/samples/import", {
          sample: sample ? sample.value : "telemetry_raw",
          offsets: offsets ? offsets.value : "device_offsets"
        });
        const counts = result.counts || {};
        const word = result.reused ? "复用" : "新增";
        setHint(hint, word + " " + result.run_id, "ok");
        setStatus("原始 " + counts.raw_records + " 行 / 采纳 " + counts.accepted + " 行", "ok");
        window.setTimeout(function () {
          window.location.reload();
        }, 260);
      } catch (error) {
        setHint(hint, "导入失败：" + error.message, "bad");
        setStatus("导入失败", "bad");
      } finally {
        button.disabled = false;
      }
    });
  }

  function bindClose() {
    const button = document.getElementById("inspect-close");
    const panel = document.getElementById("inspect");
    if (!button || !panel) {
      return;
    }
    button.addEventListener("click", function () {
      panel.hidden = true;
    });
    document.addEventListener("keydown", function (event) {
      if (event.key === "Escape" && !panel.hidden) {
        panel.hidden = true;
      }
    });
  }

  document.addEventListener("DOMContentLoaded", function () {
    ready();
    bindImport();
    bindClose();
  });

  window.Gridlab = {
    postJSON: postJSON,
    setStatus: setStatus,
    setHint: setHint
  };
})();
