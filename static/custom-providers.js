(function(){
  var _debounceTimer = null;

  function esc(str) {
    if (typeof str !== 'string') return '';
    return str.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
  }

  function t(key, ...args) {
    if (typeof window.t === 'function') {
      return window.t(key, ...args);
    }
    return key;
  }

  function showDialog(provider) {
    var isEdit = !!provider;
    var existing = document.getElementById('cpDialogOverlay');
    if (existing) existing.remove();

    var overlay = document.createElement('div');
    overlay.id = 'cpDialogOverlay';
    overlay.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,0.6);display:flex;align-items:center;justify-content:center;z-index:1000';

    var card = document.createElement('div');
    card.style.cssText = 'background:var(--code-bg,#1a1a2e);border:1px solid var(--border);border-radius:16px;padding:24px;width:480px;max-width:90vw;max-height:90vh;overflow-y:auto';

    card.innerHTML =
      '<div style="font-size:16px;font-weight:600;margin-bottom:16px">' + esc(isEdit ? t('custom_provider_edit') : t('custom_provider_add')) + '</div>' +
      '<div style="margin-bottom:12px"><label style="display:block;font-size:12px;color:var(--muted);margin-bottom:4px">' + t('custom_provider_name') + '</label>' +
      '<input id="cpName" type="text" placeholder="my-ollama" value="' + esc(provider ? provider.name : '') + '" style="width:100%;padding:8px 12px;background:var(--code-bg);border:1px solid var(--border);border-radius:8px;color:var(--text);font-size:13px;box-sizing:border-box"></div>' +
      '<div style="margin-bottom:12px"><label style="display:block;font-size:12px;color:var(--muted);margin-bottom:4px">' + t('custom_provider_base_url') + '</label>' +
      '<input id="cpBaseUrl" type="url" placeholder="http://localhost:11434/v1" value="' + esc(provider ? provider.base_url : '') + '" style="width:100%;padding:8px 12px;background:var(--code-bg);border:1px solid var(--border);border-radius:8px;color:var(--text);font-size:13px;box-sizing:border-box"></div>' +
      '<div style="margin-bottom:12px"><label style="display:block;font-size:12px;color:var(--muted);margin-bottom:4px">' + t('custom_provider_api_key') + '</label>' +
      '<input id="cpApiKey" type="password" placeholder="sk-..." value="' + esc(provider ? provider.api_key : '') + '" style="width:100%;padding:8px 12px;background:var(--code-bg);border:1px solid var(--border);border-radius:8px;color:var(--text);font-size:13px;box-sizing:border-box"></div>' +
      '<div style="margin-bottom:16px"><label style="display:block;font-size:12px;color:var(--muted);margin-bottom:4px">' + t('custom_provider_model') + '</label>' +
      '<div style="position:relative"><input id="cpModel" type="text" placeholder="llama3" value="' + esc(provider ? provider.model : '') + '" style="width:100%;padding:8px 12px;background:var(--code-bg);border:1px solid var(--border);border-radius:8px;color:var(--text);font-size:13px;box-sizing:border-box">' +
      '<div id="cpModelDropdown" style="display:none;position:absolute;top:100%;left:0;right:0;background:var(--code-bg,#1a1a2e);border:1px solid var(--border);border-radius:8px;max-height:200px;overflow-y:auto;z-index:10"></div></div>' +
      '<div id="cpProbeStatus" style="font-size:11px;color:var(--muted);margin-top:4px"></div></div>' +
      '<div style="display:flex;gap:8px;justify-content:flex-end">' +
      '<button id="cpCancelBtn" style="padding:8px 20px;background:var(--code-bg);color:var(--text);border:1px solid var(--border);border-radius:8px;cursor:pointer;font-size:13px">' + t('custom_provider_cancel') + '</button>' +
      '<button id="cpSaveBtn" style="padding:8px 20px;background:var(--accent);color:var(--text);border:none;border-radius:8px;cursor:pointer;font-size:13px;font-weight:600">' + esc(isEdit ? t('custom_provider_save') : t('custom_provider_add_btn')) + '</button></div>';

    overlay.appendChild(card);
    document.body.appendChild(overlay);

    var nameInput = document.getElementById('cpName');
    var urlInput = document.getElementById('cpBaseUrl');
    var keyInput = document.getElementById('cpApiKey');
    var modelInput = document.getElementById('cpModel');
    var modelDropdown = document.getElementById('cpModelDropdown');
    var probeStatus = document.getElementById('cpProbeStatus');
    var saveBtn = document.getElementById('cpSaveBtn');
    var cancelBtn = document.getElementById('cpCancelBtn');

    function close() { overlay.remove(); }

    function doProbe() {
      var url = urlInput.value.trim();
      var key = keyInput.value.trim();
      if (!url) return;
      probeStatus.textContent = t('custom_provider_fetching_models');
      probeStatus.style.color = 'var(--muted)';
      fetch('/api/custom-providers/probe', {
        method: 'POST',
        headers: {'Content-Type':'application/json'},
        body: JSON.stringify({base_url: url, api_key: key}),
        credentials: 'include'
      }).then(function(r){ return r.json(); }).then(function(data){
        if (data.ok && data.models && data.models.length) {
          modelDropdown.innerHTML = '';
          data.models.forEach(function(m){
            var opt = document.createElement('div');
            opt.textContent = m.label || m.id;
            opt.style.cssText = 'padding:6px 12px;cursor:pointer;font-size:13px';
            opt.onmouseover = function(){ opt.style.background = 'var(--accent)'; };
            opt.onmouseout = function(){ opt.style.background = ''; };
            opt.onclick = function(){ modelInput.value = m.id || m.label; modelDropdown.style.display = 'none'; };
            modelDropdown.appendChild(opt);
          });
          modelDropdown.style.display = '';
          probeStatus.textContent = t('custom_provider_models_found', data.models.length);
          probeStatus.style.color = 'var(--success)';
        } else {
          probeStatus.textContent = t('custom_provider_no_models');
          probeStatus.style.color = 'var(--warning)';
        }
      }).catch(function(){
        probeStatus.textContent = t('custom_provider_fetch_failed');
        probeStatus.style.color = 'var(--error)';
      });
    }

    var probeTimeout = null;
    function onUrlOrKeyChange() {
      if (probeTimeout) clearTimeout(probeTimeout);
      probeTimeout = setTimeout(doProbe, 500);
    }
    urlInput.addEventListener('input', onUrlOrKeyChange);
    keyInput.addEventListener('input', onUrlOrKeyChange);

    modelInput.addEventListener('focus', function(){
      if (modelDropdown.children.length) modelDropdown.style.display = '';
    });
    modelInput.addEventListener('blur', function(){
      setTimeout(function(){ modelDropdown.style.display = 'none'; }, 200);
    });

    cancelBtn.addEventListener('click', close);
    overlay.addEventListener('click', function(e){ if (e.target === overlay) close(); });

    saveBtn.addEventListener('click', function(){
      var name = nameInput.value.trim();
      var url = urlInput.value.trim();
      var key = keyInput.value.trim();
      var model = modelInput.value.trim();
      if (!name || !url || (!isEdit && !key)) {
        probeStatus.textContent = isEdit ? 'Name and Base URL are required' : 'Name, Base URL and API Key are required';
        probeStatus.style.color = 'var(--error)';
        return;
      }
      var method = isEdit ? 'PUT' : 'POST';
      fetch('/api/custom-providers', {
        method: method,
        headers: {'Content-Type':'application/json'},
        body: JSON.stringify({name: name, base_url: url, api_key: key, model: model}),
        credentials: 'include'
      }).then(function(r){ return r.json(); }).then(function(data){
        if (data.ok) { close(); renderCustomProvidersSection(); }
        else { probeStatus.textContent = data.error || t('custom_provider_failed_to_save'); probeStatus.style.color = 'var(--error)'; }
      }).catch(function(){
        probeStatus.textContent = 'Network error';
        probeStatus.style.color = 'var(--error)';
      });
    });
  }

  window.renderCustomProvidersSection = function() {
    // Work with the existing providers panel structure
    var container = document.getElementById('providersList');
    if (!container) return;
    
    var customHTML = '<div id="customProvidersSectionWrapper"></div>';
    container.insertAdjacentHTML('afterbegin', customHTML);
    
    var sectionElement = container.querySelector('#customProvidersSectionWrapper');
    if (!sectionElement) return;

    fetch('/api/custom-providers', {credentials: 'include'}).then(function(r){ return r.json(); }).then(function(data){
      if (!data.ok) { 
        sectionElement.innerHTML = '<div style="color:var(--error);font-size:12px">' + t('custom_provider_failed_to_load') + '</div>'; 
        return; 
      }
      var providers = data.providers || [];
      var html = '<div id="customProvidersSection" style="margin-top:16px">';
      html += '<div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:4px">';
      html += '<div style="font-size:14px;font-weight:600">' + t('custom_providers_title') + '</div>';
      html += '<button id="cpAddBtn" style="padding:4px 14px;background:var(--accent);color:#fff;border:none;border-radius:8px;cursor:pointer;font-size:12px;font-weight:600;white-space:nowrap" type="button">+ ' + t('custom_provider_add') + '</button>';
      html += '</div>';
      html += '<div style="font-size:11px;color:var(--muted);margin-bottom:12px;margin-top:2px">' + t('custom_providers_desc') + '</div>';
      if (!providers.length) {
        html += '<div style="color:var(--muted);font-size:12px;padding:8px 0">' + t('custom_provider_no_providers') + '</div>';
      } else {
        html += '<div style="display:flex;flex-direction:column;gap:4px">';
        providers.forEach(function(p){
          html += '<div style="display:flex;align-items:center;padding:8px 10px;background:var(--code-bg,#1a1a2e);border:1px solid var(--border);border-radius:8px">';
          html += '<div style="flex:1;min-width:0"><div style="font-size:13px;font-weight:500;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">' + esc(p.name) + '</div>';
          html += '<div style="font-size:11px;color:var(--muted)">' + esc(p.base_url) + (p.model ? ' · ' + esc(p.model) : '') + '</div></div>';
          html += '<button class="cp-edit-btn" data-name="' + esc(p.name) + '" style="background:none;border:none;cursor:pointer;padding:4px 8px;color:var(--muted)" title="' + t('custom_provider_edit') + '">' +
            '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/></svg></button>';
          html += '<button class="cp-delete-btn" data-name="' + esc(p.name) + '" style="background:none;border:none;cursor:pointer;padding:4px 8px;color:var(--muted)" title="Delete">' +
            '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg></button>';
          html += '</div>';
        });
        html += '</div>';
      }
      html += '<div style="border-top:1px solid var(--border);margin-top:16px"></div>';
      html += '</div>';
      sectionElement.innerHTML = html;

      sectionElement.querySelectorAll('.cp-edit-btn').forEach(function(btn){
        btn.addEventListener('click', function(){
          var name = btn.getAttribute('data-name');
          var p = providers.find(function(x){ return x.name === name; });
          if (p) showDialog(p);
        });
      });
      sectionElement.querySelectorAll('.cp-delete-btn').forEach(function(btn){
        btn.addEventListener('click', function(){
          var name = btn.getAttribute('data-name');
          if (!confirm(t('custom_provider_delete_confirm').replace('{name}', name))) return;
          fetch('/api/custom-providers?name=' + encodeURIComponent(name), {
            method: 'DELETE',
            credentials: 'include'
          }).then(function(r){ return r.json(); }).then(function(d){
            if (d.ok) {
              var wrapper = document.getElementById('customProvidersSectionWrapper');
              if(wrapper) wrapper.remove();
              loadProvidersPanel();
            }
          });
        });
      });
      document.getElementById('cpAddBtn') && document.getElementById('cpAddBtn').addEventListener('click', function(){ showDialog(null); });
    }).catch(function(){
      var sectionElement = document.getElementById('customProvidersSectionWrapper');
      if(sectionElement) sectionElement.innerHTML = '<div style="color:var(--error);font-size:12px">' + t('custom_provider_failed_to_load') + '</div>';
    });
  };
})();
