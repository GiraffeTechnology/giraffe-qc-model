/* Admin Studio — chat-first SKU + standard training (S2). */
(function () {
  "use strict";

  const tenant = document.body.dataset.tenant || "default";
  const state = { skuId: null, sku: null, renderedIntakes: new Set() };

  const $ = (sel) => document.querySelector(sel);
  const conversation = $("#conversation");
  const skuList = $("#sku-list");
  const skuCard = $("#sku-card");
  const activeChip = $("#active-sku-chip");
  const assistantState = $("#assistant-state");
  const strings = window.GIRAFFE_STUDIO_I18N || {};

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
    renderCard(sku);
    if (sku && sku.pending_confirmation &&
        !state.renderedIntakes.has(sku.pending_confirmation.intake_id)) {
      state.renderedIntakes.add(sku.pending_confirmation.intake_id);
      renderConfirmCard(sku.pending_confirmation);
    }
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

    const canPublish = sku.standard_status === "standard_active";
    skuCard.innerHTML =
      `<h3>${esc(sku.name)}</h3>` +
      `<div class="sku-sub">${esc(sku.item_number)}${sku.category ? " · " + esc(sku.category) : ""}</div>` +
      preview +
      `<div class="standard-facts">` +
      `<span><small>${esc(t("lifecycle"))}</small><strong>${esc(statusLabel(sku.status))}</strong></span>` +
      `<span><small>${esc(t("revision"))}</small><strong>${esc(sku.active_revision_no || "—")}</strong></span>` +
      `<span><small>${esc(t("confirmedPoints"))}</small><strong>${esc(sku.detection_point_count || 0)}</strong></span>` +
      `</div>` +
      `<div><span class="status-badge status-${esc(sku.standard_status)}">${esc(standardStatusLabel(sku.standard_status))}</span></div>` +
      (dps ? `<ul class="dp-list">${dps}</ul>` : `<p class="muted" style="margin-top:12px">${esc(t("noDetectionPoints"))}</p>`) +
      `<div class="publish-row">` +
      `<button class="publish-btn" id="publish-btn" ${canPublish ? "" : "disabled"}>${esc(t("publish"))}</button>` +
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

    if (sku.active_revision_id) loadProbation(sku.active_revision_id);
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
      })
      .catch((err) => {
        pending.remove();
        addBubble(t("error", { message: err.message }), "system");
      })
      .finally(() => setAssistantState(t("assistantReady"), false));
  }

  // ── Confirmation card (§5.5) ────────────────────────────────────────────
  function renderConfirmCard(card) {
    state.renderedIntakes.add(card.intake_id);
    const tpl = $("#confirm-card-template").content.cloneNode(true);
    const root = tpl.querySelector(".confirm-card");
    const body = tpl.querySelector(".confirm-body");

    const inputs = {};
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
      return;
    }
    const fd = new FormData();
    fd.append("sku_id", state.skuId);
    fd.append("tenant_id", tenant);
    fd.append("image", file);
    addBubble(t("uploadingPhoto"), "user");
    setAssistantState(t("visionThinking"), true);
    const pending = addBubble(t("visionThinking"), "pending");
    api("/admin/studio/upload", { method: "POST", body: fd })
      .then((res) => {
        pending.remove();
        addBubble(t("photoUploaded"), "system", res.url);
        if (res.analysis_error) {
          addBubble(t("visionFailed", { message: res.analysis_error }), "system");
        } else if (res.analysis) {
          if (res.analysis.reply) addBubble(res.analysis.reply, "system");
          showAssistantMeta(res.analysis.assistant);
          if (res.analysis.confirmation_card) renderConfirmCard(res.analysis.confirmation_card);
        }
        if (res.analysis && res.analysis.sku) setActiveSku(res.analysis.sku);
        else if (res.sku) setActiveSku(res.sku);
        loadSkus();
      })
      .catch((err) => {
        pending.remove();
        addBubble(t("uploadFailed", { message: err.message }), "system");
      })
      .finally(() => setAssistantState(t("assistantReady"), false));
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
  $("#chat-form").addEventListener("submit", (e) => {
    e.preventDefault();
    const input = $("#chat-text");
    const text = input.value.trim();
    if (!text) return;
    input.value = "";
    sendChat(text);
  });
  $("#photo-input").addEventListener("change", (e) => {
    if (e.target.files && e.target.files[0]) uploadPhoto(e.target.files[0]);
    e.target.value = "";
  });
  $("#voice-toggle").addEventListener("click", voiceToggle);
  let searchTimer;
  $("#sku-search").addEventListener("input", () => {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(loadSkus, 200);
  });
  $("#sku-status-filter").addEventListener("change", loadSkus);

  api("/admin/studio/conversation")
    .then((history) => {
      const messages = history.messages || [];
      if (!messages.length) addBubble(t("welcome"), "system");
      else messages.forEach((item) => addBubble(item.text, item.role === "user" ? "user" : "system"));
    })
    .catch(() => addBubble(t("welcome"), "system"));
  api("/admin/studio/assistants")
    .then((status) => {
      const ready = status.text && status.text.configured && status.vision && status.vision.configured;
      setAssistantState(ready ? t("assistantReady") : t("assistantUnavailable"), false);
    })
    .catch(() => setAssistantState(t("assistantUnavailable"), false));
  loadSkus();
})();
