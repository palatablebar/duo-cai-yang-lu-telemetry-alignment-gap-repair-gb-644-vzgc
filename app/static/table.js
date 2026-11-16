/* 单元格导航：方向键移动焦点、Enter 复制、行高亮 */
(function () {
  "use strict";

  function cellMatrix(row) {
    return Array.prototype.slice.call(row.querySelectorAll("td[tabindex]"));
  }

  function rowList() {
    return Array.prototype.slice.call(document.querySelectorAll(".sheet-grid tbody tr"));
  }

  function focusCell(rowIndex, cellIndex) {
    const rows = rowList();
    if (!rows.length) {
      return;
    }
    const safeRow = Math.max(0, Math.min(rows.length - 1, rowIndex));
    const cells = cellMatrix(rows[safeRow]);
    if (!cells.length) {
      return;
    }
    const safeCell = Math.max(0, Math.min(cells.length - 1, cellIndex));
    cells[safeCell].focus();
  }

  function locate(target) {
    const rows = rowList();
    for (let r = 0; r < rows.length; r += 1) {
      const cells = cellMatrix(rows[r]);
      const c = cells.indexOf(target);
      if (c >= 0) {
        return { row: r, cell: c };
      }
    }
    return null;
  }

  function copyCell(target) {
    const text = (target.textContent || "").trim();
    if (!text || !navigator.clipboard) {
      return;
    }
    navigator.clipboard.writeText(text).then(function () {
      target.setAttribute("data-copied", "1");
      window.setTimeout(function () {
        target.removeAttribute("data-copied");
      }, 600);
    });
  }

  document.addEventListener("DOMContentLoaded", function () {
    const sheet = document.getElementById("sheet");
    if (!sheet) {
      return;
    }
    sheet.addEventListener("keydown", function (event) {
      const target = event.target;
      if (!target || target.tagName !== "TD") {
        return;
      }
      if (event.key === "Enter") {
        event.preventDefault();
        copyCell(target);
        return;
      }
      const keys = ["ArrowUp", "ArrowDown", "ArrowLeft", "ArrowRight"];
      if (keys.indexOf(event.key) < 0) {
        return;
      }
      const spot = locate(target);
      if (!spot) {
        return;
      }
      event.preventDefault();
      if (event.key === "ArrowUp") {
        focusCell(spot.row - 1, spot.cell);
      } else if (event.key === "ArrowDown") {
        focusCell(spot.row + 1, spot.cell);
      } else if (event.key === "ArrowLeft") {
        focusCell(spot.row, spot.cell - 1);
      } else {
        focusCell(spot.row, spot.cell + 1);
      }
    });

    sheet.addEventListener("focusin", function (event) {
      const target = event.target;
      if (!target || target.tagName !== "TD") {
        return;
      }
      const row = target.closest("tr");
      if (!row) {
        return;
      }
      rowList().forEach(function (item) {
        item.classList.remove("is-active");
      });
      row.classList.add("is-active");
    });
  });
})();
