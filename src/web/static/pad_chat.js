(function () {
  'use strict';

  var chatMessages = document.getElementById('chat-messages');
  var chatInput = document.getElementById('chat-input');
  var sendBtn = document.getElementById('send-btn');
  var voiceBtn = document.getElementById('voice-btn');
  var imageUpload = document.getElementById('image-upload');
  var languageSelect = document.getElementById('language-select');
  var actionCards = document.getElementById('action-cards');

  var i18n = window.GIRAFFE_PAD_I18N || {};
  function t(key, fallback) { return i18n[key] || fallback; }

  var mediaRecorder = null;
  var audioChunks = [];
  var context = {};

  function appendMessage(role, text) {
    var div = document.createElement('div');
    div.className = 'message ' + role;
    div.textContent = text;
    chatMessages.appendChild(div);
    chatMessages.scrollTop = chatMessages.scrollHeight;
  }

  function renderActionCard(card) {
    if (!card || !actionCards) return;
    actionCards.innerHTML = '';
    var cardType = card.type || card.action_type || '';
    var div = document.createElement('div');
    div.className = 'action-card';
    div.setAttribute('data-card-type', cardType);

    if (cardType === 'standard_confirmation') {
      div.innerHTML =
        '<strong></strong>' +
        '<p style="margin:0.5rem 0;font-size:0.85rem;color:#64748b">' +
          t('sourceLabel', 'Source:') + ' ' + (card.source_language || 'unknown') +
        '</p>' +
        '<p style="margin:0.5rem 0">' + (card.canonical_english_text || '') + '</p>';

      div.querySelector('strong').textContent =
        t('standardConfirmationRequired', 'Standard Confirmation Required');

      var checkpointList = document.createElement('ul');
      checkpointList.style.cssText = 'margin:0.5rem 0;padding-left:1.25rem;font-size:0.9rem';
      (card.checkpoints || []).forEach(function (cp) {
        var li = document.createElement('li');
        li.setAttribute('data-point-code', cp.point_code);
        var val = cp.expected_value ? ' = ' + cp.expected_value : '';
        li.textContent = cp.label + val + ' [' + cp.severity + ']';
        checkpointList.appendChild(li);
      });
      div.appendChild(checkpointList);

      var btnRow = document.createElement('div');
      btnRow.style.cssText = 'display:flex;gap:0.5rem;margin-top:0.75rem';

      var confirmBtn = document.createElement('button');
      confirmBtn.className = 'btn-primary qc-action-btn';
      confirmBtn.setAttribute('data-action', 'confirm-standard');
      confirmBtn.textContent = t('confirmStandard', 'Confirm Standard');
      confirmBtn.onclick = function () { confirmStandard(card.intake_id); };
      btnRow.appendChild(confirmBtn);

      var editBtn = document.createElement('button');
      editBtn.className = 'btn-secondary qc-action-btn';
      editBtn.setAttribute('data-action', 'edit-standard');
      editBtn.textContent = t('edit', 'Edit');
      editBtn.disabled = true;
      btnRow.appendChild(editBtn);

      var rejectBtn = document.createElement('button');
      rejectBtn.className = 'btn-secondary qc-action-btn';
      rejectBtn.setAttribute('data-action', 'reject-standard');
      rejectBtn.textContent = t('reject', 'Reject');
      rejectBtn.onclick = function () { appendMessage('assistant', t('standardRejected', 'Standard rejected.')); actionCards.innerHTML = ''; };
      btnRow.appendChild(rejectBtn);

      div.appendChild(btnRow);
    } else {
      div.innerHTML = '<strong>' + cardType + '</strong>';
      if ((cardType === 'confirm_intake' || cardType === 'confirm_standard') && card.intake_id) {
        var btn = document.createElement('button');
        btn.className = 'btn-primary qc-action-btn';
        btn.style.cssText = 'margin-top:0.5rem;display:block';
        btn.textContent = t('confirm', 'Confirm');
        btn.onclick = function () { confirmStandard(card.intake_id); };
        div.appendChild(btn);
      }
    }

    actionCards.appendChild(div);
  }

  function sendMessage(text) {
    if (!text.trim()) return;
    appendMessage('user', text);
    chatInput.value = '';

    fetch('/api/v1/pad/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message: text, context: context }),
    })
      .then(function (res) { return res.json(); })
      .then(function (data) {
        appendMessage('assistant', data.reply || t('noReply', 'No reply'));
        if (data.action_card) {
          renderActionCard(data.action_card);
          if (data.action_card.action_type === 'start_inspection') {
            context.intent = 'start_inspection';
          }
        }
      })
      .catch(function (err) {
        appendMessage('assistant', t('errorPrefix', 'Error:') + ' ' + err.message);
      });
  }

  function confirmStandard(intakeId) {
    fetch('/api/v1/pad/confirm_standard', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ intake_id: intakeId }),
    })
      .then(function (res) { return res.json(); })
      .then(function (data) {
        if (data.status === 'confirmed') {
          appendMessage('assistant', t('standardConfirmedPrefix', 'Standard confirmed. Revision ID:') + ' ' + data.revision_id);
          actionCards.innerHTML = '<p style="color:#16a34a;font-weight:600"></p>';
          actionCards.firstChild.textContent = t('standardActivated', '✓ Standard activated');
        } else {
          appendMessage('assistant', t('confirmFailedPrefix', 'Confirmation failed:') + ' ' + (data.error || t('unknownError', 'unknown error')));
        }
      })
      .catch(function (err) {
        appendMessage('assistant', t('confirmFailedPrefix', 'Confirmation failed:') + ' ' + err.message);
      });
  }

  function showTranscriptArea(transcript) {
    var area = document.createElement('div');
    area.id = 'voice-transcript-area';
    area.style.cssText = 'padding:0.75rem;background:#fef9c3;border:1px solid #fde047;border-radius:6px;margin-bottom:0.5rem';
    area.innerHTML = '<p style="font-size:0.85rem;margin-bottom:0.4rem"></p>';
    area.firstChild.textContent = t('voiceTranscriptHint', 'Voice transcript — edit before sending:');
    var ta = document.createElement('textarea');
    ta.rows = 2;
    ta.style.cssText = 'width:100%;padding:0.4rem;font-size:0.9rem;border:1px solid #cbd5e1;border-radius:4px';
    ta.value = transcript || '';
    area.appendChild(ta);
    var sendTransBtn = document.createElement('button');
    sendTransBtn.className = 'btn-primary qc-action-btn';
    sendTransBtn.style.cssText = 'margin-top:0.4rem;font-size:0.85rem;padding:0.3rem 0.9rem';
    sendTransBtn.textContent = t('sendTranscript', 'Send Transcript');
    sendTransBtn.onclick = function () {
      var text = ta.value.trim();
      if (text) { sendMessage(text); }
      var existing = document.getElementById('voice-transcript-area');
      if (existing) existing.remove();
    };
    area.appendChild(sendTransBtn);
    var inputArea = document.querySelector('.chat-input-area');
    if (inputArea) inputArea.insertBefore(area, inputArea.firstChild);
  }

  function startVoice() {
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
      appendMessage('assistant', t('voiceNotSupported', 'Voice input not supported in this browser.'));
      return;
    }
    navigator.mediaDevices.getUserMedia({ audio: true }).then(function (stream) {
      mediaRecorder = new MediaRecorder(stream);
      audioChunks = [];
      mediaRecorder.ondataavailable = function (e) { audioChunks.push(e.data); };
      mediaRecorder.onstop = function () {
        var blob = new Blob(audioChunks, { type: 'audio/webm' });
        var form = new FormData();
        form.append('audio', blob, 'recording.webm');
        fetch('/api/v1/pad/voice', { method: 'POST', body: form })
          .then(function (res) { return res.json(); })
          .then(function (data) {
            // Show editable transcript area so operator can confirm before submitting
            showTranscriptArea(data.transcript || '');
            appendMessage('assistant', data.message || 'Voice processed — edit transcript and send.');
          });
        stream.getTracks().forEach(function (t) { t.stop(); });
      };
      mediaRecorder.start();
      voiceBtn.textContent = t('stop', 'Stop');
      voiceBtn.onclick = stopVoice;
    });
  }

  function stopVoice() {
    if (mediaRecorder && mediaRecorder.state !== 'inactive') {
      mediaRecorder.stop();
    }
    voiceBtn.textContent = t('voice', 'Voice');
    voiceBtn.onclick = startVoice;
  }

  function setLanguage(lang) {
    fetch('/api/v1/pad/language', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ language: lang }),
    }).then(function () {
      // Server also syncs the shell language cookie; reload so page chrome
      // (templates) re-renders in the newly selected language.
      window.location.reload();
    });
  }

  if (sendBtn) {
    sendBtn.onclick = function () { sendMessage(chatInput.value); };
  }
  if (chatInput) {
    chatInput.addEventListener('keydown', function (e) {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        sendMessage(chatInput.value);
      }
    });
  }
  if (voiceBtn) {
    voiceBtn.onclick = startVoice;
  }
  if (imageUpload) {
    imageUpload.onchange = function () {
      var file = imageUpload.files[0];
      if (!file) return;
      var form = new FormData();
      form.append('image', file);
      fetch('/api/v1/pad/upload', { method: 'POST', body: form })
        .then(function (res) { return res.json(); })
        .then(function (data) {
          appendMessage('assistant', 'Image uploaded: ' + data.filename);
        });
    };
  }
  if (languageSelect) {
    languageSelect.onchange = function () { setLanguage(languageSelect.value); };
  }
})();
