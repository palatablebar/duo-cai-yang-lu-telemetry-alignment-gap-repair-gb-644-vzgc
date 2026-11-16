/* 班次交接页：起草交接包、确认、腾空间、回滚 */
(function () {
  "use strict";

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

  function setHint(node, text, kind) {
    if (!node) {
      return;
    }
    node.textContent = text;
    node.className = "hint" + (kind ? " " + kind : "");
  }

  function bindPrepare() {
    const form = document.getElementById("handover-form");
    if (!form) {
      return;
    }
    const hint = document.getElementById("handover-hint");
    const button = document.getElementById("handover-btn");
    const input = document.getElementById("shift-date");
    form.addEventListener("submit", async function (event) {
      event.preventDefault();
      if (button.disabled) {
        return;
      }
      button.disabled = true;
      setHint(hint, "生成中", "");
      try {
        const result = await postJSON("/api/handovers", {
          shift_date: input.value,
          actor: "值班员"
        });
        const word = result.reused ? "复用既有交接包 " : "已起草交接包 ";
        setHint(hint, word + result.handover_id, "ok");
        window.setTimeout(function () {
          window.location.reload();
        }, 320);
      } catch (error) {
        setHint(hint, "起草失败：" + error.message, "bad");
      } finally {
        button.disabled = false;
      }
    });
  }

  function bindActions() {
    const hint = document.getElementById("action-hint");
    async function act(button, path, okText) {
      const id = button.getAttribute("data-id");
      button.disabled = true;
      setHint(hint, "处理中", "");
      try {
        const result = await postJSON("/api/handovers/" + id + "/" + path, { actor: "值班员" });
        setHint(hint, okText + " " + id, "ok");
        if (window.Gridlab) {
          window.Gridlab.setStatus(okText, "ok");
        }
        window.setTimeout(function () {
          window.location.reload();
        }, 360);
        return result;
      } catch (error) {
        setHint(hint, "操作失败：" + error.message, "bad");
        button.disabled = false;
      }
    }

    const confirmBtn = document.getElementById("confirm-btn");
    const reclaimBtn = document.getElementById("reclaim-btn");
    const rollbackBtn = document.getElementById("rollback-btn");
    if (confirmBtn) {
      confirmBtn.addEventListener("click", function () {
        act(confirmBtn, "confirm", "已确认交接");
      });
    }
    if (reclaimBtn) {
      reclaimBtn.addEventListener("click", function () {
        act(reclaimBtn, "reclaim", "已腾出在线空间，证据保留");
      });
    }
    if (rollbackBtn) {
      rollbackBtn.addEventListener("click", function () {
        act(rollbackBtn, "rollback", "已回滚并恢复旧版结果与原始记录");
      });
    }
  }

  document.addEventListener("DOMContentLoaded", function () {
    bindPrepare();
    bindActions();
  });
})();
