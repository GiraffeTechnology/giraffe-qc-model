(function () {
  'use strict';

  var chatMessages = document.getElementById('chat-messages');
  var chatInput = document.getElementById('chat-input');
  var sendBtn = document.getElementById('send-btn');
  var voiceBtn = document.getElementById('voice-btn');
  var imageUpload = document.getElementById('image-upload');
  var languageSelect = document.getElementById('language-select');
  var actionCards = document.getElementById('action-cards');

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
    var div = document.createElement('div');
    div.className = 'action-card';
    div.innerHTML = '<strong>' + card.action_type + '</strong>';
    if (card.action_type === 'confirm_intake' && card.payload.intake_id) {
      var btn = document.createElement('button');
      btn.className = 'btn-primary qc-action-btn';
      btn.style.marginTop = '0.5rem';
      btn.style.display = 'block';
      btn.textContent = 'Confirm';
      btn.onclick = function () { confirmIntake(card.payload.intake_id); };
      div.appendChild(btn);
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
        appendMessage('assistant', data.reply || 'No reply');
        if (data.action_card) {
          renderActionCard(data.action_card);
          if (data.action_card.action_type === 'start_inspection') {
            context.intent = 'start_inspection';
          }
        }
      })
      .catch(function (err) {
        appendMessage('assistant', 'Error: ' + err.message);
      });
  }

  function confirmIntake(intakeId) {
    fetch('/api/v1/pad/confirm_standard', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ intake_id: intakeId }),
    })
      .then(function (res) { return res.json(); })
      .then(function (data) {
        appendMessage('assistant', 'Standard confirmed (intake #' + intakeId + ')');
      });
  }

  function startVoice() {
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
      appendMessage('assistant', 'Voice input not supported in this browser.');
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
            appendMessage('assistant', data.message || 'Voice processed');
          });
        stream.getTracks().forEach(function (t) { t.stop(); });
      };
      mediaRecorder.start();
      voiceBtn.textContent = 'Stop';
      voiceBtn.onclick = stopVoice;
    });
  }

  function stopVoice() {
    if (mediaRecorder && mediaRecorder.state !== 'inactive') {
      mediaRecorder.stop();
    }
    voiceBtn.textContent = 'Voice';
    voiceBtn.onclick = startVoice;
  }

  function setLanguage(lang) {
    fetch('/api/v1/pad/language', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ language: lang }),
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
