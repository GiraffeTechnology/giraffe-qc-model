/* ROI canvas editor — drag to draw normalized rectangle on primary photo */
(function () {
  "use strict";

  var canvas = document.getElementById("roi-canvas");
  var image = document.getElementById("roi-image");
  var output = document.getElementById("roi-json-display");

  if (!canvas || !image || !output) return;

  var ctx = canvas.getContext("2d");
  var dragging = false;
  var startX = 0, startY = 0, endX = 0, endY = 0;

  function syncCanvasSize() {
    var rect = image.getBoundingClientRect();
    canvas.width = image.naturalWidth || rect.width;
    canvas.height = image.naturalHeight || rect.height;
  }

  function getPos(e) {
    var rect = canvas.getBoundingClientRect();
    return {
      x: (e.clientX - rect.left) * (canvas.width / rect.width),
      y: (e.clientY - rect.top) * (canvas.height / rect.height),
    };
  }

  function draw() {
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    var x = Math.min(startX, endX);
    var y = Math.min(startY, endY);
    var w = Math.abs(endX - startX);
    var h = Math.abs(endY - startY);
    ctx.strokeStyle = "#2563eb";
    ctx.lineWidth = 2;
    ctx.strokeRect(x, y, w, h);
    ctx.fillStyle = "rgba(37,99,235,0.10)";
    ctx.fillRect(x, y, w, h);
  }

  function writeJson() {
    var x = Math.min(startX, endX);
    var y = Math.min(startY, endY);
    var w = Math.abs(endX - startX);
    var h = Math.abs(endY - startY);
    var W = canvas.width;
    var H = canvas.height;
    if (W === 0 || H === 0 || w === 0 || h === 0) return;
    output.value = JSON.stringify({
      x: parseFloat((x / W).toFixed(4)),
      y: parseFloat((y / H).toFixed(4)),
      w: parseFloat((w / W).toFixed(4)),
      h: parseFloat((h / H).toFixed(4)),
    }, null, 2);
  }

  image.addEventListener("load", syncCanvasSize);
  if (image.complete && image.naturalWidth) syncCanvasSize();

  canvas.addEventListener("mousedown", function (e) {
    dragging = true;
    var pos = getPos(e);
    startX = endX = pos.x;
    startY = endY = pos.y;
  });

  canvas.addEventListener("mousemove", function (e) {
    if (!dragging) return;
    var pos = getPos(e);
    endX = pos.x;
    endY = pos.y;
    draw();
  });

  canvas.addEventListener("mouseup", function (e) {
    if (!dragging) return;
    dragging = false;
    var pos = getPos(e);
    endX = pos.x;
    endY = pos.y;
    draw();
    writeJson();
  });

  canvas.addEventListener("mouseleave", function () {
    if (dragging) {
      dragging = false;
      writeJson();
    }
  });
})();
