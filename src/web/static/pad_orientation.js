(function () {
  'use strict';

  var overlay = document.getElementById('orientation-overlay');
  var actionBtns = [];

  function updateOrientation() {
    var isPortrait = window.innerHeight > window.innerWidth;
    if (!overlay) return;

    if (isPortrait) {
      overlay.style.display = 'flex';
      // Disable all QC action buttons
      actionBtns = document.querySelectorAll('.qc-action-btn');
      actionBtns.forEach(function (btn) {
        btn.disabled = true;
        btn.setAttribute('aria-disabled', 'true');
      });
    } else {
      overlay.style.display = 'none';
      // Re-enable all QC action buttons
      actionBtns = document.querySelectorAll('.qc-action-btn');
      actionBtns.forEach(function (btn) {
        btn.disabled = false;
        btn.removeAttribute('aria-disabled');
      });
    }
  }

  window.addEventListener('resize', updateOrientation);
  window.addEventListener('orientationchange', updateOrientation);
  document.addEventListener('DOMContentLoaded', updateOrientation);
  updateOrientation();
})();
