/* Sample standard authoring and detection-point confirmation: natural
   language, process card, standard file, region annotation, and CV/analysis
   config all live here — Studio only trains and publishes the result. */
(function () {
  "use strict";

  const root = document.querySelector("#sample-standard-workbench");
  if (!root) return;
  const tenant = root.dataset.tenant || "default";
  const skuId = root.dataset.skuId;
  const strings = window.GIRAFFE_SAMPLE_AUTHOR_I18N || {};
  const conversation = document.querySelector("#sample-authoring-conversation");
  const stateEl = document.querySelector("#sample-authoring-state");
  const dpSection = document.querySelector("#sample-detection-points");
  const renderedIntakes = new Set();
  let currentSku = null;
  let activeRegionEditor = null;

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
    const requestOptions = Object.assign({}, options || {});
    const method = String(requestOptions.method || "GET").toUpperCase();
    const mutating = !["GET", "HEAD", "OPTIONS"].includes(method);
    const credentialInput = document.querySelector("#sample-mutation-credential");
    if (mutating) {
      const credential = credentialInput ? credentialInput.value.trim() : "";
      if (!credential) return Promise.reject(new Error(t("mutationRequired")));
      const headers = new Headers(requestOptions.headers || {});
      headers.set("X-QC-Sample-Surface", "sample-standard");
      headers.set("X-QC-Mutation-Key", credential);
      requestOptions.headers = headers;
    }
    return fetch(path, requestOptions).then(async (response) => {
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(data.error || data.detail || `HTTP ${response.status}`);
      if (mutating && credentialInput) credentialInput.value = "";
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

  // ── Detection point confirmation: read/edit list, region annotation (§2), ─
  // and CV/analysis config. This — not Studio — is where a detection point is
  // located and configured; Studio only trains and publishes the result.
  function findDp(dpId) {
    return ((currentSku && currentSku.detection_points) || []).find((d) => d.id === dpId);
  }

  function renderDetectionPoints(sku) {
    currentSku = sku;
    if (!dpSection) return;
    const dps = (sku.detection_points || [])
      .map((dp) => {
        const bits = [];
        if (dp.method_hint) bits.push(dp.method_hint);
        if (dp.expected_value) bits.push(t("expected", { value: dp.expected_value }));
        bits.push(dp.severity);
        const regionCount = (dp.regions || []).length;
        return (
          `<li data-dp-id="${esc(dp.id)}"><span class="dp-code">${esc(dp.point_code)}</span> — ${esc(dp.label)}` +
          `<div class="dp-meta">${esc(bits.join(" · "))}</div>` +
          (dp.pass_criteria ? `<div class="dp-meta">${esc(dp.pass_criteria)}</div>` : "") +
          `<details class="engineering-settings"><summary>${esc(t("engineering"))}</summary>` +
          `<button type="button" class="btn dp-regions-btn" data-dp-id="${esc(dp.id)}">` +
          (regionCount ? t("regions", { count: regionCount }) : t("addRegions")) +
          `</button>` +
          `<button type="button" class="btn dp-analysis-btn" data-dp-id="${esc(dp.id)}">` +
          ((dp.cv_config && (dp.cv_config.analyzers || []).length) ? t("editCvConfig") : t("addCvConfig")) +
          `</button></details>` +
          `<div class="region-editor-slot"></div>` +
          `</li>`
        );
      })
      .join("");
    dpSection.innerHTML = dps
      ? `<ul class="dp-list">${dps}</ul>`
      : `<p class="hint">${esc(t("noDetectionPoints"))}</p>`;
    dpSection.querySelectorAll(".dp-regions-btn").forEach((btn) => {
      btn.addEventListener("click", () => toggleRegionEditor(btn));
    });
    dpSection.querySelectorAll(".dp-analysis-btn").forEach((btn) => {
      btn.addEventListener("click", () => editAnalysisConfig(btn.dataset.dpId));
    });
  }

  function editAnalysisConfig(dpId) {
    const dp = findDp(dpId);
    if (!dp) return;
    const expectedRaw = window.prompt(
      t("expectedFeaturesPrompt"),
      JSON.stringify(dp.expected_features || {})
    );
    if (expectedRaw === null) return;
    const configRaw = window.prompt(
      t("cvConfigPrompt"),
      JSON.stringify(dp.cv_config || {})
    );
    if (configRaw === null) return;
    let expectedFeatures, cvConfig;
    try {
      expectedFeatures = JSON.parse(expectedRaw || "{}");
      cvConfig = JSON.parse(configRaw || "{}");
    } catch (err) {
      addBubble(t("invalidAnalysisJson", { message: err.message }), "system");
      return;
    }
    api(`/admin/studio/detection-points/${dpId}/analysis-config`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ tenant_id: tenant, expected_features: expectedFeatures, cv_config: cvConfig }),
    })
      .then((data) => {
        if (data.sku) renderDetectionPoints(data.sku);
        addBubble(t("analysisSaved"), "system");
      })
      .catch((err) => addBubble(t("analysisSaveFailed", { message: err.message }), "system"));
  }

  // One editor open at a time; drawn boxes accumulate in `activeRegionEditor`
  // (bounding-box only, normalized 0-1 coords, tagged with the selected
  // photo's image_id) and are only persisted on "Save regions".
  function toggleRegionEditor(btn) {
    const dpId = btn.dataset.dpId;
    const li = btn.closest("li[data-dp-id]");
    const slot = li.querySelector(".region-editor-slot");

    if (activeRegionEditor && activeRegionEditor.dpId === dpId) {
      closeRegionEditor();
      return;
    }
    closeRegionEditor();

    const dp = findDp(dpId);
    const photos = (currentSku && currentSku.photos) || [];
    if (!photos.length) {
      addBubble(t("uploadPhotoBeforeRegions"), "system");
      return;
    }

    const tpl = document.querySelector("#sample-region-editor-template").content.cloneNode(true);
    const regionRoot = tpl.querySelector(".region-editor");
    const select = tpl.querySelector(".region-photo-select");
    const img = tpl.querySelector(".region-image");
    const canvas = tpl.querySelector(".region-canvas");
    const list = tpl.querySelector(".region-list");
    const errorEl = tpl.querySelector(".region-error");

    photos.forEach((p) => {
      const opt = document.createElement("option");
      opt.value = p.id;
      opt.textContent = (p.view_type || p.angle || p.id.slice(0, 8)) + (p.is_primary ? ` (${t("primary")})` : "");
      select.appendChild(opt);
    });

    const regions = (dp.regions || []).map((r) => Object.assign({}, r));

    function currentImageId() { return select.value; }

    function renderList() {
      list.innerHTML = "";
      regions.forEach((r, idx) => {
        if (r.image_id !== currentImageId()) return;
        const li2 = document.createElement("li");
        li2.textContent = `x=${r.x.toFixed(2)} y=${r.y.toFixed(2)} w=${r.w.toFixed(2)} h=${r.h.toFixed(2)}`;
        const rm = document.createElement("button");
        rm.type = "button";
        rm.className = "region-remove";
        rm.textContent = t("remove");
        rm.addEventListener("click", () => {
          regions.splice(idx, 1);
          renderList();
          drawAll();
        });
        li2.appendChild(rm);
        list.appendChild(li2);
      });
    }

    function syncCanvasSize() {
      canvas.width = img.naturalWidth || img.clientWidth;
      canvas.height = img.naturalHeight || img.clientHeight;
      drawAll();
    }

    function drawBox(ctx, x, y, w, h, color) {
      ctx.strokeStyle = color;
      ctx.lineWidth = 2;
      ctx.strokeRect(x, y, w, h);
      ctx.fillStyle = color.replace("rgb", "rgba").replace(")", ",0.12)");
      ctx.fillRect(x, y, w, h);
    }

    function drawAll(dragBox) {
      const ctx = canvas.getContext("2d");
      ctx.clearRect(0, 0, canvas.width, canvas.height);
      regions
        .filter((r) => r.image_id === currentImageId())
        .forEach((r) =>
          drawBox(ctx, r.x * canvas.width, r.y * canvas.height, r.w * canvas.width, r.h * canvas.height, "rgb(37,99,235)")
        );
      if (dragBox) drawBox(ctx, dragBox.x, dragBox.y, dragBox.w, dragBox.h, "rgb(220,38,38)");
    }

    function getPos(e) {
      const rect = canvas.getBoundingClientRect();
      return {
        x: (e.clientX - rect.left) * (canvas.width / rect.width),
        y: (e.clientY - rect.top) * (canvas.height / rect.height),
      };
    }

    let dragging = false, startX = 0, startY = 0;
    canvas.addEventListener("mousedown", (e) => {
      dragging = true;
      const p = getPos(e);
      startX = p.x; startY = p.y;
    });
    canvas.addEventListener("mousemove", (e) => {
      if (!dragging) return;
      const p = getPos(e);
      const x = Math.min(startX, p.x), y = Math.min(startY, p.y);
      const w = Math.abs(p.x - startX), h = Math.abs(p.y - startY);
      drawAll({ x, y, w, h });
    });
    canvas.addEventListener("mouseup", (e) => {
      if (!dragging) return;
      dragging = false;
      const p = getPos(e);
      const x = Math.min(startX, p.x), y = Math.min(startY, p.y);
      const w = Math.abs(p.x - startX), h = Math.abs(p.y - startY);
      if (w < 4 || h < 4 || canvas.width === 0 || canvas.height === 0) { drawAll(); return; }
      regions.push({
        image_id: currentImageId(),
        x: parseFloat((x / canvas.width).toFixed(4)),
        y: parseFloat((y / canvas.height).toFixed(4)),
        w: parseFloat((w / canvas.width).toFixed(4)),
        h: parseFloat((h / canvas.height).toFixed(4)),
      });
      renderList();
      drawAll();
    });

    function loadPhoto() {
      const photo = photos.find((p) => p.id === currentImageId());
      img.src = photo ? photo.url : "";
      renderList();
    }
    img.addEventListener("load", syncCanvasSize);
    select.addEventListener("change", loadPhoto);

    regionRoot.querySelector(".region-save").addEventListener("click", () => {
      errorEl.textContent = "";
      api(`/admin/studio/detection-points/${dpId}/regions`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ tenant_id: tenant, regions: regions }),
      })
        .then((res) => {
          addBubble(t("regionsSaved", { count: regions.length, point: dp.point_code }), "system");
          if (res.sku) renderDetectionPoints(res.sku);
        })
        .catch((err) => { errorEl.textContent = err.message; });
    });
    regionRoot.querySelector(".region-cancel").addEventListener("click", closeRegionEditor);

    slot.appendChild(tpl);
    loadPhoto();
    activeRegionEditor = { dpId, root: slot };
  }

  function closeRegionEditor() {
    if (activeRegionEditor && activeRegionEditor.root) activeRegionEditor.root.innerHTML = "";
    activeRegionEditor = null;
  }

  function showAssistantMeta(assistant) {
    if (!assistant) return;
    addBubble(t("assistantMeta", {
      model: assistant.model || assistant.role,
      seconds: ((assistant.elapsed_ms || 0) / 1000).toFixed(1),
    }), "meta");
  }

  function questionText(question) {
    if (typeof question === "string") return question;
    if (!question) return "";
    const raw = String(
      question.question || question.prompt || question.question_key || question.i18n_key || ""
    ).trim();
    if (!raw) return "";
    if (strings[raw]) return t(raw);
    // Some providers return a translation key in the question field. Never
    // expose that key as the only operator-facing prompt.
    if (/^[A-Za-z][A-Za-z0-9_.:-]*$/.test(raw) && (raw.includes(".") || raw.includes(":"))) {
      const field = String(question.field || "").replace(/[._-]+/g, " ").trim();
      if (field) return t("administratorQuestion") + " (" + field + ")";
      return t("administratorQuestion");
    }
    return raw;
  }

  function showQuestions(questions) {
    (questions || []).forEach((question) => {
      const text = questionText(question);
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
    const questionInputs = {};
    const unresolvedQuestions = (card.questions || []).filter(
      (question) => question && (question.question || question.question_key || question.i18n_key)
    );

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

    const confirmButton = panel.querySelector(".sample-confirm-yes");
    unresolvedQuestions.forEach((question, index) => {
      const row = document.createElement("div");
      row.className = "sample-confirm-row sample-confirm-question";
      const field = String(question.field || "question_" + index).trim() || "question_" + index;
      const label = document.createElement("div");
      label.className = "sample-confirm-fields";
      label.textContent = questionText(question);
      row.appendChild(label);
      const input = document.createElement("textarea");
      input.className = "sample-confirm-input sample-confirm-question-input";
      input.rows = 2;
      input.placeholder = t("answerPlaceholder");
      input.dataset.questionField = field;
      row.appendChild(input);
      questionInputs[field] = input;
      body.appendChild(row);
    });
    if (unresolvedQuestions.length) {
      const warning = document.createElement("div");
      warning.className = "sample-confirm-fields";
      warning.textContent = t("resolveQuestionsBeforeConfirm");
      body.appendChild(warning);
    }

    function isComplete() {
      const countsReady = Object.values(countInputs).every((input) => input.value.trim());
      const questionsReady = Object.values(questionInputs).every((input) => input.value.trim());
      return countsReady && questionsReady;
    }
    function updateConfirmState() {
      confirmButton.disabled = !isComplete();
      confirmButton.title = confirmButton.disabled ? t("resolveQuestionsBeforeConfirm") : "";
    }
    Object.values(countInputs).forEach((input) => input.addEventListener("input", updateConfirmState));
    Object.values(questionInputs).forEach((input) => input.addEventListener("input", updateConfirmState));
    updateConfirmState();

    confirmButton.addEventListener("click", () => {
      const checkpoints = (card.checkpoints || []).map((checkpoint, index) => {
        const result = Object.assign({}, checkpoint);
        if (countInputs[index]) result.expected_value = countInputs[index].value.trim();
        return result;
      });
      if (checkpoints.some((point) => point.method_hint === "counting" && !point.expected_value)) {
        addBubble(t("provideCounts"), "system");
        return;
      }
      const questionAnswers = {};
      unresolvedQuestions.forEach((question, index) => {
        const field = String(question.field || "question_" + index).trim() || "question_" + index;
        questionAnswers[field] = (questionInputs[field] || {}).value
          ? questionInputs[field].value.trim()
          : "";
      });
      if (Object.values(questionAnswers).some((answer) => !answer)) {
        addBubble(t("resolveQuestionsBeforeConfirm"), "system");
        return;
      }
      api("/admin/studio/confirm", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          tenant_id: tenant,
          intake_id: card.intake_id,
          checkpoints,
          question_answers: questionAnswers,
        }),
      }).then((result) => {
        panel.querySelector(".sample-confirm-actions").innerHTML =
          `<span class="hint">${esc(t("confirmedRevision", { revision: result.revision_no }))}</span>`;
        addBubble(t("savedPoints", { count: checkpoints.length, revision: result.revision_no }), "system");
        if (result.sku) renderDetectionPoints(result.sku);
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
    if (result.sku) renderDetectionPoints(result.sku);
    if (result.confirmation_card) renderConfirmation(result.confirmation_card);
    showQuestions(result.questions);
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
      renderDetectionPoints(sku);
      if (sku.pending_confirmation) renderConfirmation(sku.pending_confirmation);
    })
    .catch(() => null);
  api("/admin/studio/assistants")
    .then((status) => setState(status.text && status.text.configured ? t("ready") : t("unavailable"), Boolean(status.text && status.text.configured)))
    .catch(() => setState(t("unavailable"), false));
})();
