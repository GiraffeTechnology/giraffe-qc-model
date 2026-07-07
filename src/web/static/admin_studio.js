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
  const strings = window.GIRAFFE_STUDIO_I18N || {};

  function t(key, vars) {
    let text = strings[key] || key;
    Object.keys(vars || {}).forEach((name) => {
      text = text.replace(new RegExp("\\{" + name + "\\}", "g"), vars[name]);
    });
    return text;
  }

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
        return (
          `<li><span class="dp-code">${esc(dp.point_code)}</span> — ${esc(dp.label)}` +
          `<div class="dp-meta">${esc(bits.join(" · "))}</div>` +
          (dp.pass_criteria ? `<div class="dp-meta">${esc(dp.pass_criteria)}</div>` : "") +
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
      (dps ? `<ul class="dp-list">${dps}</ul>` : `<p class="muted" style="margin-top:12px">${esc(t("noDetectionPoints"))}</p>`) +
      `<div class="publish-row">` +
      `<button class="publish-btn" id="publish-btn" ${canPublish ? "" : "disabled"}>${esc(t("publish"))}</button>` +
      `<div class="bundle-note hidden" id="bundle-note"></div>` +
      `</div>`;

    const pubBtn = $("#publish-btn");
    if (pubBtn) pubBtn.addEventListener("click", publish);
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
        btn.textContent = t("publish");
        btn.disabled = false;
      })
      .catch((err) => {
        addBubble(t("publishFailed", { message: err.message }), "system");
        btn.textContent = t("publish");
        btn.disabled = false;
      });
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
      .catch((err) => addBubble(t("error", { message: err.message }), "system"));
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
          confirmed_by: "qc_supervisor",
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
    api("/admin/studio/upload", { method: "POST", body: fd })
      .then((res) => {
        addBubble(t("photoUploaded"), "system", res.url);
        if (res.sku) setActiveSku(res.sku);
      })
      .catch((err) => addBubble(t("uploadFailed", { message: err.message }), "system"));
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

  addBubble(t("welcome"), "system");
  loadSkus();
})();
