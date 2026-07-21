(function () {
  'use strict';

  var input = document.getElementById('sku-search-input');
  var searchButton = document.getElementById('sku-search-btn');
  var results = document.getElementById('sku-search-results');
  var status = document.getElementById('qc-control-status');
  var i18n = window.GIRAFFE_PAD_CONTROL_I18N || {};

  function message(text, error) {
    status.textContent = text || '';
    status.className = 'qc-control-status' + (error ? ' is-error' : '');
  }

  function startJob(skuId, button) {
    button.disabled = true;
    message(i18n.starting || 'Creating job…');
    fetch('/api/v1/pad/create_inspection_job', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({sku_id: skuId, job_ref: 'web-simulator-' + Date.now()}),
    })
      .then(function (response) { return response.json().then(function (data) { return {response: response, data: data}; }); })
      .then(function (result) {
        if (!result.response.ok) throw new Error(result.data.error || 'job creation failed');
        window.location.assign('/pad/inspections/' + encodeURIComponent(result.data.job_id));
      })
      .catch(function (error) {
        button.disabled = false;
        message((i18n.error || 'QC control error:') + ' ' + error.message, true);
      });
  }

  function render(items) {
    results.innerHTML = '';
    if (!items.length) {
      var empty = document.createElement('p');
      empty.className = 'placeholder-text';
      empty.textContent = i18n.noSkus || 'No active SKU with a confirmed standard was found.';
      results.appendChild(empty);
      return;
    }
    items.forEach(function (sku) {
      var card = document.createElement('article');
      card.className = 'sku-result-card';
      var text = document.createElement('div');
      var title = document.createElement('strong');
      title.textContent = sku.item_number;
      var name = document.createElement('span');
      name.textContent = sku.name;
      text.appendChild(title);
      text.appendChild(name);
      var button = document.createElement('button');
      button.className = 'btn-primary qc-action-btn';
      button.textContent = i18n.start || 'Start QC job';
      button.addEventListener('click', function () { startJob(sku.id, button); });
      card.appendChild(text);
      card.appendChild(button);
      results.appendChild(card);
    });
  }

  function search() {
    searchButton.disabled = true;
    message(i18n.searching || 'Searching…');
    fetch('/api/v1/pad/skus?q=' + encodeURIComponent(input.value.trim()), {cache: 'no-store'})
      .then(function (response) { return response.json().then(function (data) { return {response: response, data: data}; }); })
      .then(function (result) {
        if (!result.response.ok) throw new Error(result.data.error || 'search failed');
        render(result.data.items || []);
        message('');
      })
      .catch(function (error) { message((i18n.error || 'QC control error:') + ' ' + error.message, true); })
      .finally(function () { searchButton.disabled = false; });
  }

  if (searchButton) searchButton.addEventListener('click', search);
  if (input) input.addEventListener('keydown', function (event) {
    if (event.key === 'Enter') { event.preventDefault(); search(); }
  });
  if (searchButton) search();
})();
