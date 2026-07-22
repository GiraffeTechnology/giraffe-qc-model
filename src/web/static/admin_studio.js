/* Admin Studio — chat-first SKU + standard training (S2). */
(function () {
  "use strict";

  const tenant = document.body.dataset.tenant || "default";
  const initialSkuId = document.body.dataset.initialSku || null;
  const state = { skuId: null, sku: null, renderedIntakes: new Set() };

  const $ = (sel) => document.querySelector(sel);
  const conversation = $("#conversation");
  const skuList = $("#sku-list");
  const skuCard = $("#sku-card");
  const activeChip = $("#active-sku-chip");
  const assistantState = $("#assistant-state");
  const strings = window.GIRAFFE_STUDIO_I18N || {};
  const standardCameraPanel = $("#standard-camera-panel");
  const standardCameraVideo = $("#standard-camera-preview");
  const standardCameraCanvas = $("#standard-camera-canvas");
  const standardCameraDevice = $("#standard-camera-device");
  const standardCameraStart = $("#standard-camera-start");
  const standardCameraCapture = $("#standard-camera-capture");
  const standardCameraStop = $("#standard-camera-stop");
  const standardCameraStatus = $("#standard-camera-status");
  const standardCameraConfirm = $("#standard-camera-confirm");
  const standardCameraUploadConfirm = $("#standard-camera-upload-confirm");
  const standardCameraRetake = $("#standard-camera-retake");
  let standardCameraStream = null;
  let pendingStandardSampleBlob = null;

  function t(key, vars) {
    let text = strings[key] || key;
    Object.keys(vars || {}).forEach((name) => {
      text = text.replace(new RegExp("\\{" + name + "\\}", "g"), vars[name]);
    });
    return text;
  }

  // PRD lifecycle label for a stored status; legacy values (active/inactive/
  // archived) have no translation and render raw so they stay recognizable.
  function statusLabel(status) {
    return (strings.statusLabels || {})[status] || status;
  }

  function standardStatusLabel(status) {
    return (strings.standardStatusLabels || {})[status] || status;
  }

  function api(path, opts) {
    return fetch(path, opts).then(async (r) => {
      const data = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(data.error || data.detail || ("HTTP " + r.status));
      return data;
    });
  }

  // ── Conversation bubbles (§3.4) ─────────────────────────────────────────
  function addBubble(text, who, imageUrl) {
    const b = document.createElement("div");
    b.className = "bubble " + (who === "user" ? "user" : "system") +
      ((who === "pending" || who === "meta") ? " " + who : "");
    b.textContent = text;
    if (imageUrl) {
      const img = document.createElement("img");
      img.className = "chat-photo";
      img.src = imageUrl;
      b.appendChild(img);
    }
    conversation.appendChild(b);
    conversation.scrollTop = conversation.scrollHeight;
    return b;
  }

  function setAssistantState(text, busy) {
    assistantState.textContent = text;
    assistantState.classList.toggle("busy", Boolean(busy));
  }

  function showAssistantMeta(assistant) {
    if (!assistant) return;
    addBubble(t("assistantMeta", {
      model: assistant.model || assistant.role,
      seconds: ((assistant.elapsed_ms || 0) / 1000).toFixed(1),
    }), "meta");
  }

  // ── Left panel: SKU list ────────────────────────────────────────────────
  function loadSkus() {
    const q = encodeURIComponent($("#sku-search").value.trim());
    const status = encodeURIComponent($("#sku-status-filter").value);
    return api(`/admin/studio/skus?tenant_id=${tenant}&q=${q}&status=${status}`)
      .then((data) => renderSkuList(data.items || []));
  }

  function renderSkuList(items) {
    skuList.innerHTML = "";
    if (!items.length) {
      const li = document.createElement("li");
      li.className = "muted";
      li.textContent = t("noSkus");
      skuList.appendChild(li);
      return;
    }
    items.forEach((sku) => {
      const li = document.createElement("li");
      if (sku.id === state.skuId) li.classList.add("selected");
      li.innerHTML =
        `<div class="sku-item-number">${esc(sku.item_number)}</div>` +
        `<div class="sku-name">${esc(sku.name)}</div>` +
        `<div class="sku-meta">${esc(statusLabel(sku.status))} · ${esc(standardStatusLabel(sku.standard_status))}</div>`;
      li.addEventListener("click", () => selectSku(sku.id));
      skuList.appendChild(li);
    });
  }

  // ── Right panel: SKU card ───────────────────────────────────────────────
  function selectSku(skuId) {
    return api(`/admin/studio/skus/${skuId}?tenant_id=${tenant}`).then((sku) => {
      setActiveSku(sku);
      loadSkus();
    });
  }

  function setActiveSku(sku) {
    state.skuId = sku ? sku.id : null;
    state.sku = sku;
    if (sku) {
      activeChip.textContent = sku.item_number;
      activeChip.classList.remove("hidden");
    } else {
      activeChip.classList.add("hidden");
    }
    const authoringLink = $("#sample-authoring-link");
    if (authoringLink) authoringLink.href = sku ? `/admin/samples/${sku.id}?tenant_id=${tenant}` : `/admin/samples?tenant_id=${tenant}`;
    renderCard(sku);
  }

  function renderCard(sku) {
    if (!sku) {
      skuCard.className = "sku-card empty";
      skuCard.innerHTML = `<p class="muted">${esc(t("emptyStandard"))}</p>`;
      return;
    }
    skuCard.className = "sku-card";
    const photo = sku.primary_photo;
    const preview = photo
      ? `<img class="standard-preview" src="${photo.url}" alt="${esc(t("standardPhotoAlt"))}">`
      : `<div class="standard-preview placeholder">${esc(t("noPhoto"))}</div>`;

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

    const trainingQualified = Boolean(sku.training && sku.training.qualified);
    const canPublish = sku.standard_status === "standard_active" && trainingQualified;
    skuCard.innerHTML =
      `<h3>${esc(sku.name)}</h3>` +
      `<div class="sku-sub">${esc(sku.item_number)}${sku.category ? " · " + esc(sku.category) : ""}</div>` +
      preview +
      `<div class="standard-facts">` +
      `<span><small>${esc(t("lifecycle"))}</small><strong>${esc(statusLabel((sku.lifecycle && sku.lifecycle.stage) || sku.status))}</strong></span>` +
      `<span><small>${esc(t("revision"))}</small><strong>${esc(sku.active_revision_no || "—")}</strong></span>` +
      `<span><small>${esc(t("confirmedPoints"))}</small><strong>${esc(sku.detection_point_count || 0)}</strong></span>` +
      `</div>` +
      `<div><span class="status-badge status-${esc(sku.standard_status)}">${esc(standardStatusLabel(sku.standard_status))}</span></div>` +
      (dps ? `<ul class="dp-list">${dps}</ul>` : `<p class="muted" style="margin-top:12px">${esc(t("noDetectionPoints"))}</p>`) +
      `<div id="training-section" class="training-section"></div>` +
      `<div class="publish-row">` +
      `<button class="publish-btn" id="publish-btn" ${canPublish ? "" : "disabled"}>${esc(t("publish"))}</button>` +
      (sku.standard_status === "standard_active" && !trainingQualified
        ? `<div class="muted publish-blocked-note">${esc(t("publishBlockedByTraining"))}</div>` : "") +
      `<div class="bundle-note hidden" id="bundle-note"></div>` +
      `</div>` +
      `<p class="install-next">${esc(t("installNext"))} <a href="/admin/workstations">${esc(t("installManage"))}</a></p>` +
      `<div id="probation-section" class="probation-section"></div>`;

    const pubBtn = $("#publish-btn");
    if (pubBtn) pubBtn.addEventListener("click", publish);

    skuCard.querySelectorAll(".dp-regions-btn").forEach((btn) => {
      btn.addEventListener("click", () => toggleRegionEditor(btn));
    });
    skuCard.querySelectorAll(".dp-analysis-btn").forEach((btn) => {
      btn.addEventListener("click", () => editAnalysisConfig(btn.dataset.dpId));
    });

    if (sku.active_revision_id) {
      loadProbation(sku.active_revision_id);
      renderTraining($("#training-section"), sku);
    }
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
        setActiveSku(data.sku);
        addBubble(t("analysisSaved"), "system");
      })
      .catch((err) => addBubble(t("analysisSaveFailed", { message: err.message }), "system"));
  }

  // ── Probation / qualification (§3, WS7) ─────────────────────────────────
  // A published standard runs under mandatory human confirmation until it
  // qualifies solo (90% agreement over >=30 real jobs). This section reads
  // the real /api/qc/probation surface -- no separate mock state here.
  function loadProbation(revisionId) {
    const slot = $("#probation-section");
    if (!slot) return;
    api(`/api/qc/probation/by-revision/${revisionId}?tenant_id=${tenant}`)
      .then((p) => renderProbation(slot, p))
      .catch(() => {
        slot.innerHTML = `<div class="probation-empty muted">${esc(t("probationNotStarted"))}</div>`;
      });
  }

  function renderProbation(slot, p) {
    const g = p.gate;
    const statusLabel = { active: t("probationActive"), paused: t("probationPaused"), qualified: t("probationQualified") }[p.status] || p.status;
    const stats = t("probationStats", { jobs: g.jobs_recorded, rate: (g.agreement_rate * 100).toFixed(0) });
    slot.innerHTML =
      `<div class="probation-head">` +
      `<span class="status-badge status-probation-${esc(p.status)}">${esc(statusLabel)}</span>` +
      `<span class="probation-stats">${esc(stats)}` +
      (g.min_sample_met ? "" : ` ${esc(t("probationMinimum", { count: g.min_sample_size }))}`) +
      `</span>` +
      `</div>` +
      `<div class="probation-actions">` +
      (p.status === "active" ? `<button type="button" class="btn" id="probation-pause">${esc(t("pause"))}</button>` : "") +
      (p.status === "paused" ? `<button type="button" class="btn btn-primary" id="probation-resume">${esc(t("resume"))}</button>` : "") +
      (g.jobs_recorded > 0 ? `<button type="button" class="btn" id="probation-report">${esc(t("disagreementReport"))}</button>` : "") +
      `</div>`;

    const pauseBtn = slot.querySelector("#probation-pause");
    if (pauseBtn) pauseBtn.addEventListener("click", () => probationAction(p.probation_id, "pause"));
    const resumeBtn = slot.querySelector("#probation-resume");
    if (resumeBtn) resumeBtn.addEventListener("click", () => probationAction(p.probation_id, "resume"));
    const reportBtn = slot.querySelector("#probation-report");
    if (reportBtn) reportBtn.addEventListener("click", () => showDisagreementReport(p.probation_id));
  }

  function probationAction(probationId, action) {
    api(`/api/qc/probation/${probationId}/${action}`, { method: "POST" })
      .then((p) => {
        addBubble(t("probationActionDone", { action: action === "pause" ? t("pause") : t("resume") }), "system");
        const slot = $("#probation-section");
        if (slot) renderProbation(slot, p);
      })
      .catch((err) => addBubble(t("probationActionFailed", {
        action: action === "pause" ? t("pause") : t("resume"),
        message: err.message,
      }), "system"));
  }

  // Reuses the existing conversation bubble component for the disagreement
  // report (per the probation-api.md contract) rather than a new chart/table.
  function showDisagreementReport(probationId) {
    api(`/api/qc/probation/${probationId}/disagreement-report?tenant_id=${tenant}`)
      .then((r) => {
        if (!r.disagreements) {
          addBubble(t("noDisagreements"), "system");
          return;
        }
        const lines = [t("disagreementSummary", { count: r.disagreements, jobs: r.gate.jobs_recorded })];
        r.detection_points.slice(0, 5).forEach((dp) => {
          lines.push(t("disagreementLine", { point: dp.point_code, count: dp.disagreement_count }));
        });
        addBubble(lines.join("\n"), "system");
      })
      .catch((err) => addBubble(t("disagreementLoadFailed", { message: err.message }), "system"));
  }

  // ── Training step (§9.5-9.8): CV+VLM judgment against a labeled sample, ──
  // per-decision admin review, rolling 29/30-window publish gate. The gate
  // itself (sku.training) already arrives on the SKU summary; this section
  // additionally loads the pending review queue and lets the admin record
  // new judgments and submit decisions.
  function renderTraining(slot, sku) {
    if (!slot) return;
    const status = sku.training;
    const badge = status && status.qualified
      ? `<span class="status-badge status-training-qualified">${esc(t("trainingQualified"))}</span>`
      : `<span class="status-badge status-training-pending">${esc(t("trainingNotQualified"))}</span>`;
    const window29 = status && status.recent_29_correct != null
      ? t("trainingWindowStats", { correct: status.recent_29_correct, size: 29 }) : null;
    const window30 = status && status.recent_30_correct != null
      ? t("trainingWindowStats", { correct: status.recent_30_correct, size: 30 }) : null;
    const falsePassNote = status && status.recent_30_false_pass_count > 0
      ? `<div class="training-false-pass">${esc(t("trainingFalsePass", { count: status.recent_30_false_pass_count }))}</div>` : "";
    slot.innerHTML =
      `<div class="training-head">` +
      `<strong>${esc(t("trainingHeading"))}</strong> ${badge}` +
      `</div>` +
      `<div class="training-stats muted">` +
      (window30 || window29 || t("trainingNoSamples")) +
      `</div>` +
      falsePassNote +
      `<div class="training-form">` +
      `<input type="file" id="training-sample-input" accept="image/*">` +
      `<label><input type="radio" name="training-truth" value="qualified" checked> ${esc(t("trainingGroundTruthQualified"))}</label>` +
      `<label><input type="radio" name="training-truth" value="unqualified"> ${esc(t("trainingGroundTruthUnqualified"))}</label>` +
      `<button type="button" class="btn" id="training-submit-btn">${esc(t("trainingSubmitSample"))}</button>` +
      `</div>` +
      `<div id="training-queue" class="training-queue"></div>`;

    const submitBtn = slot.querySelector("#training-submit-btn");
    if (submitBtn) submitBtn.addEventListener("click", () => submitTrainingSample(sku.id));
    loadTrainingQueue(sku.id);
  }

  function submitTrainingSample(skuId) {
    const input = $("#training-sample-input");
    const file = input && input.files && input.files[0];
    if (!file) {
      addBubble(t("trainingSelectSample"), "system");
      return;
    }
    const truthInput = document.querySelector('input[name="training-truth"]:checked');
    const groundTruth = truthInput ? truthInput.value : "qualified";
    const fd = new FormData();
    fd.append("tenant_id", tenant);
    fd.append("ground_truth_label", groundTruth);
    fd.append("image", file);
    addBubble(t("trainingRunning"), "system");
    api(`/admin/studio/skus/${skuId}/training/judgments`, { method: "POST", body: fd })
      .then(() => {
        addBubble(t("trainingRecorded"), "system");
        if (input) input.value = "";
        loadTrainingQueue(skuId);
      })
      .catch((err) => addBubble(t("trainingFailed", { message: err.message }), "system"));
  }

  function loadTrainingQueue(skuId) {
    const queue = $("#training-queue");
    if (!queue) return;
    api(`/admin/studio/skus/${skuId}/training/judgments?tenant_id=${tenant}`)
      .then((data) => renderTrainingQueue(queue, skuId, data.judgments || []))
      .catch(() => { queue.innerHTML = ""; });
  }

  function renderTrainingQueue(queue, skuId, judgments) {
    if (!judgments.length) {
      queue.innerHTML = `<p class="muted">${esc(t("trainingQueueEmpty"))}</p>`;
      return;
    }
    queue.innerHTML = judgments.map((j) => {
      const results = (j.checkpoint_results || [])
        .map((r) => `${esc(r.point_code)}: ${esc(r.result)}`)
        .join(", ");
      return (
        `<div class="training-item" data-judgment-id="${esc(j.id)}">` +
        `<div class="training-item__meta">${esc(t("trainingGroundTruth", { label: j.ground_truth_label }))} · ${esc(t("trainingModelResult", { result: j.model_overall_result }))}</div>` +
        `<div class="training-item__results muted">${results}</div>` +
        `<div class="training-item__actions">` +
        `<button type="button" class="btn btn-primary training-correct">${esc(t("trainingCorrect"))}</button>` +
        `<button type="button" class="btn training-incorrect">${esc(t("trainingIncorrect"))}</button>` +
        `</div>` +
        `</div>`
      );
    }).join("");
    queue.querySelectorAll(".training-item").forEach((row) => {
      const judgmentId = row.dataset.judgmentId;
      row.querySelector(".training-correct").addEventListener("click", () => submitTrainingDecision(skuId, judgmentId, "correct"));
      row.querySelector(".training-incorrect").addEventListener("click", () => submitTrainingDecision(skuId, judgmentId, "incorrect"));
    });
  }

  function submitTrainingDecision(skuId, judgmentId, decision) {
    let correction = null;
    if (decision === "incorrect") {
      const pointCode = window.prompt(t("trainingCorrectionPoint"));
      if (pointCode === null) return;
      const modelError = window.prompt(t("trainingCorrectionModelError"));
      if (modelError === null) return;
      const correctConclusion = window.prompt(t("trainingCorrectionConclusion"));
      if (correctConclusion === null) return;
      const correctFacts = window.prompt(t("trainingCorrectionFacts"));
      if (correctFacts === null) return;
      correction = {
        point_code: pointCode, model_error: modelError,
        correct_conclusion: correctConclusion, correct_facts: correctFacts,
      };
    }
    api(`/admin/studio/training/judgments/${judgmentId}/decision`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ tenant_id: tenant, decision, correction }),
    })
      .then(() => {
        addBubble(t("trainingDecisionSaved"), "system");
        loadTrainingQueue(skuId);
        selectSku(skuId); // refresh the gate status + publish button
      })
      .catch((err) => addBubble(t("trainingDecisionFailed", { message: err.message }), "system"));
  }

  function publish() {
    if (!state.skuId) return;
    const btn = $("#publish-btn");
    btn.disabled = true;
    btn.textContent = t("publishing");
    api("/admin/studio/publish", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ tenant_id: tenant, sku_id: state.skuId }),
    })
      .then((data) => {
        const b = data.bundle;
        addBubble(
          t("published", {
            item: state.sku.item_number,
            count: b.detection_point_count,
          }),
          "system"
        );
        const note = $("#bundle-note");
        note.classList.remove("hidden");
        note.textContent = t("bundleNote", {
          id: b.id.slice(0, 8),
          algorithm: b.signature_algorithm,
          hash: b.bundle_hash.slice(0, 16),
        });
        if (data.sku) setActiveSku(data.sku);
        loadSkus();
        btn.textContent = t("publish");
        btn.disabled = false;
      })
      .catch((err) => {
        addBubble(t("publishFailed", { message: err.message }), "system");
        btn.textContent = t("publish");
        btn.disabled = false;
      });
  }

  // ── Region annotation editor (§2) ───────────────────────────────────────
  // One editor open at a time; drawn boxes accumulate in `activeEditor.regions`
  // (bounding-box only, normalized 0-1 coords, tagged with the selected
  // photo's image_id) and are only persisted on "Save regions".
  let activeEditor = null;

  function findDp(dpId) {
    return ((state.sku && state.sku.detection_points) || []).find((d) => d.id === dpId);
  }

  function toggleRegionEditor(btn) {
    const dpId = btn.dataset.dpId;
    const li = btn.closest("li[data-dp-id]");
    const slot = li.querySelector(".region-editor-slot");

    if (activeEditor && activeEditor.dpId === dpId) {
      closeRegionEditor();
      return;
    }
    closeRegionEditor();

    const dp = findDp(dpId);
    const photos = (state.sku && state.sku.photos) || [];
    if (!photos.length) {
      addBubble(t("uploadPhotoBeforeRegions"), "system");
      return;
    }

    const tpl = $("#region-editor-template").content.cloneNode(true);
    const root = tpl.querySelector(".region-editor");
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

    root.querySelector(".region-save").addEventListener("click", () => {
      errorEl.textContent = "";
      api(`/admin/studio/detection-points/${dpId}/regions`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ tenant_id: tenant, regions: regions }),
      })
        .then((res) => {
          addBubble(t("regionsSaved", { count: regions.length, point: dp.point_code }), "system");
          if (res.sku) setActiveSku(res.sku);
        })
        .catch((err) => { errorEl.textContent = err.message; });
    });
    root.querySelector(".region-cancel").addEventListener("click", closeRegionEditor);

    slot.appendChild(tpl);
    loadPhoto();
    activeEditor = { dpId, root: slot };
  }

  function closeRegionEditor() {
    if (activeEditor && activeEditor.root) activeEditor.root.innerHTML = "";
    activeEditor = null;
  }

  // ── Chat send ───────────────────────────────────────────────────────────
  function sendChat(text) {
    addBubble(text, "user");
    setAssistantState(t("textThinking"), true);
    const pending = addBubble(t("textThinking"), "pending");
    return api("/admin/studio/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ tenant_id: tenant, message: text, sku_id: state.skuId }),
    })
      .then((res) => {
        pending.remove();
        if (res.reply) addBubble(res.reply, "system");
        showAssistantMeta(res.assistant);
        if (res.sku) setActiveSku(res.sku);
        if (res.action === "created_sku" || res.action === "selected_sku") loadSkus();
        if (res.confirmation_card) renderConfirmCard(res.confirmation_card);
        else renderQuestions(res.questions);
      })
      .catch((err) => {
        pending.remove();
        addBubble(t("error", { message: err.message }), "system");
      })
      .finally(() => setAssistantState(t("assistantReady"), false));
  }

  function importStandard(file, sourceKind) {
    if (!state.skuId) {
      addBubble(t("selectBeforeImport"), "system");
      return Promise.resolve(false);
    }
    const fd = new FormData();
    fd.append("sku_id", state.skuId);
    fd.append("tenant_id", tenant);
    fd.append("source_kind", sourceKind);
    fd.append("document", file);
    addBubble(t("importReading", { filename: file.name }), "user");
    setAssistantState(t("importSending"), true);
    const pending = addBubble(t("importSending"), "pending");
    return api("/admin/studio/import-standard", { method: "POST", body: fd })
      .then((res) => {
        pending.remove();
        if (res.import && res.import.ocr_used) addBubble(t("ocrComplete"), "system");
        if (res.reply) addBubble(res.reply, "system");
        showAssistantMeta(res.assistant);
        if (res.sku) setActiveSku(res.sku);
        if (res.confirmation_card) renderConfirmCard(res.confirmation_card);
        else renderQuestions(res.questions);
        addBubble(t("importComplete"), "system");
        return true;
      })
      .catch((err) => {
        pending.remove();
        addBubble(t("importFailed", { message: err.message }), "system");
        return false;
      })
      .finally(() => setAssistantState(t("assistantReady"), false));
  }

  function openImportPicker(selector) {
    if (!state.skuId) {
      addBubble(t("selectBeforeImport"), "system");
      return;
    }
    addBubble(t("importOpening"), "system");
    $(selector).click();
  }

  function handleImportSelection(event, sourceKind) {
    const input = event.target;
    const file = input.files && input.files[0];
    input.value = "";
    if (file) importStandard(file, sourceKind);
  }

  // Assistant follow-up questions arrive without a confirmation card when the
  // administrator has not defined checkpoints yet (checkpoints are authored by
  // the administrator; photo analysis only describes and asks). Surface them
  // as chat bubbles so they are never silently dropped.
  function renderQuestions(questions) {
    (questions || []).forEach((q) => {
      const text = typeof q === "string" ? q : q && q.question;
      if (text) addBubble(text, "system");
    });
  }

  // ── Confirmation card (§5.5) ────────────────────────────────────────────
  function renderConfirmCard(card) {
    state.renderedIntakes.add(card.intake_id);
    const tpl = $("#confirm-card-template").content.cloneNode(true);
    const root = tpl.querySelector(".confirm-card");
    const body = tpl.querySelector(".confirm-body");

    const inputs = {};
    if (card.coverage_review) {
      const coverage = card.coverage_review;
      const review = document.createElement("div");
      review.className = "cp-coverage " + (coverage.complete ? "is-complete" : "needs-review");
      let html = `<strong>${esc(coverage.complete ? t("coverageComplete") : t("coverageIncomplete"))}</strong>`;
      if ((coverage.checked_dimensions || []).length) {
        html += `<div>${esc(t("coverageChecked", { dimensions: coverage.checked_dimensions.join(", ") }))}</div>`;
      }
      if ((coverage.omissions || []).length) {
        html += `<div>${esc(t("coverageOmissions", { omissions: coverage.omissions.join("; ") }))}</div>`;
      }
      review.innerHTML = html;
      body.appendChild(review);
    }
    card.checkpoints.forEach((cp, i) => {
      const row = document.createElement("div");
      row.className = "cp-row";
      const needsCount = cp.method_hint === "counting" && !cp.expected_value;
      let html =
        `<div class="cp-code">${esc(cp.point_code)} — ${esc(cp.label)}</div>` +
        `<div class="cp-fields">${esc(cp.method_hint || "")} · ${esc(cp.severity || "")}` +
        (cp.pass_criteria ? ` · ${esc(cp.pass_criteria)}` : "") + `</div>`;
      if (needsCount) {
        html += `<div class="cp-missing">${esc(t("expectedCountRequired"))}</div>`;
      } else if (cp.expected_value) {
        html += `<div class="cp-fields">${esc(t("expected", { value: cp.expected_value }))}</div>`;
      }
      row.innerHTML = html;
      if (needsCount) {
        const inp = document.createElement("input");
        inp.className = "cp-input";
        inp.type = "text";
        inp.placeholder = t("countPlaceholder");
        inp.dataset.idx = i;
        row.appendChild(inp);
        inputs[i] = inp;
      }
      body.appendChild(row);
    });

    root.querySelector(".confirm-yes").addEventListener("click", () => {
      const checkpoints = card.checkpoints.map((cp, i) => {
        const out = Object.assign({}, cp);
        if (inputs[i]) out.expected_value = inputs[i].value.trim();
        return out;
      });
      const missing = checkpoints.some(
        (cp) => cp.method_hint === "counting" && !cp.expected_value
      );
      if (missing) {
        addBubble(t("provideCounts"), "system");
        return;
      }
      api("/admin/studio/confirm", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          tenant_id: tenant,
          intake_id: card.intake_id,
          checkpoints: checkpoints,
        }),
      })
        .then((res) => {
          root.querySelector(".confirm-actions").innerHTML =
            `<span class="muted">${esc(t("confirmedRevision", { revision: res.revision_no }))}</span>`;
          addBubble(
            t("savedPoints", {
              count: checkpoints.length,
              revision: res.revision_no,
            }),
            "system"
          );
          if (res.sku) setActiveSku(res.sku);
          loadSkus();
        })
        .catch((err) => addBubble(t("error", { message: err.message }), "system"));
    });

    root.querySelector(".confirm-no").addEventListener("click", () => {
      api("/admin/studio/reject", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ tenant_id: tenant, intake_id: card.intake_id }),
      }).finally(() => {
        root.querySelector(".confirm-actions").innerHTML =
          `<span class="muted">${esc(t("rejected"))}</span>`;
      });
    });

    conversation.appendChild(tpl);
    conversation.scrollTop = conversation.scrollHeight;
  }

  // ── Upload (§5.3) ───────────────────────────────────────────────────────
  function uploadPhoto(file) {
    if (!state.skuId) {
      addBubble(t("selectBeforeUpload"), "system");
      return Promise.resolve(false);
    }
    const fd = new FormData();
    fd.append("sku_id", state.skuId);
    fd.append("tenant_id", tenant);
    fd.append("image", file);
    addBubble(t("uploadingPhoto"), "user");
    setAssistantState(t("visionThinking"), true);
    const pending = addBubble(t("visionThinking"), "pending");
    return api("/admin/studio/upload", { method: "POST", body: fd })
      .then((res) => {
        pending.remove();
        addBubble(t("photoUploaded"), "system", res.url);
        if (res.analysis_error) {
          addBubble(t("visionFailed", { message: res.analysis_error }), "system");
        } else if (res.analysis) {
          if (res.analysis.reply) addBubble(res.analysis.reply, "system");
          showAssistantMeta(res.analysis.assistant);
          if (res.analysis.confirmation_card) renderConfirmCard(res.analysis.confirmation_card);
          else renderQuestions(res.analysis.questions);
        }
        if (res.analysis && res.analysis.sku) setActiveSku(res.analysis.sku);
        else if (res.sku) setActiveSku(res.sku);
        loadSkus();
        return true;
      })
      .catch((err) => {
        pending.remove();
        addBubble(t("uploadFailed", { message: err.message }), "system");
        return false;
      })
      .finally(() => setAssistantState(t("assistantReady"), false));
  }

  // ── Photo-library permission + readability gate ───────────────────────
  function requestAlbumPhoto() {
    if (!state.skuId) {
      addBubble(t("selectBeforeUpload"), "system");
      return;
    }
    if (!window.File || !window.FileReader || !("files" in $("#photo-input"))) {
      addBubble(t("albumUnavailable"), "system");
      return;
    }
    addBubble(t("albumPermission"), "system");
    $("#photo-input").click();
  }

  function readAlbumPhoto(file) {
    if (!file || !String(file.type || "").startsWith("image/")) {
      addBubble(t("albumUnreadable"), "system");
      return;
    }
    addBubble(t("albumReading"), "system");
    const reader = new FileReader();
    reader.onload = () => {
      if (!reader.result || !reader.result.byteLength) {
        addBubble(t("albumUnreadable"), "system");
        return;
      }
      addBubble(t("albumReadable"), "system");
      uploadPhoto(file);
    };
    reader.onerror = () => addBubble(t("albumUnreadable"), "system");
    reader.readAsArrayBuffer(file.slice(0, 32));
  }

  // A separate file-folder entry keeps "photo library" and "device file"
  // authorization explicit even when a desktop OS renders similar pickers.
  function requestDeviceFile() {
    if (!state.skuId) {
      addBubble(t("selectBeforeUpload"), "system");
      return;
    }
    if (!window.File || !window.FileReader || !("files" in $("#photo-file-input"))) {
      addBubble(t("fileUnavailable"), "system");
      return;
    }
    addBubble(t("fileOpening"), "system");
    $("#photo-file-input").click();
  }

  function readDeviceFile(file) {
    if (!file || !String(file.type || "").startsWith("image/")) {
      addBubble(t("fileUnreadable"), "system");
      return;
    }
    addBubble(t("fileReading"), "system");
    const reader = new FileReader();
    reader.onload = () => {
      if (!reader.result || !reader.result.byteLength) {
        addBubble(t("fileUnreadable"), "system");
        return;
      }
      addBubble(t("fileReadable"), "system");
      uploadPhoto(file);
    };
    reader.onerror = () => addBubble(t("fileUnreadable"), "system");
    reader.readAsArrayBuffer(file.slice(0, 32));
  }

  // ── USB standard-sample capture (Stage 2) ──────────────────────────────
  function cameraOption(value, label, selected) {
    const option = document.createElement("option");
    option.value = value;
    option.textContent = label;
    option.selected = Boolean(selected);
    return option;
  }

  function setStandardCameraStatus(text, kind) {
    standardCameraStatus.textContent = text || "";
    standardCameraStatus.className = "standard-camera-status" + (kind ? " is-" + kind : "");
  }

  function stopStandardCamera() {
    if (standardCameraStream) {
      standardCameraStream.getTracks().forEach((track) => track.stop());
    }
    standardCameraStream = null;
    standardCameraVideo.srcObject = null;
    pendingStandardSampleBlob = null;
    standardCameraCanvas.classList.add("hidden");
    standardCameraVideo.classList.remove("hidden");
    standardCameraConfirm.classList.add("hidden");
    standardCameraUploadConfirm.disabled = false;
    standardCameraRetake.disabled = false;
    standardCameraCapture.disabled = true;
    standardCameraStop.disabled = true;
    standardCameraStart.disabled = false;
  }

  function populateStandardCameraDevices() {
    if (!navigator.mediaDevices || !navigator.mediaDevices.enumerateDevices) return Promise.resolve();
    return navigator.mediaDevices.enumerateDevices().then((devices) => {
      const activeTrack = standardCameraStream && standardCameraStream.getVideoTracks()[0];
      const activeDeviceId = activeTrack && activeTrack.getSettings ? activeTrack.getSettings().deviceId : "";
      const prior = standardCameraDevice.value || activeDeviceId;
      standardCameraDevice.innerHTML = "";
      standardCameraDevice.appendChild(cameraOption("", t("cameraDefault"), !prior));
      devices.filter((device) => device.kind === "videoinput").forEach((device, index) => {
        const label = device.label || (t("cameraDefault") + " " + (index + 1));
        standardCameraDevice.appendChild(cameraOption(device.deviceId, label, device.deviceId === prior));
      });
    });
  }

  function requestStandardCamera(constraints) {
    return new Promise((resolve, reject) => {
      let finished = false;
      const timer = window.setTimeout(() => {
        finished = true;
        reject(new Error(t("cameraTimeout")));
      }, 12000);
      navigator.mediaDevices.getUserMedia(constraints).then((stream) => {
        if (finished) {
          stream.getTracks().forEach((track) => track.stop());
          return;
        }
        finished = true;
        window.clearTimeout(timer);
        resolve(stream);
      }).catch((error) => {
        if (finished) return;
        finished = true;
        window.clearTimeout(timer);
        reject(error);
      });
    });
  }

  function startStandardCamera() {
    if (!state.skuId) {
      addBubble(t("selectBeforeUpload"), "system");
      return;
    }
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
      setStandardCameraStatus(t("cameraDenied") + " getUserMedia unavailable", "error");
      return;
    }
    stopStandardCamera();
    standardCameraStart.disabled = true;
    const deviceId = standardCameraDevice.value;
    const video = deviceId
      ? { deviceId: { exact: deviceId } }
      : { width: { ideal: 1280 }, height: { ideal: 720 } };
    requestStandardCamera({ video: video, audio: false })
      .then((stream) => {
        standardCameraStream = stream;
        standardCameraVideo.srcObject = stream;
        standardCameraCapture.disabled = false;
        standardCameraStop.disabled = false;
        const track = stream.getVideoTracks()[0];
        const label = track && track.label ? track.label : t("cameraDefault");
        setStandardCameraStatus(t("cameraReady") + ": " + label, "success");
        return populateStandardCameraDevices();
      })
      .catch((error) => {
        standardCameraStart.disabled = false;
        setStandardCameraStatus(t("cameraDenied") + " " + error.message, "error");
      });
  }

  function openStandardCamera() {
    if (!state.skuId) {
      addBubble(t("selectBeforeUpload"), "system");
      return;
    }
    standardCameraPanel.classList.remove("hidden");
    startStandardCamera();
  }

  function closeStandardCamera() {
    stopStandardCamera();
    standardCameraPanel.classList.add("hidden");
  }

  function captureStandardSample() {
    if (!standardCameraStream || !standardCameraVideo.videoWidth || !standardCameraVideo.videoHeight) {
      setStandardCameraStatus(t("cameraRequired"), "error");
      return;
    }
    standardCameraCanvas.width = standardCameraVideo.videoWidth;
    standardCameraCanvas.height = standardCameraVideo.videoHeight;
    standardCameraCanvas.getContext("2d").drawImage(
      standardCameraVideo, 0, 0, standardCameraCanvas.width, standardCameraCanvas.height
    );
    standardCameraCanvas.toBlob((blob) => {
      if (!blob) {
        setStandardCameraStatus(t("cameraCaptureFailed") + " encoding failed", "error");
        return;
      }
      pendingStandardSampleBlob = blob;
      standardCameraVideo.pause();
      standardCameraVideo.classList.add("hidden");
      standardCameraCanvas.classList.remove("hidden");
      standardCameraCapture.disabled = true;
      standardCameraConfirm.classList.remove("hidden");
      setStandardCameraStatus(t("cameraCaptured"), "success");
    }, "image/jpeg", 0.92);
  }

  function uploadCapturedStandardSample() {
    if (!pendingStandardSampleBlob) {
      setStandardCameraStatus(t("cameraCaptureFailed") + " no pending capture", "error");
      return;
    }
    const file = new File(
      [pendingStandardSampleBlob], "mac-usb-standard-sample.jpg", { type: "image/jpeg" }
    );
    standardCameraUploadConfirm.disabled = true;
    standardCameraRetake.disabled = true;
    setStandardCameraStatus(t("cameraUploading"));
    uploadPhoto(file).then((uploaded) => {
      if (uploaded) closeStandardCamera();
      else {
        standardCameraUploadConfirm.disabled = false;
        standardCameraRetake.disabled = false;
      }
    });
  }

  function retakeStandardSample() {
    pendingStandardSampleBlob = null;
    standardCameraCanvas.classList.add("hidden");
    standardCameraVideo.classList.remove("hidden");
    standardCameraConfirm.classList.add("hidden");
    standardCameraCapture.disabled = !standardCameraStream;
    if (standardCameraStream) standardCameraVideo.play();
    setStandardCameraStatus(t("cameraReady"), "success");
  }

  // ── Voice toggle (§5.3) — must not crash ────────────────────────────────
  function voiceToggle() {
    api("/admin/studio/voice", { method: "POST" })
      .then((res) => addBubble(res.message || t("voiceDisabled"), "system"))
      .catch(() => addBubble(t("voiceDisabled"), "system"));
  }

  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])
    );
  }

  // ── Wire up ─────────────────────────────────────────────────────────────
  let searchTimer;
  $("#sku-search").addEventListener("input", () => {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(loadSkus, 200);
  });
  $("#sku-status-filter").addEventListener("change", loadSkus);

  if (initialSkuId) {
    selectSku(initialSkuId).catch(() => loadSkus());
  } else {
    loadSkus();
  }
})();
