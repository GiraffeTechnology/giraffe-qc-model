/* Admin Studio — chat-first SKU + standard training (S2). */
(function () {
  "use strict";

  const tenant = document.body.dataset.tenant || "default";
  const state = { skuId: null, sku: null };

  const $ = (sel) => document.querySelector(sel);
  const conversation = $("#conversation");
  const skuList = $("#sku-list");
  const skuCard = $("#sku-card");
  const activeChip = $("#active-sku-chip");

  function api(path, opts) {
    return fetch(path, opts).then(async (r) => {
      const data = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(data.error || ("HTTP " + r.status));
      return data;
    });
  }

  // ── Conversation bubbles (§3.4) ─────────────────────────────────────────
  function addBubble(text, who, imageUrl) {
    const b = document.createElement("div");
    b.className = "bubble " + (who === "user" ? "user" : "system");
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
      li.textContent = "No SKUs yet.";
      skuList.appendChild(li);
      return;
    }
    items.forEach((sku) => {
      const li = document.createElement("li");
      if (sku.id === state.skuId) li.classList.add("selected");
      li.innerHTML =
        `<div class="sku-item-number">${esc(sku.item_number)}</div>` +
        `<div class="sku-name">${esc(sku.name)}</div>` +
        `<div class="sku-meta">${esc(sku.status)} · ${esc(sku.standard_status)}</div>`;
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
  }

  function renderCard(sku) {
    if (!sku) {
      skuCard.className = "sku-card empty";
      skuCard.innerHTML = `<p class="muted">Select or create a SKU to see its standard.</p>`;
      return;
    }
    skuCard.className = "sku-card";
    const photo = sku.primary_photo;
    const preview = photo
      ? `<img class="standard-preview" src="${photo.url}" alt="standard photo">`
      : `<div class="standard-preview placeholder">No standard photo yet</div>`;

    const dps = (sku.detection_points || [])
      .map((dp) => {
        const bits = [];
        if (dp.method_hint) bits.push(dp.method_hint);
        if (dp.expected_value) bits.push("expected: " + dp.expected_value);
        bits.push(dp.severity);
        const regionCount = (dp.regions || []).length;
        return (
          `<li data-dp-id="${esc(dp.id)}"><span class="dp-code">${esc(dp.point_code)}</span> — ${esc(dp.label)}` +
          `<div class="dp-meta">${esc(bits.join(" · "))}</div>` +
          (dp.pass_criteria ? `<div class="dp-meta">${esc(dp.pass_criteria)}</div>` : "") +
          `<button type="button" class="btn dp-regions-btn" data-dp-id="${esc(dp.id)}">` +
          (regionCount ? `Regions (${regionCount})` : "Add regions") +
          `</button>` +
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
      `<div><span class="status-badge status-${esc(sku.standard_status)}">${esc(sku.standard_status.replace(/_/g, " "))}</span></div>` +
      (dps ? `<ul class="dp-list">${dps}</ul>` : `<p class="muted" style="margin-top:12px">No confirmed detection points.</p>`) +
      `<div class="publish-row">` +
      `<button class="publish-btn" id="publish-btn" ${canPublish ? "" : "disabled"}>Publish to Pad (L2)</button>` +
      `<div class="bundle-note hidden" id="bundle-note"></div>` +
      `</div>` +
      `<div id="probation-section" class="probation-section"></div>`;

    const pubBtn = $("#publish-btn");
    if (pubBtn) pubBtn.addEventListener("click", publish);

    skuCard.querySelectorAll(".dp-regions-btn").forEach((btn) => {
      btn.addEventListener("click", () => toggleRegionEditor(btn));
    });

    if (sku.active_revision_id) loadProbation(sku.active_revision_id);
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
        slot.innerHTML = `<div class="probation-empty muted">Not yet on probation (publish to start).</div>`;
      });
  }

  function renderProbation(slot, p) {
    const g = p.gate;
    const statusLabel = { active: "On probation", paused: "Probation paused", qualified: "Qualified — solo" }[p.status] || p.status;
    slot.innerHTML =
      `<div class="probation-head">` +
      `<span class="status-badge status-probation-${esc(p.status)}">${esc(statusLabel)}</span>` +
      `<span class="probation-stats">${g.jobs_recorded} job(s) · ${(g.agreement_rate * 100).toFixed(0)}% agreement` +
      (g.min_sample_met ? "" : ` (min ${g.min_sample_size} required)`) +
      `</span>` +
      `</div>` +
      `<div class="probation-actions">` +
      (p.status === "active" ? `<button type="button" class="btn" id="probation-pause">Pause</button>` : "") +
      (p.status === "paused" ? `<button type="button" class="btn btn-primary" id="probation-resume">Resume</button>` : "") +
      (g.jobs_recorded > 0 ? `<button type="button" class="btn" id="probation-report">View disagreement report</button>` : "") +
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
        addBubble(action === "pause" ? "Probation paused." : "Probation resumed.", "system");
        const slot = $("#probation-section");
        if (slot) renderProbation(slot, p);
      })
      .catch((err) => addBubble(`Could not ${action} probation: ${err.message}`, "system"));
  }

  // Reuses the existing conversation bubble component for the disagreement
  // report (per the probation-api.md contract) rather than a new chart/table.
  function showDisagreementReport(probationId) {
    api(`/api/qc/probation/${probationId}/disagreement-report?tenant_id=${tenant}`)
      .then((r) => {
        if (!r.disagreements) {
          addBubble("No disagreements recorded yet — AI and human decisions have matched on every job so far.", "system");
          return;
        }
        const lines = [`${r.disagreements} disagreement(s) out of ${r.gate.jobs_recorded} job(s):`];
        r.detection_points.slice(0, 5).forEach((dp) => {
          lines.push(`  • ${dp.point_code}: ${dp.disagreement_count} disagreement(s)`);
        });
        addBubble(lines.join("\n"), "system");
      })
      .catch((err) => addBubble("Could not load disagreement report: " + err.message, "system"));
  }

  function publish() {
    if (!state.skuId) return;
    const btn = $("#publish-btn");
    btn.disabled = true;
    btn.textContent = "Publishing…";
    api("/admin/studio/publish", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ tenant_id: tenant, sku_id: state.skuId }),
    })
      .then((data) => {
        const b = data.bundle;
        addBubble(
          `Published signed L2 bundle for ${state.sku.item_number} — ` +
          `${b.detection_point_count} detection point(s).`,
          "system"
        );
        const note = $("#bundle-note");
        note.classList.remove("hidden");
        note.textContent = `bundle ${b.id.slice(0, 8)} · ${b.signature_algorithm} · hash ${b.bundle_hash.slice(0, 16)}…`;
        btn.textContent = "Publish to Pad (L2)";
        btn.disabled = false;
      })
      .catch((err) => {
        addBubble("Publish failed: " + err.message, "system");
        btn.textContent = "Publish to Pad (L2)";
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
      addBubble("Upload a standard photo before adding regions.", "system");
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
      opt.textContent = (p.view_type || p.angle || p.id.slice(0, 8)) + (p.is_primary ? " (primary)" : "");
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
        rm.textContent = "Remove";
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
          addBubble(`Saved ${regions.length} region(s) for ${dp.point_code}.`, "system");
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
    return api("/admin/studio/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ tenant_id: tenant, message: text, sku_id: state.skuId }),
    })
      .then((res) => {
        if (res.reply) addBubble(res.reply, "system");
        if (res.sku) setActiveSku(res.sku);
        if (res.action === "created_sku" || res.action === "selected_sku") loadSkus();
        if (res.confirmation_card) renderConfirmCard(res.confirmation_card);
      })
      .catch((err) => addBubble("Error: " + err.message, "system"));
  }

  // ── Confirmation card (§5.5) ────────────────────────────────────────────
  function renderConfirmCard(card) {
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
        html += `<div class="cp-missing">Expected count required</div>`;
      } else if (cp.expected_value) {
        html += `<div class="cp-fields">expected: ${esc(cp.expected_value)}</div>`;
      }
      row.innerHTML = html;
      if (needsCount) {
        const inp = document.createElement("input");
        inp.className = "cp-input";
        inp.type = "text";
        inp.placeholder = "count";
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
        addBubble("Please provide every expected count before confirming.", "system");
        return;
      }
      api("/admin/studio/confirm", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          tenant_id: tenant,
          intake_id: card.intake_id,
          confirmed_by: "qc_supervisor",
          checkpoints: checkpoints,
        }),
      })
        .then((res) => {
          root.querySelector(".confirm-actions").innerHTML =
            `<span class="muted">Confirmed — revision ${res.revision_no}.</span>`;
          addBubble(
            `Saved ${checkpoints.length} detection point(s) to revision ${res.revision_no}. ` +
            `You can now publish to Pad.`,
            "system"
          );
          if (res.sku) setActiveSku(res.sku);
          loadSkus();
        })
        .catch((err) => addBubble("Confirm failed: " + err.message, "system"));
    });

    root.querySelector(".confirm-no").addEventListener("click", () => {
      api("/admin/studio/reject", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ tenant_id: tenant, intake_id: card.intake_id }),
      }).finally(() => {
        root.querySelector(".confirm-actions").innerHTML =
          `<span class="muted">Rejected.</span>`;
      });
    });

    conversation.appendChild(tpl);
    conversation.scrollTop = conversation.scrollHeight;
  }

  // ── Upload (§5.3) ───────────────────────────────────────────────────────
  function uploadPhoto(file) {
    if (!state.skuId) {
      addBubble("Select or create a SKU before uploading a standard photo.", "system");
      return;
    }
    const fd = new FormData();
    fd.append("sku_id", state.skuId);
    fd.append("tenant_id", tenant);
    fd.append("image", file);
    addBubble("Uploading standard photo…", "user");
    api("/admin/studio/upload", { method: "POST", body: fd })
      .then((res) => {
        addBubble("Standard photo uploaded.", "system", res.url);
        if (res.sku) setActiveSku(res.sku);
      })
      .catch((err) => addBubble("Upload failed: " + err.message, "system"));
  }

  // ── Voice toggle (§5.3) — must not crash ────────────────────────────────
  function voiceToggle() {
    api("/admin/studio/voice", { method: "POST" })
      .then((res) => addBubble(res.message || "Voice input is not enabled yet.", "system"))
      .catch(() => addBubble("Voice input is not enabled yet.", "system"));
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

  addBubble(
    "Welcome to Admin Studio. Create a SKU (e.g. “create sku FLW-001 Flower Brooch”) " +
    "or select one on the left to train its QC standard.",
    "system"
  );
  loadSkus();
})();
