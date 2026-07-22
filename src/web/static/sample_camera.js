/* Manual USB standard-sample capture for Samples & Standards. */
(function () {
  "use strict";

  var form = document.getElementById("sample-photo-form");
  var panel = document.getElementById("mode-camera");
  if (!form || !panel) return;

  var video = document.getElementById("sample-camera-preview");
  var canvas = document.getElementById("sample-camera-canvas");
  var device = document.getElementById("sample-camera-device");
  var start = document.getElementById("sample-camera-start");
  var capture = document.getElementById("sample-camera-capture");
  var stop = document.getElementById("sample-camera-stop");
  var status = document.getElementById("sample-camera-status");
  var confirmPanel = document.getElementById("sample-camera-confirm");
  var upload = document.getElementById("sample-camera-upload-confirm");
  var retake = document.getElementById("sample-camera-retake");
  var stream = null;
  var pendingBlob = null;

  function message(name) {
    return panel.dataset[name] || "";
  }

  function setStatus(text, kind) {
    status.textContent = text || "";
    status.className = "sample-camera-status" + (kind ? " is-" + kind : "");
  }

  function option(value, label, selected) {
    var node = document.createElement("option");
    node.value = value;
    node.textContent = label;
    node.selected = Boolean(selected);
    return node;
  }

  function resetPreview() {
    pendingBlob = null;
    canvas.hidden = true;
    video.hidden = false;
    confirmPanel.hidden = true;
    capture.disabled = !stream;
    upload.disabled = false;
    retake.disabled = false;
    if (stream) video.play();
  }

  function stopCamera() {
    if (stream) stream.getTracks().forEach(function (track) { track.stop(); });
    stream = null;
    video.srcObject = null;
    resetPreview();
    capture.disabled = true;
    stop.disabled = true;
    start.disabled = false;
  }

  function populateDevices() {
    if (!navigator.mediaDevices || !navigator.mediaDevices.enumerateDevices) return Promise.resolve();
    var current = device.value;
    device.innerHTML = "";
    device.appendChild(option("", message("default"), !current));
    return navigator.mediaDevices.enumerateDevices().then(function (devices) {
      devices.filter(function (item) { return item.kind === "videoinput"; })
        .forEach(function (item, index) {
          device.appendChild(option(item.deviceId, item.label || (message("default") + " " + (index + 1)), item.deviceId === current));
        });
    });
  }

  function requestCamera(constraints) {
    return new Promise(function (resolve, reject) {
      var finished = false;
      var timer = window.setTimeout(function () {
        finished = true;
        reject(new Error(message("timeout")));
      }, 12000);
      navigator.mediaDevices.getUserMedia(constraints).then(function (mediaStream) {
        if (finished) {
          mediaStream.getTracks().forEach(function (track) { track.stop(); });
          return;
        }
        finished = true;
        window.clearTimeout(timer);
        resolve(mediaStream);
      }).catch(function (error) {
        if (finished) return;
        finished = true;
        window.clearTimeout(timer);
        reject(error);
      });
    });
  }

  function startCamera() {
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
      setStatus(message("denied") + " getUserMedia unavailable", "error");
      return;
    }
    stopCamera();
    start.disabled = true;
    var deviceId = device.value;
    var constraints = deviceId ? {deviceId: {exact: deviceId}} : {width: {ideal: 1280}, height: {ideal: 720}};
    requestCamera({video: constraints, audio: false}).then(function (mediaStream) {
      stream = mediaStream;
      video.srcObject = mediaStream;
      capture.disabled = false;
      stop.disabled = false;
      var track = mediaStream.getVideoTracks()[0];
      setStatus(message("ready") + ": " + (track.label || message("default")), "success");
      return populateDevices();
    }).catch(function (error) {
      start.disabled = false;
      setStatus(message("denied") + " " + error.message, "error");
    });
  }

  function capturePhoto() {
    if (!stream || !video.videoWidth || !video.videoHeight) {
      setStatus(message("required"), "error");
      return;
    }
    canvas.width = video.videoWidth;
    canvas.height = video.videoHeight;
    canvas.getContext("2d").drawImage(video, 0, 0, canvas.width, canvas.height);
    canvas.toBlob(function (blob) {
      if (!blob) {
        setStatus(message("failed") + " encoding failed", "error");
        return;
      }
      pendingBlob = blob;
      video.pause();
      video.hidden = true;
      canvas.hidden = false;
      capture.disabled = true;
      confirmPanel.hidden = false;
      setStatus(message("captured"), "success");
    }, "image/jpeg", 0.92);
  }

  function uploadPhoto() {
    if (!pendingBlob) {
      setStatus(message("failed") + " no pending capture", "error");
      return;
    }
    upload.disabled = true;
    retake.disabled = true;
    setStatus(message("uploading"));
    var data = new FormData(form);
    data.delete("_photo_mode");
    data.set("photo_file", new File([pendingBlob], "mac-usb-standard-sample.jpg", {type: "image/jpeg"}));
    fetch(form.action, {method: "POST", body: data, credentials: "same-origin", redirect: "follow"})
      .then(function (response) {
        if (!response.ok) throw new Error("HTTP " + response.status);
        stopCamera();
        window.location.assign(response.url || form.action);
      }).catch(function (error) {
        upload.disabled = false;
        retake.disabled = false;
        setStatus(message("failed") + " " + error.message, "error");
      });
  }

  start.addEventListener("click", startCamera);
  capture.addEventListener("click", capturePhoto);
  stop.addEventListener("click", stopCamera);
  upload.addEventListener("click", uploadPhoto);
  retake.addEventListener("click", resetPreview);
  device.addEventListener("change", function () { if (stream) startCamera(); });
  window.addEventListener("pagehide", stopCamera);
})();
