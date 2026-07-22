(function () {
  'use strict';

  var config = window.GIRAFFE_PAD_INSPECTION || {};
  var jobId = config.jobId;
  var s = config.strings || {};
  var list = document.getElementById('checkpoints-list');
  var status = document.getElementById('inspection-status');
  var mediaStatus = document.getElementById('media-status');
  var submitButton = document.getElementById('submit-results-btn');
  var runVisionButton = document.getElementById('run-vision-btn');
  var fixtureUpload = document.getElementById('fixture-upload');
  var video = document.getElementById('camera-preview');
  var canvas = document.getElementById('camera-canvas');
  var standardPhoto = document.getElementById('standard-photo');
  var standardPhotoMissing = document.getElementById('standard-photo-missing');
  var deviceSelect = document.getElementById('camera-device-select');
  var startButton = document.getElementById('camera-start-btn');
  var stopButton = document.getElementById('camera-stop-btn');
  var cameraStream = null;
  var currentJob = null;
  var autoDetectionTimer = null;
  var autoDetectionBusy = false;
  var autoCaptureCommitted = false;
  var consecutiveDetections = 0;

  function setStatus(text, kind) {
    status.textContent = text || '';
    status.className = 'inspection-status' + (kind ? ' is-' + kind : '');
  }

  function fetchJson(url, options) {
    return fetch(url, options).then(function (response) {
      return response.json().then(function (data) {
        if (!response.ok) throw new Error(data.error || data.detail || ('HTTP ' + response.status));
        return data;
      });
    });
  }

  function resultOption(value, label, selected) {
    var option = document.createElement('option');
    option.value = value;
    option.textContent = label;
    option.selected = selected;
    return option;
  }

  function renderJob(job) {
    currentJob = job;
    if (job.standard_photo && job.standard_photo.url) {
      standardPhoto.src = job.standard_photo.url;
      standardPhoto.hidden = false;
      standardPhotoMissing.hidden = true;
    } else {
      standardPhoto.removeAttribute('src');
      standardPhoto.hidden = true;
      standardPhotoMissing.hidden = false;
    }
    list.innerHTML = '';
    if (!job.checkpoints.length) {
      var empty = document.createElement('p');
      empty.className = 'error-banner';
      empty.textContent = s.error + ' no active detection points';
      list.appendChild(empty);
      submitButton.disabled = true;
      return;
    }
    job.checkpoints.forEach(function (point) {
      var card = document.createElement('article');
      card.className = 'checkpoint-card';
      card.dataset.pointId = point.id;
      card.dataset.pointCode = point.point_code;
      var header = document.createElement('header');
      var title = document.createElement('strong');
      title.textContent = point.point_code + ' · ' + point.label;
      var severity = document.createElement('span');
      severity.textContent = point.severity;
      header.appendChild(title);
      header.appendChild(severity);
      card.appendChild(header);
      if (point.description) {
        var description = document.createElement('p');
        description.textContent = point.description;
        card.appendChild(description);
      }
      var select = document.createElement('select');
      select.className = 'checkpoint-result';
      select.setAttribute('aria-label', point.label);
      select.appendChild(resultOption('', s.chooseResult || 'Choose result', !point.submitted_result));
      select.appendChild(resultOption('pass', s.pass || 'Pass', point.submitted_result === 'pass'));
      select.appendChild(resultOption('fail', s.fail || 'Fail', point.submitted_result === 'fail'));
      select.appendChild(resultOption('not_visible', s.notVisible || 'Not visible', point.submitted_result === 'not_visible'));
      select.appendChild(resultOption('low_confidence', s.lowConfidence || 'Low confidence', point.submitted_result === 'low_confidence'));
      select.disabled = Boolean(point.submitted_result || job.final_report);
      card.appendChild(select);
      list.appendChild(card);
    });
    mediaStatus.textContent = job.media_count > 0 ? (s.mediaAttached + ' (' + job.media_count + ')') : s.noMedia;
    runVisionButton.disabled = !job.media_count || Boolean(job.final_report) ||
      job.checkpoints.some(function (point) { return Boolean(point.submitted_result); });
    if (job.final_report) {
      submitButton.disabled = true;
      setStatus((s.finalized || 'Final verdict:') + ' ' + job.final_report.overall_result + '\n' + (job.final_report.summary_text || ''), 'success');
    }
  }

  function loadJob() {
    return fetchJson('/api/v1/pad/inspection-jobs/' + encodeURIComponent(jobId), {cache: 'no-store'})
      .then(renderJob)
      .catch(function (error) { setStatus((s.error || 'Inspection error:') + ' ' + error.message, 'error'); });
  }

  // Client-side stage timings for the 10s SLO record: capture (frame encode)
  // and upload (media POST) happen in the browser, so the browser reports them.
  var stageTimings = {};

  function attachImage(file, source) {
    var form = new FormData();
    form.append('image', file, file.name || 'capture.jpg');
    form.append('capture_source', source);
    mediaStatus.textContent = s.loading || 'Loading…';
    var uploadStarted = performance.now();
    return fetchJson('/api/v1/pad/inspection-jobs/' + encodeURIComponent(jobId) + '/media', {
      method: 'POST', body: form,
    }).then(function (data) {
      stageTimings.upload_ms = Math.round(performance.now() - uploadStarted);
      mediaStatus.textContent = (s.mediaAttached || 'Evidence attached') + ' · ' + data.source + ' · ' + data.sha256.slice(0, 12);
      return loadJob();
    }).catch(function (error) {
      setStatus((s.error || 'Inspection error:') + ' ' + error.message, 'error');
      throw error;
    });
  }

  function stopCamera() {
    if (autoDetectionTimer) clearTimeout(autoDetectionTimer);
    autoDetectionTimer = null;
    autoDetectionBusy = false;
    autoCaptureCommitted = false;
    consecutiveDetections = 0;
    if (cameraStream) cameraStream.getTracks().forEach(function (track) { track.stop(); });
    cameraStream = null;
    video.srcObject = null;
    stopButton.disabled = true;
    startButton.disabled = false;
  }

  function populateDevices() {
    if (!navigator.mediaDevices || !navigator.mediaDevices.enumerateDevices) return Promise.resolve();
    return navigator.mediaDevices.enumerateDevices().then(function (devices) {
      var activeTrack = cameraStream && cameraStream.getVideoTracks()[0];
      var activeDeviceId = activeTrack && activeTrack.getSettings ? activeTrack.getSettings().deviceId : '';
      var prior = deviceSelect.value || activeDeviceId;
      deviceSelect.innerHTML = '';
      deviceSelect.appendChild(resultOption('', s.cameraDefault || 'System default camera', !prior));
      devices.filter(function (device) { return device.kind === 'videoinput'; }).forEach(function (device, index) {
        var label = device.label || ('Camera ' + (index + 1));
        deviceSelect.appendChild(resultOption(device.deviceId, label, device.deviceId === prior));
      });
    });
  }

  function getCameraStream(constraints) {
    return new Promise(function (resolve, reject) {
      var finished = false;
      var timer = setTimeout(function () {
        finished = true;
        reject(new Error(s.cameraTimeout || 'Camera permission timed out. Allow camera access in Chrome and retry.'));
      }, 12000);
      navigator.mediaDevices.getUserMedia(constraints).then(function (stream) {
        if (finished) {
          stream.getTracks().forEach(function (track) { track.stop(); });
          return;
        }
        finished = true;
        clearTimeout(timer);
        resolve(stream);
      }).catch(function (error) {
        if (finished) return;
        finished = true;
        clearTimeout(timer);
        reject(error);
      });
    });
  }

  function startCamera() {
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
      setStatus((s.cameraDenied || 'Camera unavailable or permission denied:') + ' getUserMedia unavailable', 'error');
      return;
    }
    stopCamera();
    startButton.disabled = true;
    var deviceId = deviceSelect.value;
    var videoConstraint = deviceId ? {deviceId: {exact: deviceId}} : {width: {ideal: 1280}, height: {ideal: 720}};
    getCameraStream({video: videoConstraint, audio: false})
      .then(function (stream) {
        cameraStream = stream;
        video.srcObject = stream;
        stopButton.disabled = false;
        var track = stream.getVideoTracks()[0];
        var label = track && track.label ? track.label : (s.cameraDefault || 'System default camera');
        mediaStatus.textContent = (s.cameraReady || 'USB camera ready') + ': ' + label + ' · ' +
          (s.instanceSearching || 'CV is looking for a stable instance in the live video…');
        return populateDevices().then(scheduleAutoDetection);
      })
      .catch(function (error) {
        startButton.disabled = false;
        setStatus((s.cameraDenied || 'Camera unavailable or permission denied:') + ' ' + error.message, 'error');
      });
  }

  function frameFile(name, quality) {
    return new Promise(function (resolve, reject) {
      if (!cameraStream || !video.videoWidth || !video.videoHeight) {
        reject(new Error(s.cameraRequired || 'Connect and start a USB camera first.'));
        return;
      }
      var captureStarted = performance.now();
      canvas.width = video.videoWidth;
      canvas.height = video.videoHeight;
      canvas.getContext('2d').drawImage(video, 0, 0, canvas.width, canvas.height);
      canvas.toBlob(function (blob) {
        if (!blob) {
          reject(new Error('capture encoding failed'));
          return;
        }
        resolve({
          file: new File([blob], name, {type: 'image/jpeg'}),
          elapsedMs: Math.round(performance.now() - captureStarted),
        });
      }, 'image/jpeg', quality);
    });
  }

  function scheduleAutoDetection() {
    if (!cameraStream || autoCaptureCommitted || autoDetectionTimer) return;
    autoDetectionTimer = setTimeout(function () {
      autoDetectionTimer = null;
      detectInstanceFrame();
    }, 900);
  }

  function detectInstanceFrame() {
    if (!cameraStream || autoCaptureCommitted || autoDetectionBusy) return;
    if (!video.videoWidth || !video.videoHeight) {
      scheduleAutoDetection();
      return;
    }
    autoDetectionBusy = true;
    frameFile('cv-probe.jpg', 0.7).then(function (frame) {
      var form = new FormData();
      form.append('image', frame.file, frame.file.name);
      return fetchJson('/api/v1/pad/inspection-jobs/' + encodeURIComponent(jobId) + '/instance-detect', {
        method: 'POST', body: form,
      });
    }).then(function (result) {
      if (!result.detected) {
        consecutiveDetections = 0;
        mediaStatus.textContent = s.instanceSearching || 'CV is looking for a stable instance in the live video…';
        return;
      }
      consecutiveDetections += 1;
      mediaStatus.textContent = (s.instanceProgress || 'Instance detected ({count}/2 stable frames)')
        .replace('{count}', String(consecutiveDetections));
      if (consecutiveDetections < 2) return;
      autoCaptureCommitted = true;
      mediaStatus.textContent = s.instanceCaptured || 'Stable instance detected. Capturing and judging automatically…';
      return captureAndJudgeAutomatically();
    }).catch(function (error) {
      consecutiveDetections = 0;
      setStatus((s.autoFailed || 'Automatic CV capture failed:') + ' ' + error.message, 'error');
    }).finally(function () {
      autoDetectionBusy = false;
      if (!autoCaptureCommitted) scheduleAutoDetection();
    });
  }

  function captureAndJudgeAutomatically() {
    var captureStarted = performance.now();
    return frameFile('mac-usb-camera-auto.jpg', 0.92).then(function (frame) {
      stageTimings.capture_ms = Math.max(frame.elapsedMs, Math.round(performance.now() - captureStarted));
      return attachImage(frame.file, 'mac_usb_camera');
    }).then(function () {
      return runVisionAnalysis();
    }).catch(function (error) {
      autoCaptureCommitted = false;
      consecutiveDetections = 0;
      setStatus((s.autoFailed || 'Automatic CV capture failed:') + ' ' + error.message, 'error');
      scheduleAutoDetection();
    });
  }

  function runVisionAnalysis() {
    runVisionButton.disabled = true;
    setStatus(s.visionAnalyzing || 'Running live vision inspection…');
    return fetchJson('/api/v1/pad/inspection-jobs/' + encodeURIComponent(jobId) + '/vision-analyze', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({client_timings: stageTimings}),
    }).then(function (data) {
      var byCode = {};
      (data.checkpoint_results || []).forEach(function (item) { byCode[item.point_code] = item; });
      Array.from(document.querySelectorAll('.checkpoint-card')).forEach(function (card) {
        var suggestion = byCode[card.dataset.pointCode];
        if (!suggestion) return;
        var select = card.querySelector('.checkpoint-result');
        select.value = suggestion.result;
        var prior = card.querySelector('.model-suggestion');
        if (prior) prior.remove();
        var note = document.createElement('p');
        note.className = 'model-suggestion';
        var resultLabels = {
          pass: s.pass || 'Pass',
          fail: s.fail || 'Fail',
          not_visible: s.notVisible || 'Not visible',
          low_confidence: s.lowConfidence || 'Low confidence',
        };
        note.textContent =
          (s.visionSuggestion || 'Live model suggestion') + ': ' +
          (resultLabels[suggestion.result] || suggestion.result) + ' · ' +
          Math.round((suggestion.confidence || 0) * 100) + '%' +
          (suggestion.notes ? ' · ' + suggestion.notes : '');
        card.appendChild(note);
      });
      var assistant = data.assistant || {};
      setStatus(
        (s.visionReady || 'Live vision suggestions ready; review every checkpoint before submitting.') +
        ' · ' + (assistant.model || 'vision') + ' · ' +
        (((assistant.elapsed_ms || 0) / 1000).toFixed(1)) + 's',
        'success'
      );
    }).catch(function (error) {
      setStatus((s.visionFailed || 'Vision inspection failed closed:') + ' ' + error.message, 'error');
    }).finally(function () {
      if (!currentJob || !currentJob.final_report) runVisionButton.disabled = false;
    });
  }

  function submitAndFinalize() {
    var cards = Array.from(document.querySelectorAll('.checkpoint-card'));
    var results = cards.map(function (card) {
      var select = card.querySelector('.checkpoint-result');
      return {detection_point_id: card.dataset.pointId, result: select.value, confidence: 1.0};
    });
    if (!results.length || results.some(function (item) { return !item.result; })) {
      setStatus(s.incomplete || 'Select a result for every checkpoint.', 'error');
      return;
    }
    submitButton.disabled = true;
    setStatus(s.finalizing || 'Saving results and finalizing…');
    fetchJson('/api/v1/pad/inspection-jobs/' + encodeURIComponent(jobId) + '/checkpoint-results', {
      method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({results: results}),
    })
      .then(function () {
        return fetchJson('/api/v1/pad/inspection-jobs/' + encodeURIComponent(jobId) + '/finalize', {method: 'POST'});
      })
      .then(function (report) {
        setStatus((s.finalized || 'Final verdict:') + ' ' + report.overall_result + '\n' + (report.summary_text || ''), 'success');
        return loadJob();
      })
      .catch(function (error) {
        submitButton.disabled = false;
        setStatus((s.error || 'Inspection error:') + ' ' + error.message, 'error');
      });
  }

  fixtureUpload.addEventListener('change', function () {
    if (fixtureUpload.files[0]) attachImage(fixtureUpload.files[0], 'fixture_upload').then(runVisionAnalysis);
  });
  startButton.addEventListener('click', startCamera);
  stopButton.addEventListener('click', stopCamera);
  deviceSelect.addEventListener('change', function () { if (cameraStream) startCamera(); });
  runVisionButton.addEventListener('click', runVisionAnalysis);
  submitButton.addEventListener('click', submitAndFinalize);
  window.addEventListener('beforeunload', stopCamera);
  loadJob();
})();
