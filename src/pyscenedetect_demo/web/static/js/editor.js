(function () {
  'use strict';
  var byId = function (id) { return document.getElementById(id); };
  var form = byId('editor-upload-form');
  var activeId = '', state = null, assets = [], projects = [], pendingUploads = [];
  var promptText = '', promptInputId = '', responseInputId = '', videoKey = '';
  var loading = true, generating = false, polling = false, navigating = false, dirty = false, saveFailed = false;
  var saveQueue = Promise.resolve(), pendingSaves = 0, saveTimer = null, editVersion = 0, openVersion = 0;

  function show(id, visible) { byId(id).classList.toggle('editor-hidden', !visible); }
  function error(message) { byId('editor-error').textContent = message || ''; }
  function processing() { return generating || !!state && (state.status === 'analyzing' || state.status === 'rendering'); }
  function needsAnalysisDefaults() { return !!state && (!!state.language || !!state.allow_reorder || state.describe_visuals === false); }
  function nameKey(name) { return name.normalize('NFKC').trim().replace(/\s+/g, ' ').toLowerCase(); }
  function duplicateName() {
    var name = byId('project-name').value.trim();
    return !!name && projects.some(function (project) { return project.id !== activeId && nameKey(project.name || '') === nameKey(name); });
  }
  function suggestName() {
    var number = 1;
    while (projects.some(function (project) { return nameKey(project.name || '') === nameKey('Project_' + number); })) number += 1;
    return 'Project_' + number;
  }
  function supported(file) { return /\.mp4$/i.test(file.name) && (!file.type || file.type === 'video/mp4' || file.type === 'application/mp4'); }
  function snapshot() {
    var result = { asset_ids: assets.map(function (asset) { return asset.id; }) };
    if (!activeId) result.name = byId('project-name').value.trim();
    if (state && state.analysis_current && responseInputId === state.analysis.input_id) {
      result.ai_response = byId('editor-plan').value; result.ai_response_input_id = responseInputId;
    }
    ['topic', 'context'].forEach(function (key) { result[key] = form.elements[key].value; });
    result.language = ''; result.allow_reorder = false; result.describe_visuals = true;
    if (state) result.revision = state.workspace_revision || 0;
    return result;
  }
  function setAddress(id) {
    var address = new URL(window.location.href);
    if (id) address.searchParams.set('project', id); else address.searchParams.delete('project');
    window.history.replaceState(null, '', address);
    try { if (id) localStorage.setItem('scene-scribe-project', id); else localStorage.removeItem('scene-scribe-project'); } catch (_) {}
  }
  function updateActions() {
    var busy = loading || navigating || processing(), saving = pendingSaves > 0;
    var current = state && state.analysis_current && !needsAnalysisDefaults();
    var ready = current && !dirty && !saveFailed;
    byId('analyze-clips').disabled = busy || saving || dirty || saveFailed || !state || !assets.length || current && !state.analysis_upgrade_available;
    byId('copy-editor-prompt').disabled = busy || saving || !ready || !promptText || promptInputId !== state.analysis.input_id;
    byId('validate-editor-plan').disabled = busy || saving || !ready || !byId('editor-plan').value.trim() || responseInputId !== state.analysis.input_id;
    byId('new-editor-project').disabled = busy || saving;
    byId('delete-editor-project').disabled = busy || saving || !activeId;
    byId('project-list').disabled = busy || saving;
    byId('project-name').disabled = busy || saving;
    byId('project-name').readOnly = !!activeId;
    byId('project-name').title = activeId ? 'Saved project names cannot be changed.' : '';
    byId('save-editor-draft').disabled = busy || saving || duplicateName();
    byId('retry-project-save').disabled = busy || saving;
    show('save-editor-draft', !activeId && !saveFailed);
    form.querySelectorAll('input, textarea').forEach(function (input) { input.disabled = busy || (input.id === 'editor-files' && (saving || !activeId)); });
    byId('editor-upload-button').title = activeId ? '' : 'Save draft to enable clip uploads.';
    byId('editor-plan').disabled = busy || !state || !state.analysis_current;
    byId('project-save-status').textContent = saveFailed ? "Couldn't save" : saving || activeId && dirty ? 'Saving…' : activeId ? 'Saved' : '';
    show('retry-project-save', saveFailed);
    if (duplicateName()) byId('project-name-message').textContent = 'A project with this name already exists. Choose another name.';
    displayFiles();
  }
  function displayFiles() {
    var list = byId('editor-file-list'), locked = loading || navigating || processing() || pendingSaves > 0;
    list.replaceChildren();
    assets.forEach(function (asset, index) {
      var row = document.createElement('li');
      row.appendChild(document.createTextNode(asset.name));
      if (!asset.analyzed) {
        var badge = document.createElement('span'); badge.className = 'editor-file-state'; badge.textContent = 'New'; row.appendChild(badge);
      }
      [-1, 1, 0].forEach(function (direction) {
        var button = document.createElement('button'); button.type = 'button'; button.className = 'btn';
        button.textContent = direction < 0 ? 'Move up' : direction > 0 ? 'Move down' : 'Remove';
        button.disabled = locked || (direction && (index + direction < 0 || index + direction >= assets.length));
        button.addEventListener('click', function () {
          if (!direction) assets.splice(index, 1);
          else { var previous = assets[index]; assets[index] = assets[index + direction]; assets[index + direction] = previous; }
          markDirty(false); autosave();
        });
        row.appendChild(button);
      });
      list.appendChild(row);
    });
    pendingUploads.forEach(function (file) {
      var row = document.createElement('li'); row.textContent = file.name + (pendingSaves ? ' — Saving…' : ''); list.appendChild(row);
    });
  }
  async function request(url, options) {
    var response = await fetch(url, options);
    if (!response.ok) {
      var body; try { body = await response.json(); } catch (_) { body = { detail: response.statusText }; }
      throw new Error(typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail));
    }
    return response;
  }
  async function jsonRequest(url, options) { return (await request(url, options)).json(); }
  function jsonOptions(data) { return { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(data) }; }
  async function refreshProjects() {
    projects = await jsonRequest('/api/editor/projects');
    var select = byId('project-list'); select.replaceChildren(new Option('Select a previous project', ''));
    projects.forEach(function (project) { select.add(new Option(project.name + (project.status === 'completed' ? '' : ' · Draft'), project.id)); });
    select.value = activeId;
    byId('project-name').placeholder = suggestName();
  }
  async function loadPrompt() {
    if (!state || !state.analysis_current) { promptText = ''; promptInputId = ''; return; }
    var id = activeId, inputId = state.analysis.input_id, version = openVersion;
    if (inputId === promptInputId) return;
    var text = await (await request('/api/editor/projects/' + id + '/prompt')).text();
    if (id === activeId && version === openVersion && state.analysis_current && state.analysis.input_id === inputId) {
      promptText = text; promptInputId = inputId; byId('copy-editor-prompt').textContent = 'Copy prompt';
    }
  }
  function applyState(saved, hydrate) {
    activeId = saved.id; state = saved; assets = saved.assets || []; setAddress(activeId);
    byId('project-name').value = saved.name;
    if (hydrate) {
      ['topic', 'context'].forEach(function (key) { form.elements[key].value = saved[key] || ''; });
      byId('editor-plan').value = saved.ai_response_current ? saved.ai_response || '' : '';
      responseInputId = saved.analysis_current ? saved.analysis.input_id : '';
    }
    show('editor-handover', !!saved.has_analysis);
    var video = saved.video;
    show('editor-result', !!video || saved.plan_current);
    if (saved.plan_current) byId('edited-script').textContent = saved.resolved.script || '[No spoken words retained]';
    else byId('edited-script').textContent = video ? video.script || '[No spoken words retained]' : '';
    show('editor-playback', !!video);
    show('previous-video-label', !!video && video.previous);
    if (video) {
      var key = saved.id + ':' + video.file;
      if (key !== videoKey) { byId('edited-video').src = '/api/editor/projects/' + saved.id + '/video?preview=true&v=' + encodeURIComponent(video.file); videoKey = key; }
      byId('download-editor-video').href = '/api/editor/projects/' + saved.id + '/video?download=true';
    }
    if (saved.error) error(saved.error);
    byId('editor-status').textContent = processing() ? saved.message || 'Processing…' :
      saved.assets.length && (!saved.analysis_current || needsAnalysisDefaults()) ? 'Analyze clips to update the prompt.' : '';
    updateActions();
  }
  function markDirty(delayed) {
    editVersion += 1; dirty = true; saveFailed = false; error('');
    byId('project-name-message').textContent = '';
    if (saveTimer) clearTimeout(saveTimer);
    saveTimer = null;
    updateActions();
    if (delayed && activeId) saveTimer = setTimeout(function () { saveTimer = null; autosave(); }, 500);
  }
  function autosave() { if (activeId) enqueueSave().catch(function () {}); }
  function enqueueSave() {
    if (saveTimer) { clearTimeout(saveTimer); saveTimer = null; }
    pendingSaves += 1; updateActions();
    saveQueue = saveQueue.catch(function () {}).then(async function () {
      var data = snapshot(), version = editVersion, uploads = pendingUploads.slice(), saved;
      if (duplicateName()) throw new Error('A project with this name already exists. Choose another name.');
      if (!activeId) {
        var initial = new FormData(); initial.set('workspace', JSON.stringify(data));
        uploads.forEach(function (file) { initial.append('videos', file, file.name); });
        saved = await jsonRequest('/api/editor/workspace', { method: 'POST', body: initial });
      } else {
        saved = await jsonRequest('/api/editor/projects/' + activeId + '/workspace', jsonOptions(data));
        // Update the committed revision even if a later file copy fails.
        state = saved;
        if (uploads.length) {
          var additional = new FormData(); uploads.forEach(function (file) { additional.append('videos', file, file.name); });
          saved = await jsonRequest('/api/editor/projects/' + activeId + '/clips', { method: 'POST', body: additional });
        }
      }
      pendingUploads = pendingUploads.filter(function (file) { return uploads.indexOf(file) < 0; });
      if (version === editVersion) dirty = false;
      saveFailed = false;
      applyState(saved, !dirty);
      await loadPrompt();
      await refreshProjects();
      // Edits made during the first explicit save now belong to the saved project.
      if (dirty && !saveTimer) saveTimer = setTimeout(function () { saveTimer = null; autosave(); }, 500);
    }).catch(function (e) {
      saveFailed = true; dirty = true; error(e.message);
      if (/project.*name/i.test(e.message)) byId('project-name-message').textContent = e.message;
      throw e;
    }).finally(function () { pendingSaves -= 1; updateActions(); });
    return saveQueue;
  }
  async function flush() {
    if (saveTimer || dirty && !pendingSaves) await enqueueSave();
    else await saveQueue;
    if (saveFailed) throw new Error('Save this project before continuing.');
  }
  function freshWorkspace() {
    openVersion += 1; activeId = ''; state = null; assets = []; pendingUploads = [];
    promptText = ''; promptInputId = ''; responseInputId = ''; videoKey = '';
    dirty = false; saveFailed = false; generating = false;
    form.reset(); byId('project-name').value = ''; byId('editor-plan').value = '';
    byId('project-name-message').textContent = ''; byId('plan-validation-message').textContent = '';
    byId('editor-status').textContent = ''; error(''); setAddress(''); byId('project-list').value = '';
    byId('edited-video').pause(); byId('edited-video').removeAttribute('src'); byId('edited-video').load();
    show('editor-handover', false); show('editor-result', false); show('editor-playback', false); updateActions();
  }
  async function openProject(id) {
    var version = ++openVersion; loading = true; error(''); updateActions();
    try {
      var saved = await jsonRequest('/api/editor/projects/' + id);
      if (version !== openVersion) return;
      dirty = false; saveFailed = false; pendingUploads = [];
      byId('plan-validation-message').textContent = '';
      applyState(saved, true); await loadPrompt(); await refreshProjects();
    } finally { loading = false; updateActions(); }
  }
  function leaveDecision() {
    var dialog = byId('leave-project-dialog');
    return new Promise(function (resolve) {
      dialog.addEventListener('close', function () { resolve(dialog.returnValue); }, { once: true });
      dialog.returnValue = 'cancel'; dialog.showModal();
    });
  }
  async function canLeave() {
    if (activeId) { await flush(); return true; }
    if (!dirty) return true;
    var decision = await leaveDecision();
    if (decision === 'save') await enqueueSave();
    return decision === 'save' || decision === 'discard';
  }
  ['save', 'discard', 'cancel'].forEach(function (choice) {
    byId('leave-project-' + choice).addEventListener('click', function () { byId('leave-project-dialog').close(choice); });
  });
  byId('save-editor-draft').addEventListener('click', function () {
    if (!this.disabled) enqueueSave().catch(function () {});
  });
  byId('delete-project-cancel').addEventListener('click', function () { byId('delete-project-dialog').close('cancel'); });
  byId('delete-project-confirm').addEventListener('click', function () { byId('delete-project-dialog').close('delete'); });
  byId('delete-editor-project').addEventListener('click', async function () {
    if (this.disabled) return;
    var id = activeId, dialog = byId('delete-project-dialog'), decision;
    if (saveTimer) { clearTimeout(saveTimer); saveTimer = null; }
    navigating = true; updateActions();
    byId('delete-project-description').textContent = 'Delete “' + state.name + '”?';
    try {
      decision = await new Promise(function (resolve) {
        dialog.addEventListener('close', function () { resolve(dialog.returnValue); }, { once: true });
        dialog.returnValue = 'cancel'; dialog.showModal();
      });
      if (decision !== 'delete') return;
      // Release the media file before removing this project's saved files.
      byId('edited-video').pause(); byId('edited-video').removeAttribute('src'); byId('edited-video').load(); videoKey = '';
      await request('/api/editor/projects/' + id, { method: 'DELETE' });
      freshWorkspace();
      await refreshProjects();
      byId('editor-status').textContent = 'Project deleted.';
      byId('project-name').focus();
    } catch (e) {
      if (state) applyState(state, false);
      error(e.message);
    } finally {
      navigating = false; updateActions();
      if (decision !== 'delete' && activeId && dirty && !saveFailed) autosave();
    }
  });
  byId('new-editor-project').addEventListener('click', async function () {
    if (this.disabled) return;
    navigating = true; updateActions();
    try { if (await canLeave()) freshWorkspace(); } catch (e) { error(e.message); }
    finally { navigating = false; updateActions(); }
  });
  byId('project-list').addEventListener('change', async function () {
    var selected = this.value;
    this.value = activeId;
    navigating = true; updateActions();
    try { if (await canLeave()) { if (selected) await openProject(selected); else freshWorkspace(); } }
    catch (e) { this.value = activeId; error(e.message); }
    finally { navigating = false; updateActions(); }
  });
  byId('project-name').addEventListener('input', function () { if (!this.readOnly) markDirty(false); });
  form.addEventListener('input', function (event) { if (event.target.id !== 'editor-files') markDirty(true); });
  byId('editor-plan').addEventListener('input', function () {
    responseInputId = state && state.analysis_current ? state.analysis.input_id : '';
    byId('plan-validation-message').textContent = ''; markDirty(true);
  });
  byId('editor-files').addEventListener('change', function () {
    var selected = Array.from(this.files); this.value = '';
    if (this.disabled || !activeId) return;
    if (!selected.every(supported)) { error('Please choose MP4 video clips only.'); return; }
    if (!selected.length) return;
    pendingUploads = pendingUploads.concat(selected); markDirty(false); autosave();
  });
  byId('retry-project-save').addEventListener('click', function () { saveFailed = false; enqueueSave().catch(function () {}); });
  form.addEventListener('submit', async function (event) {
    event.preventDefault(); if (byId('analyze-clips').disabled) return;
    try {
      if (needsAnalysisDefaults()) await enqueueSave();
      await flush(); error(''); loading = true; updateActions();
      await request('/api/editor/projects/' + activeId + '/analyze', { method: 'POST' });
      applyState(await jsonRequest('/api/editor/projects/' + activeId), true);
    } catch (e) { error(e.message); }
    finally { loading = false; updateActions(); }
  });
  byId('copy-editor-prompt').addEventListener('click', async function () {
    if (this.disabled) return;
    try { await navigator.clipboard.writeText(promptText); }
    catch (_) {
      var field = document.createElement('textarea'); field.value = promptText; field.readOnly = true;
      field.style.cssText = 'position:fixed;top:0;left:0;opacity:0;'; document.body.appendChild(field);
      try { field.select(); if (!document.execCommand('copy')) throw new Error('Copy failed'); }
      catch (_) { error('Could not copy the prompt. Allow clipboard access and try again.'); return; }
      finally { field.remove(); this.focus(); }
    }
    this.textContent = 'Prompt copied';
  });
  byId('validate-editor-plan').addEventListener('click', async function () {
    if (this.disabled) return;
    generating = true; error(''); byId('plan-validation-message').textContent = ''; updateActions();
    try {
      await flush();
      await request('/api/editor/projects/' + activeId + '/plan', { method: 'POST', headers: { 'Content-Type': 'text/plain' }, body: byId('editor-plan').value });
      await request('/api/editor/projects/' + activeId + '/render', { method: 'POST' });
    } catch (e) { byId('plan-validation-message').textContent = e.message; byId('plan-validation-message').className = 'editor-error'; }
    finally {
      generating = false;
      try { applyState(await jsonRequest('/api/editor/projects/' + activeId), true); } catch (e) { error(e.message); }
      updateActions();
    }
  });
  window.addEventListener('beforeunload', function (event) {
    if (dirty || pendingSaves || pendingUploads.length) { event.preventDefault(); event.returnValue = ''; }
  });
  setInterval(async function () {
    if (!activeId || !processing() || polling || pendingSaves || dirty || loading || generating) return;
    polling = true; var id = activeId, version = openVersion;
    try {
      var saved = await jsonRequest('/api/editor/projects/' + id);
      if (id !== activeId || version !== openVersion) return;
      applyState(saved, true); await loadPrompt(); await refreshProjects();
    } catch (e) { error(e.message); }
    finally { polling = false; updateActions(); }
  }, 1500);
  updateActions();
  refreshProjects().then(async function () {
    var id = new URLSearchParams(window.location.search).get('project');
    if (!id) { try { id = localStorage.getItem('scene-scribe-project'); } catch (_) {} }
    if (id && projects.some(function (project) { return project.id === id; })) await openProject(id);
    else freshWorkspace();
  }).catch(function (e) { error(e.message); }).finally(function () { loading = false; updateActions(); });
})();
