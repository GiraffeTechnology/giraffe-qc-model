(function () {
  'use strict';

  var config = window.GIRAFFE_PAD_REPORT || {};
  var jobId = config.jobId;
  var s = config.strings || {};
  var content = document.getElementById('report-content');
  var resultLabels = {
    pass: s.pass || 'Pass',
    fail: s.fail || 'Fail',
    not_visible: s.notVisible || 'Not visible',
    low_confidence: s.lowConfidence || 'Low confidence',
  };

  function element(tag, className, text) {
    var node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  }

  function fact(label, value) {
    var wrapper = element('div', 'report-fact');
    wrapper.appendChild(element('strong', '', label));
    wrapper.appendChild(element('span', '', String(value)));
    return wrapper;
  }

  function render(job) {
    content.innerHTML = '';
    if (!job.final_report) {
      content.appendChild(element('p', 'error-banner', s.notReady || 'This inspection has not been finalized yet.'));
      return;
    }

    var verdict = job.final_report.overall_result;
    var verdictNode = element('div', 'report-verdict verdict-' + verdict);
    verdictNode.appendChild(element('strong', '', (s.verdict || 'Final verdict') + ': '));
    verdictNode.appendChild(document.createTextNode(verdict.toUpperCase()));
    content.appendChild(verdictNode);

    var facts = element('div', 'report-facts');
    facts.appendChild(fact(s.jobStatus || 'Job status', job.status));
    facts.appendChild(fact(s.evidenceCount || 'Evidence files', job.media_count));
    content.appendChild(facts);
    if (job.final_report.summary_text) content.appendChild(element('p', '', job.final_report.summary_text));

    var table = element('table', 'report-checkpoints');
    table.appendChild(element('caption', '', s.checkpoints || 'Checkpoint results'));
    var body = document.createElement('tbody');
    job.checkpoints.forEach(function (point) {
      var row = document.createElement('tr');
      row.appendChild(element('th', '', point.point_code + ' · ' + point.label));
      var outcome = point.submitted_result || '-';
      row.appendChild(element('td', 'verdict-' + outcome, resultLabels[outcome] || outcome));
      body.appendChild(row);
    });
    table.appendChild(body);
    content.appendChild(table);
  }

  fetch('/api/v1/pad/inspection-jobs/' + encodeURIComponent(jobId), {cache: 'no-store'})
    .then(function (response) {
      return response.json().then(function (data) {
        if (!response.ok) throw new Error(data.error || data.detail || ('HTTP ' + response.status));
        return data;
      });
    })
    .then(render)
    .catch(function (error) {
      content.innerHTML = '';
      content.appendChild(element('p', 'error-banner', (s.error || 'Report error:') + ' ' + error.message));
    });
})();
