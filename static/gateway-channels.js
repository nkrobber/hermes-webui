(function(){
  var PLATFORMS = [
    {id:'feishu', label:'飞书', emoji:'飞', hasQR:true,
     fields:[{key:'app_id', label:'App ID', type:'text'},{key:'app_secret', label:'App Secret', type:'password'},{key:'verification_token', label:'Verification Token', type:'password'}]},
    {id:'dingtalk', label:'钉钉', emoji:'钉', hasQR:false,
     fields:[{key:'client_id', label:'Client ID', type:'text'},{key:'client_secret', label:'Client Secret', type:'password'}]},
    {id:'weixin', label:'微信', emoji:'微', hasQR:true,
     fields:[{key:'token', label:'Token', type:'password'}]},
    {id:'wecom', label:'企业微信', emoji:'企', hasQR:true,
     fields:[{key:'bot_id', label:'Bot ID', type:'text'},{key:'secret', label:'Secret', type:'password'}]},
    {id:'qqbot', label:'QQ', emoji:'QQ', hasQR:true,
     fields:[{key:'app_id', label:'App ID', type:'text'},{key:'client_secret', label:'Client Secret', type:'password'}]}
  ];

  function esc(s){ if(typeof s!=='string')return ''; return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;'); }
  function t(key){ return (typeof window.t==='function') ? window.t(key) : key; }

  function renderHeader(container, status){
    var html = '<div style="padding:16px 12px;border-bottom:1px solid var(--border)">';
    html += '<div style="font-size:14px;font-weight:600;margin-bottom:8px">' + t('settings_tab_gateway') + '</div>';
    if(!status || !status.ok){
      html += '<div style="display:flex;align-items:center;gap:8px"><span style="width:8px;height:8px;border-radius:50%;background:var(--warning,#f59e0b);display:inline-block"></span><span style="font-size:13px;color:var(--warning)">' + t('gateway_status_unknown') + '</span></div>';
    } else if(status.running){
      html += '<div style="display:flex;align-items:center;gap:8px;margin-bottom:8px"><span style="width:8px;height:8px;border-radius:50%;background:var(--success,#22c55e);display:inline-block"></span><span style="font-size:13px;font-weight:500;color:var(--success)">' + t('gateway_status_running') + '</span></div>';
      if(status.uptime_seconds){
        var h = Math.floor(status.uptime_seconds/3600);
        var m = Math.floor((status.uptime_seconds%3600)/60);
        html += '<div style="font-size:11px;color:var(--muted);margin-bottom:8px">' + h + 'h ' + m + 'm' + (status.pid ? ' · PID: '+status.pid : '') + '</div>';
      }
      html += '<div style="display:flex;gap:6px;margin-bottom:8px"><button class="gw-btn gw-btn-stop" style="padding:5px 14px;background:var(--error,#ef4444);color:var(--text,#fff);border:none;border-radius:6px;cursor:pointer;font-size:12px">' + t('gateway_btn_stop') + '</button>';
      html += '<button class="gw-btn gw-btn-restart" style="padding:5px 14px;background:var(--code-bg);color:var(--text);border:1px solid var(--border);border-radius:6px;cursor:pointer;font-size:12px">' + t('gateway_btn_restart') + '</button></div>';
      html += '<div style="font-size:10px;color:var(--muted);font-style:italic">' + t('gateway_restart_note') + '</div>';
    } else if(status.configured){
      html += '<div style="display:flex;align-items:center;gap:8px;margin-bottom:8px"><span style="width:8px;height:8px;border-radius:50%;background:var(--error,#ef4444);display:inline-block"></span><span style="font-size:13px;font-weight:500;color:var(--error)">' + t('gateway_status_stopped') + '</span></div>';
      html += '<button class="gw-btn gw-btn-start" style="padding:5px 14px;background:var(--accent);color:var(--text,#fff);border:none;border-radius:6px;cursor:pointer;font-size:12px">' + t('gateway_btn_start') + '</button>';
    } else {
      html += '<div style="display:flex;align-items:center;gap:8px;margin-bottom:8px"><span style="width:8px;height:8px;border-radius:50%;background:var(--warning);display:inline-block"></span><span style="font-size:13px;color:var(--warning)">' + t('gateway_status_not_configured') + '</span></div>';
    }
    html += '</div>';
    container.innerHTML = html;

    container.querySelector('.gw-btn-start') && container.querySelector('.gw-btn-start').addEventListener('click',function(){
      fetch('/api/gateway/start',{method:'POST',credentials:'include'}).then(function(){ refreshGatewayPanel(); });
    });
    container.querySelector('.gw-btn-stop') && container.querySelector('.gw-btn-stop').addEventListener('click',function(){
      fetch('/api/gateway/stop',{method:'POST',credentials:'include'}).then(function(){ refreshGatewayPanel(); });
    });
    container.querySelector('.gw-btn-restart') && container.querySelector('.gw-btn-restart').addEventListener('click',function(){
      fetch('/api/gateway/restart',{method:'POST',credentials:'include'}).then(function(){ refreshGatewayPanel(); });
    });
  }

  function renderCards(container, channels){
    var html = '<div style="padding:12px"><div style="font-size:14px;font-weight:600;margin-bottom:8px">' + t('gateway_platforms') + '</div>';
    html += '<div style="display:flex;flex-direction:column;gap:10px">';
    PLATFORMS.forEach(function(p){
      var ch = channels && channels[p.id];
      var configured = ch && ch.configured;
      var enabled = ch && ch.enabled;
      html += '<div class="gw-card" data-platform="'+p.id+'" style="background:var(--card-bg);border:1px solid var(--border);border-radius:12px;padding:14px;'+(configured && !enabled ? 'opacity:0.5' : '')+'">';
      html += '<div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:8px">';
      html += '<div style="display:flex;align-items:center;gap:8px"><span style="font-size:16px">'+p.emoji+'</span><span style="font-size:14px;font-weight:500">'+esc(p.label)+'</span></div>';
      if(configured){
        html += '<label style="display:flex;align-items:center;gap:4px;font-size:12px;cursor:pointer"><input type="checkbox" class="gw-toggle" data-platform="'+p.id+'" '+(enabled?'checked':'')+'> <span style="color:var(--muted)">'+(enabled?'ON':'OFF')+'</span></label>';
      }
      html += '</div>';
      if(configured){
        html += '<div style="display:flex;align-items:center;gap:6px;margin-bottom:8px"><span style="width:6px;height:6px;border-radius:50%;background:var(--success);display:inline-block"></span><span style="font-size:12px;color:var(--success)">' + t('gateway_configured') + '</span></div>';
        html += '<div style="display:flex;gap:6px;flex-wrap:wrap">';
        html += '<button class="gw-test" data-platform="'+p.id+'" style="padding:4px 12px;background:var(--code-bg);color:var(--text);border:1px solid var(--border);border-radius:6px;cursor:pointer;font-size:11px">' + t('gateway_test_connection') + '</button>';
        if(p.hasQR) html += '<button class="gw-reconfig" data-platform="'+p.id+'" style="padding:4px 12px;background:var(--code-bg);color:var(--text);border:1px solid var(--border);border-radius:6px;cursor:pointer;font-size:11px">' + t('gateway_reconfigure') + '</button>';
        html += '<button class="gw-clear" data-platform="'+p.id+'" style="padding:4px 12px;background:transparent;color:var(--error);border:1px solid var(--error);border-radius:6px;cursor:pointer;font-size:11px">' + t('gateway_clear_config') + '</button>';
        html += '</div>';
      } else {
        html += '<div style="display:flex;align-items:center;gap:6px;margin-bottom:8px"><span style="width:6px;height:6px;border-radius:50%;background:var(--muted);display:inline-block"></span><span style="font-size:12px;color:var(--muted)">' + t('gateway_not_configured') + '</span></div>';
        html += '<div style="display:flex;gap:6px">';
        if(p.hasQR) html += '<button class="gw-qr" data-platform="'+p.id+'" style="padding:4px 12px;background:var(--accent);color:var(--text);border:none;border-radius:6px;cursor:pointer;font-size:11px">' + t('gateway_scan_qr') + '</button>';
        html += '<button class="gw-manual" data-platform="'+p.id+'" style="padding:4px 12px;background:var(--code-bg);color:var(--text);border:1px solid var(--border);border-radius:6px;cursor:pointer;font-size:11px">' + t('gateway_manual_config') + '</button>';
        html += '</div>';
      }
      html += '<div class="gw-test-result" style="margin-top:6px;font-size:11px;display:none"></div>';
      html += '</div>';
    });
    html += '</div></div>';
    container.innerHTML = html;

    container.querySelectorAll('.gw-test').forEach(function(btn){
      btn.addEventListener('click', function(){
        var plat = btn.getAttribute('data-platform');
        var resultDiv = btn.closest('.gw-card').querySelector('.gw-test-result');
        resultDiv.style.display = 'block';
        resultDiv.innerHTML = '<span style="color:var(--muted)">Testing...</span>';
        fetch('/api/gateway/channels/'+plat+'/test',{method:'POST',credentials:'include'}).then(function(r){return r.json();}).then(function(d){
          if(d.ok){ resultDiv.innerHTML = '<span style="color:var(--success)">&#10003; '+esc(d.message||'OK')+'</span>'; }
          else { resultDiv.innerHTML = '<span style="color:var(--error)">&#10007; '+esc(d.message||'Failed')+'</span>'; }
        }).catch(function(){ resultDiv.innerHTML = '<span style="color:var(--error)">&#10007; Network error</span>'; });
      });
    });

    container.querySelectorAll('.gw-clear').forEach(function(btn){
      btn.addEventListener('click', function(){
        var plat = btn.getAttribute('data-platform');
        if(!confirm(t('gateway_clear_confirm').replace('{platform}', plat))) return;
        fetch('/api/gateway/channels/'+plat+'/clear',{method:'POST',credentials:'include'}).then(function(r){return r.json();}).then(function(d){
          if(d.ok) refreshGatewayPanel();
        });
      });
    });

    container.querySelectorAll('.gw-toggle').forEach(function(cb){
      cb.addEventListener('change', function(){
        var plat = cb.getAttribute('data-platform');
        fetch('/api/gateway/channels/'+plat,{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({enabled: cb.checked}),credentials:'include'}).then(function(r){return r.json();}).then(function(d){
          if(d.ok){ refreshGatewayPanel(); } else { cb.checked = !cb.checked; }
        }).catch(function(){ cb.checked = !cb.checked; });
      });
    });

    container.querySelectorAll('.gw-manual').forEach(function(btn){
      btn.addEventListener('click', function(){ openManualForm(btn.getAttribute('data-platform')); });
    });
    container.querySelectorAll('.gw-reconfig').forEach(function(btn){
      btn.addEventListener('click', function(){ openManualForm(btn.getAttribute('data-platform')); });
    });
    container.querySelectorAll('.gw-qr').forEach(function(btn){
      btn.addEventListener('click', function(){ openQRModal(btn.getAttribute('data-platform')); });
    });
  }

  function openManualForm(platformId){
    var p = PLATFORMS.find(function(x){ return x.id === platformId; });
    if(!p) return;
    var existing = document.getElementById('gwFormOverlay');
    if(existing) existing.remove();

    var overlay = document.createElement('div');
    overlay.id = 'gwFormOverlay';
    overlay.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,0.6);display:flex;align-items:center;justify-content:center;z-index:1000';
    
    var card = document.createElement('div');
    card.style.cssText = 'background:var(--code-bg);border:1px solid var(--border);border-radius:16px;padding:24px;width:440px;max-width:90vw;max-height:90vh;overflow-y:auto';

    var html = '<div style="font-size:16px;font-weight:600;margin-bottom:4px">'+esc(p.emoji)+' '+esc(p.label)+'</div>';
    html += '<div style="font-size:12px;color:var(--muted);margin-bottom:16px">' + t('gateway_enter_credentials').replace('{platform}', p.label) + '</div>';
    p.fields.forEach(function(f){
      html += '<div style="margin-bottom:10px"><label style="display:block;font-size:12px;color:var(--muted);margin-bottom:4px">'+esc(f.label)+'</label>';
      html += '<input class="gw-field" data-key="'+f.key+'" type="'+f.type+'" style="width:100%;padding:8px 12px;background:var(--code-bg);border:1px solid var(--border);border-radius:8px;color:var(--text);font-size:13px;box-sizing:border-box"></div>';
    });
    html += '<div style="margin-bottom:16px"><label style="display:flex;align-items:center;gap:6px;font-size:12px;cursor:pointer"><input id="gwFormEnabled" type="checkbox" checked> ' + t('gateway_enable_channel') + '</label></div>';
    html += '<div id="gwFormStatus" style="font-size:11px;color:var(--muted);margin-bottom:8px;display:none"></div>';
    html += '<div style="display:flex;gap:8px;justify-content:flex-end">';
    html += '<button id="gwFormCancel" style="padding:8px 20px;background:var(--code-bg);color:var(--text);border:1px solid var(--border);border-radius:8px;cursor:pointer;font-size:13px">' + t('gateway_cancel') + '</button>';
    html += '<button id="gwFormSave" style="padding:8px 20px;background:var(--accent);color:var(--text);border:none;border-radius:8px;cursor:pointer;font-size:13px;font-weight:600">' + t('gateway_save') + '</button></div>';
    card.innerHTML = html;
    overlay.appendChild(card);
    document.body.appendChild(overlay);

    function close(){ overlay.remove(); }
    document.getElementById('gwFormCancel').addEventListener('click', close);
    overlay.addEventListener('click', function(e){ if(e.target===overlay) close(); });
    document.getElementById('gwFormSave').addEventListener('click', function(){
      var body = {enabled: document.getElementById('gwFormEnabled').checked};
      overlay.querySelectorAll('.gw-field').forEach(function(inp){
        var val = inp.value.trim();
        if(val) body[inp.getAttribute('data-key')] = val;
      });
      var statusDiv = document.getElementById('gwFormStatus');
      statusDiv.style.display = 'block';
      statusDiv.innerHTML = '<span style="color:var(--muted)">Saving...</span>';
      fetch('/api/gateway/channels/'+platformId,{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify(body),credentials:'include'}).then(function(r){return r.json();}).then(function(d){
        if(d.ok){ close(); refreshGatewayPanel(); }
        else { statusDiv.innerHTML = '<span style="color:var(--error)">'+esc(d.error||'Failed to save')+'</span>'; }
      }).catch(function(){ statusDiv.innerHTML = '<span style="color:var(--error)">Network error</span>'; });
    });
  }

  function openQRModal(platformId){
    var p = PLATFORMS.find(function(x){ return x.id === platformId; });
    if(!p) return;
    var existing = document.getElementById('gwQROverlay');
    if(existing) existing.remove();

    var overlay = document.createElement('div');
    overlay.id = 'gwQROverlay';
    overlay.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,0.6);display:flex;align-items:center;justify-content:center;z-index:1000';
    
    var card = document.createElement('div');
    card.style.cssText = 'background:var(--code-bg);border:1px solid var(--border);border-radius:16px;padding:24px;width:400px;max-width:90vw;text-align:center';
    card.innerHTML =
      '<div style="font-size:16px;font-weight:600;margin-bottom:12px">' + t('gateway_scan_qr_title') + '</div>'+
      '<div style="font-size:12px;color:var(--muted);margin-bottom:16px">' + esc(p.label) + '</div>'+
      '<div id="gwQRCode" style="margin:0 auto 16px;width:200px;height:200px;background:#fff;border-radius:8px;display:flex;align-items:center;justify-content:center"><span style="color:var(--muted);font-size:12px">' + t('gateway_loading_qr') + '</span></div>'+
      '<div id="gwQRStatus" style="font-size:12px;color:var(--muted);margin-bottom:12px"></div>'+
      '<button id="gwQRClose" style="padding:6px 16px;background:var(--code-bg);color:var(--text);border:1px solid var(--border);border-radius:6px;cursor:pointer;font-size:12px">' + t('gateway_close') + '</button>';
    overlay.appendChild(card);
    document.body.appendChild(overlay);

    function close(){ if(window._gwQrPollTimer){ clearInterval(window._gwQrPollTimer); } overlay.remove(); }
    document.getElementById('gwQRClose').addEventListener('click', close);
    overlay.addEventListener('click', function(e){ if(e.target===overlay) close(); });

    var qrDataUrl = '';
    var deviceId = '';

    fetch('/api/gateway/channels/'+platformId+'/qr/begin',{method:'POST',credentials:'include'}).then(function(r){return r.json();}).then(function(d){
      if(d.ok && d.qr_data_url){
        qrDataUrl = d.qr_data_url;
        deviceId = d.device_code || d.task_id || '';

        // Render QR code locally using embedded qrcode-generator
        var container = document.getElementById('gwQRCode');
        try {
          var qr = qrcode(0, 'M'); // 0 = auto type number
          qr.addData(qrDataUrl);
          qr.make();
          container.innerHTML = qr.createImgTag(4, 2); // 4px modules, 2px margin
        } catch(e) {
          container.innerHTML = '<span style="color:var(--error);font-size:12px">QR generation error</span>';
        }

        document.getElementById('gwQRStatus').innerHTML = '<span style="color:var(--warning)">' + t('gateway_waiting_scan') + '</span>';

        if(window._gwQrPollTimer) clearInterval(window._gwQrPollTimer);
        window._gwQrPollTimer = setInterval(function(){
          var pollBody = {};
          if(platformId === 'feishu' && deviceId) pollBody.device_code = deviceId;
          else if(deviceId) pollBody.task_id = deviceId;
          fetch('/api/gateway/channels/'+platformId+'/qr/poll', {
            method:'POST',
            headers:{'Content-Type':'application/json'},
            body: JSON.stringify(pollBody),
            credentials:'include'
          }).then(function(r){return r.json();}).then(function(d){
            if(d.status === 'confirmed'){
              document.getElementById('gwQRStatus').innerHTML = '<span style="color:var(--success);font-weight:600">' + t('gateway_scan_confirmed') + '</span>';
              if(window._gwQrPollTimer) clearInterval(window._gwQrPollTimer);
              setTimeout(function(){ close(); refreshGatewayPanel(); }, 1500);
            } else if(d.status === 'expired'){
              document.getElementById('gwQRStatus').innerHTML = '<span style="color:var(--error)">' + t('gateway_qr_expired') + '</span>';
              if(window._gwQrPollTimer) clearInterval(window._gwQrPollTimer);
            } else if(d.status === 'pending'){
              document.getElementById('gwQRStatus').innerHTML = '<span style="color:var(--warning)">' + t('gateway_waiting_scan') + '</span>';
            }
          }).catch(function(){});
        }, 3000);
      } else {
        document.getElementById('gwQRCode').innerHTML = '<span style="color:var(--error);font-size:12px">QR unavailable</span>';
        document.getElementById('gwQRStatus').innerHTML = '';
      }
    }).catch(function(){
      document.getElementById('gwQRCode').innerHTML = '<span style="color:var(--error);font-size:12px">Failed to get QR</span>';
      document.getElementById('gwQRStatus').innerHTML = '';
    });
  }

  function refreshGatewayPanel(){
    var header = document.getElementById('gwHeader');
    var cards = document.getElementById('gwCards');
    if(!header || !cards) return;
    fetch('/api/gateway/status',{credentials:'include'}).then(function(r){return r.json();}).then(function(status){
      renderHeader(header, status);
    }).catch(function(){
      renderHeader(header, null);
    });
    fetch('/api/gateway/channels',{credentials:'include'}).then(function(r){return r.json();}).then(function(data){
      renderCards(cards, data.ok ? data.channels : null);
    }).catch(function(){
      cards.innerHTML = '<div style="padding:12px;color:var(--error);font-size:12px">' + t('gateway_load_failed') + '</div>';
    });
  }

  window.loadGatewayPanel = function(){
    var settingsContent = document.getElementById('gatewaySettingsContent');
    if(settingsContent){
      if(!document.getElementById('gwHeader')){
        settingsContent.innerHTML = '<div id="gwHeader"></div><div id="gwCards"></div>';
      }
      refreshGatewayPanel();
      return;
    }
    var panel = document.getElementById('panelGateway');
    if(!panel){
      return;
    }
    if(!document.getElementById('gwHeader')){
      panel.innerHTML = '<div id="gwHeader"></div><div id="gwCards"></div>';
    }
    refreshGatewayPanel();
  };
})();
