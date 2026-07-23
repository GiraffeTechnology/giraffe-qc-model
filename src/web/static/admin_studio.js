/* Admin Studio — SKU training and publish workspace (S2). Standard
   authoring (chat, region annotation, CV config) lives on the sample
   page (sample_standard_authoring.js); this workspace only trains,
   qualifies, and publishes the standard that page produces. */
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
  const strings = window.GIRAFFE_STUDIO_I18N || {};
  const studioCamera = { stream: null };

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
    syncStudioCameraControls();
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

    // Detection points are authored and confirmed on the sample page (§2);
    // this card only needs a read-only summary for training/publish context.
    const dps = (sku.detection_points || [])
      .map((dp) => {
        const bits = [];
        if (dp.method_hint) bits.push(dp.method_hint);
        if (dp.expected_value) bits.push(t("expected", { value: dp.expected_value }));
        bits.push(dp.severity);
        return (
          `<li data-dp-id="${esc(dp.id)}"><span class="dp-code">${esc(dp.point_code)}</span> — ${esc(dp.label)}` +
          `<div class="dp-meta">${esc(bits.join(" · "))}</div>` +
          (dp.pass_criteria ? `<div class="dp-meta">${esc(dp.pass_criteria)}</div>` : "") +
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

    if (sku.active_revision_id) {
      loadProbation(sku.active_revision_id);
      renderTraining($("#training-review-section"), sku);
    }
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
  // per-decision admin review, rolling 30-sample publish gate. The gate
  // itself (sku.training) already arrives on the SKU summary; this section
  // additionally loads the pending review queue and lets the admin record
  // new judgments and submit decisions.
  function renderTraining(slot, sku) {
    if (!slot) return;
    const status = sku.training;
    const badge = status && status.qualified
      ? `<span class="status-badge status-training-qualified">${esc(t("trainingQualified"))}</span>`
      : `<span class="status-badge status-training-pending">${esc(t("trainingNotQualified"))}</span>`;
    const window30 = status && status.recent_30_correct != null
      ? t("trainingWindowStats", { correct: status.recent_30_correct, size: 30 }) : null;
    const reviewedCount = status ? Math.min(status.total_reviewed || 0, 30) : 0;
    const correctCount = status && status.recent_30_correct != null ? status.recent_30_correct : 0;
    const falsePassNote = status && status.recent_30_false_pass_count > 0
      ? `<div class="training-false-pass">${esc(t("trainingFalsePass", { count: status.recent_30_false_pass_count }))}</div>` : "";
    slot.innerHTML =
      `<div class="training-head">` +
      `<strong>${esc(t("trainingHeading"))}</strong> ${badge}` +
      `</div>` +
      `<div class="training-window-card"><strong>${esc(t("trainingWindowProgress", { reviewed: reviewedCount, correct: correctCount }))}</strong></div>` +
      `<div class="training-stats muted">` +
      (window30 || t("trainingNoSamples")) +
      `</div>` +
      falsePassNote +
      `<div class="training-form">` +
      `<p class="muted">${esc(t("trainingSampleSource"))}</p>` +
      `<label><input type="radio" name="training-truth" value="qualified" checked> ${esc(t("trainingGroundTruthQualified"))}</label>` +
      `<label><input type="radio" name="training-truth" value="unqualified"> ${esc(t("trainingGroundTruthUnqualified"))}</label>` +
      `<button type="button" class="btn" id="training-submit-btn">${esc(t("trainingSubmitSample"))}</button>` +
      `</div>` +
      `<div id="training-queue" class="training-queue"></div>`;

    const submitBtn = slot.querySelector("#training-submit-btn");
    if (submitBtn) submitBtn.addEventListener("click", () => submitTrainingSample(sku.id));
    loadTrainingQueue(sku.id);
  }

  function setStudioCameraStatus(text, kind) {
    const status = $("#studio-camera-status");
    if (!status) return;
    status.textContent = text;
    status.className = "studio-camera-status" + (kind ? " is-" + kind : "");
  }

  function syncStudioCameraControls() {
    const video = $("#studio-camera-preview");
    const capture = $("#studio-camera-capture");
    const start = $("#studio-camera-start");
    const stop = $("#studio-camera-stop");
    const live = Boolean(studioCamera.stream);
    if (video) video.hidden = !live;
    if (start) start.disabled = live;
    if (capture) capture.disabled = !live || !state.skuId;
    if (stop) stop.disabled = !live;
  }

  async function startStudioCamera() {
    try {
      studioCamera.stream = await navigator.mediaDevices.getUserMedia({ video: true, audio: false });
      const video = $("#studio-camera-preview");
      video.srcObject = studioCamera.stream;
      await video.play();
      setStudioCameraStatus(t("trainingCameraReady"), "success");
      syncStudioCameraControls();
    } catch (err) {
      studioCamera.stream = null;
      setStudioCameraStatus(t("trainingCameraDenied") + " " + (err.message || ""), "error");
      syncStudioCameraControls();
    }
  }

  function stopStudioCamera() {
    if (studioCamera.stream) studioCamera.stream.getTracks().forEach((track) => track.stop());
    studioCamera.stream = null;
    const video = $("#studio-camera-preview");
    if (video) video.srcObject = null;
    setStudioCameraStatus(t("trainingCameraRequired"));
    syncStudioCameraControls();
  }

  function submitTrainingSample(skuId) {
    if (!studioCamera.stream) {
      addBubble(t("trainingCameraRequired"), "system");
      return;
    }
    if (!skuId) {
      addBubble(t("trainingCaptureSkuFirst"), "system");
      return;
    }
    const video = $("#studio-camera-preview");
    const canvas = $("#studio-camera-canvas");
    if (!video || !canvas || !video.videoWidth || !video.videoHeight) {
      setStudioCameraStatus(t("trainingCameraFailed"), "error");
      return;
    }
    canvas.width = video.videoWidth;
    canvas.height = video.videoHeight;
    canvas.getContext("2d").drawImage(video, 0, 0, canvas.width, canvas.height);
    const truthInput = document.querySelector('input[name="training-truth"]:checked');
    const groundTruth = truthInput ? truthInput.value : "qualified";
    canvas.toBlob((blob) => {
      if (!blob) {
        setStudioCameraStatus(t("trainingCameraFailed"), "error");
        return;
      }
      const fd = new FormData();
      fd.append("tenant_id", tenant);
      fd.append("ground_truth_label", groundTruth);
      fd.append("capture_source", "usb_camera");
      fd.append("image", blob, "usb-training-frame.jpg");
      addBubble(t("trainingRunning"), "system");
      api(`/admin/studio/skus/${skuId}/training/judgments`, { method: "POST", body: fd })
        .then(() => {
          setStudioCameraStatus(t("trainingCameraCaptured"), "success");
          addBubble(t("trainingRecorded"), "system");
          loadTrainingQueue(skuId);
        })
        .catch((err) => addBubble(t("trainingFailed", { message: err.message }), "system"));
    }, "image/jpeg", 0.92);
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
    const mutationCredential = window.prompt(t("mutationPrompt"));
    if (!mutationCredential) return;
    const btn = $("#publish-btn");
    btn.disabled = true;
    btn.textContent = t("publishing");
    api("/admin/studio/publish", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        tenant_id: tenant,
        sku_id: state.skuId,
        mutation_credential: mutationCredential,
      }),
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
  $("#studio-camera-start").addEventListener("click", startStudioCamera);
  $("#studio-camera-stop").addEventListener("click", stopStudioCamera);
  $("#studio-camera-capture").addEventListener("click", () => submitTrainingSample(state.skuId));
  window.addEventListener("beforeunload", stopStudioCamera);

  if (initialSkuId) {
    selectSku(initialSkuId).catch(() => loadSkus());
  } else {
    loadSkus();
  }
})();
