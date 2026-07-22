/* Sample standard authoring: natural language, process card, and standard file. */
(function () {
  "use strict";

  const root = document.querySelector("#sample-standard-workbench");
  if (!root) return;
  const tenant = root.dataset.tenant || "default";
  const skuId = root.dataset.skuId;
  const strings = window.GIRAFFE_SAMPLE_AUTHOR_I18N || {};
  const conversation = document.querySelector("#sample-authoring-conversation");
  const stateEl = document.querySelector("#sample-authoring-state");
  const renderedIntakes = new Set();

  function t(key, vars) {
    let value = strings[key] || key;
    Object.keys(vars || {}).forEach((name) => {
      value = value.replace(new RegExp("\\{" + name + "\\}", "g"), vars[name]);
    });
    return value;
  }

  function esc(value) {
    return String(value == null ? "" : value).replace(/[&<>"']/g, (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])
    );
  }

  function api(path, options) {
    return fetch(path, options).then(async (response) => {
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(data.error || data.detail || `HTTP ${response.status}`);
      return data;
    });
  }

  function addBubble(text, kind) {
    const bubble = document.createElement("div");
    bubble.className = `sample-authoring-bubble ${kind || "system"}`;
    bubble.textContent = text;
    conversation.appendChild(bubble);
    conversation.scrollTop = conversation.scrollHeight;
    return bubble;
  }

  function setState(text, ready) {
    stateEl.textContent = text;
    stateEl.classList.toggle("is-ready", Boolean(ready));
  }

  function showAssistantMeta(assistant) {
    if (!assistant) return;
    addBubble(t("assistantMeta", {
      model: assistant.model || assistant.role,
      seconds: ((assistant.elapsed_ms || 0) / 1000).toFixed(1),
    }), "meta");
  }

  function showQuestions(questions) {
    (questions || []).forEach((question) => {
      const text = typeof question === "string" ? question : question && question.question;
      if (text) addBubble(text, "system");
    });
  }

  function renderConfirmation(card) {
    if (!card || renderedIntakes.has(card.intake_id)) return;
    renderedIntakes.add(card.intake_id);
    const fragment = document.querySelector("#sample-confirm-card-template").content.cloneNode(true);
    const panel = fragment.querySelector(".sample-confirm-card");
    const body = fragment.querySelector(".sample-confirm-body");
    const countInputs = {};

    if (card.coverage_review) {
      const coverage = card.coverage_review;
      const node = document.createElement("div");
      node.className = "sample-coverage";
      let html = `<strong>${esc(coverage.complete ? t("coverageComplete") : t("coverageIncomplete"))}</strong>`;
      if ((coverage.checked_dimensions || []).length) {
        html += `<div>${esc(t("coverageChecked", { dimensions: coverage.checked_dimensions.join(", ") }))}</div>`;
      }
      if ((coverage.omissions || []).length) {
        html += `<div>${esc(t("coverageOmissions", { omissions: coverage.omissions.join("; ") }))}</div>`;
      }
      node.innerHTML = html;
      body.appendChild(node);
    }

    (card.checkpoints || []).forEach((checkpoint, index) => {
      const row = document.createElement("div");
      row.className = "sample-confirm-row";
      const needsCount = checkpoint.method_hint === "counting" && !checkpoint.expected_value;
      row.innerHTML =
        `<div class="sample-confirm-code">${esc(checkpoint.point_code)} — ${esc(checkpoint.label)}</div>` +
        `<div class="sample-confirm-fields">${esc(checkpoint.method_hint || "")} · ${esc(checkpoint.severity || "")}` +
        `${checkpoint.pass_criteria ? " · " + esc(checkpoint.pass_criteria) : ""}</div>` +
        `${checkpoint.expected_value ? `<div class="sample-confirm-fields">${esc(t("expected", { value: checkpoint.expected_value }))}</div>` : ""}` +
        `${needsCount ? `<div class="sample-confirm-fields">${esc(t("expectedCountRequired"))}</div>` : ""}`;
      if (needsCount) {
        const input = document.createElement("input");
        input.className = "sample-confirm-input";
        input.placeholder = t("countPlaceholder");
        row.appendChild(input);
        countInputs[index] = input;
      }
      body.appendChild(row);
    });

    panel.querySelector(".sample-confirm-yes").addEventListener("click", () => {
      const checkpoints = (card.checkpoints || []).map((checkpoint, index) => {
        const result = Object.assign({}, checkpoint);
        if (countInputs[index]) result.expected_value = countInputs[index].value.trim();
        return result;
      });
      if (checkpoints.some((point) => point.method_hint === "counting" && !point.expected_value)) {
        addBubble(t("provideCounts"), "system");
        return;
      }
      api("/admin/studio/confirm", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ tenant_id: tenant, intake_id: card.intake_id, checkpoints }),
      }).then((result) => {
        panel.querySelector(".sample-confirm-actions").innerHTML =
          `<span class="hint">${esc(t("confirmedRevision", { revision: result.revision_no }))}</span>`;
        addBubble(t("savedPoints", { count: checkpoints.length, revision: result.revision_no }), "system");
      }).catch((error) => addBubble(t("error", { message: error.message }), "system"));
    });

    panel.querySelector(".sample-confirm-no").addEventListener("click", () => {
      api("/admin/studio/reject", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ tenant_id: tenant, intake_id: card.intake_id }),
      }).then(() => {
        panel.querySelector(".sample-confirm-actions").innerHTML = `<span class="hint">${esc(t("rejected"))}</span>`;
      }).catch((error) => addBubble(t("error", { message: error.message }), "system"));
    });

    conversation.appendChild(fragment);
    conversation.scrollTop = conversation.scrollHeight;
  }

  function handleResult(result) {
    if (result.reply) addBubble(result.reply, "system");
    showAssistantMeta(result.assistant);
    if (result.confirmation_card) renderConfirmation(result.confirmation_card);
    else showQuestions(result.questions);
  }

  function sendText(text) {
    addBubble(text, "user");
    setState(t("thinking"), false);
    const pending = addBubble(t("thinking"), "meta");
    return api("/admin/studio/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ tenant_id: tenant, sku_id: skuId, message: text }),
    }).then((result) => {
      pending.remove();
      handleResult(result);
    }).catch((error) => {
      pending.remove();
      addBubble(t("error", { message: error.message }), "system");
    }).finally(() => setState(t("ready"), true));
  }

  function importFile(file, sourceKind) {
    const form = new FormData();
    form.append("tenant_id", tenant);
    form.append("sku_id", skuId);
    form.append("source_kind", sourceKind);
    form.append("document", file);
    addBubble(t("importReading", { filename: file.name }), "user");
    setState(t("importSending"), false);
    const pending = addBubble(t("importSending"), "meta");
    return api("/admin/studio/import-standard", { method: "POST", body: form }).then((result) => {
      pending.remove();
      if (result.import && result.import.ocr_used) addBubble(t("ocrComplete"), "system");
      handleResult(result);
      addBubble(t("importComplete"), "system");
    }).catch((error) => {
      pending.remove();
      addBubble(t("importFailed", { message: error.message }), "system");
    }).finally(() => setState(t("ready"), true));
  }

  document.querySelector("#sample-authoring-form").addEventListener("submit", (event) => {
    event.preventDefault();
    const input = document.querySelector("#sample-authoring-text");
    const text = input.value.trim();
    if (!text) return;
    input.value = "";
    sendText(text);
  });

  [
    ["#sample-process-card-toggle", "#sample-process-card-input", "process_card"],
    ["#sample-standard-file-toggle", "#sample-standard-file-input", "file"],
  ].forEach(([buttonSelector, inputSelector, sourceKind]) => {
    const input = document.querySelector(inputSelector);
    document.querySelector(buttonSelector).addEventListener("click", () => {
      addBubble(t("importOpening"), "system");
      input.click();
    });
    input.addEventListener("change", () => {
      const file = input.files && input.files[0];
      input.value = "";
      if (file) importFile(file, sourceKind);
    });
  });

  addBubble(t("welcome"), "system");
  api(`/admin/studio/skus/${skuId}?tenant_id=${tenant}`)
    .then((sku) => {
      if (sku.pending_confirmation) renderConfirmation(sku.pending_confirmation);
    })
    .catch(() => null);
  api("/admin/studio/assistants")
    .then((status) => setState(status.text && status.text.configured ? t("ready") : t("unavailable"), Boolean(status.text && status.text.configured)))
    .catch(() => setState(t("unavailable"), false));
})();
