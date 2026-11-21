// Run with: node --test tests/editor-ui.test.cjs
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const web = path.join(__dirname, '../src/pyscenedetect_demo/web');
const template = fs.readFileSync(path.join(web, 'templates/editor.html'), 'utf8');
const script = fs.readFileSync(path.join(web, 'static/js/editor.js'), 'utf8');
async function settle() { for (let i = 0; i < 12; i++) await new Promise(resolve => setImmediate(resolve)); }
class Element {
  constructor(tag = '', attributes = '') {
    this.tag = tag; this.children = []; this.listeners = {}; this.value = ''; this.textContent = '';
    this.disabled = /\bdisabled\b/.test(attributes); this.hidden = /editor-hidden/.test(attributes);
    this.classList = { toggle: (_, hidden) => { this.hidden = hidden; } };
  }
  addEventListener(event, listener) { this.listeners[event] = listener; }
  async emit(event, details = {}) { await this.listeners[event]?.call(this, { preventDefault() {}, target: this, ...details }); await settle(); }
  appendChild(child) { this.children.push(child); }
  replaceChildren(...children) { this.children = children; }
  add(child) { this.children.push(child); }
  querySelectorAll(tag) { return this.children.filter(child => child.tag === tag); }
  pause() {} load() {} select() {} focus() {}
  showModal() { this.open = true; }
  close(value) { this.open = false; this.returnValue = value; this.listeners.close?.call(this); }
  removeAttribute(name) { delete this[name]; }
}
function signature(state) { return JSON.stringify([state.topic, state.context, state.language, state.allow_reorder, state.describe_visuals, state.assets.map(a => a.id)]); }
function view(state) {
  const current = !!state.analysis && state.analysisSignature === signature(state);
  const copy = structuredClone(state);
  copy.has_analysis = !!state.analysis; copy.analysis_current = current;
  copy.has_plan = !!state.resolved; copy.plan_current = current && state.planInputId === state.analysis.input_id;
  copy.ai_response_current = current && state.ai_response_input_id === state.analysis.input_id;
  if (copy.video) copy.video.previous = !copy.plan_current || copy.video.signature !== signature(state) || copy.video.plan_revision !== state.plan_revision;
  return copy;
}
async function setup({ database = [], selected = '', failRender = false } = {}) {
  const db = structuredClone(database), elements = {}, timers = new Map(), requests = [], local = new Map();
  let tick, timerId = 0, failure = false, pause;
  const windowEvents = {};
  for (const match of template.matchAll(/<(\w+)([^>]*\bid="([^"]+)"[^>]*)>/g)) elements[match[3]] = new Element(match[1], match[2]);
  const get = id => elements[id];
  Object.entries(elements).forEach(([id, element]) => { element.id = id; });
  const form = get('editor-upload-form');
  form.elements = {};
  for (const match of template.matchAll(/<(input|textarea)\b([^>]*\bname="([^"]+)"[^>]*)>/g)) form.elements[match[3]] = new Element(match[1], match[2]);
  form.reset = () => { Object.values(form.elements).forEach(el => { el.value = ''; el.checked = false; }); get('editor-files').value = ''; };
  form.reset();
  form.querySelectorAll = () => [get('editor-files'), ...Object.values(form.elements)];
  function state(id) { const result = db.find(s => s.id === id); assert.ok(result, 'Project exists'); return result; }
  function changes(saved, data) {
    ['topic', 'context', 'language', 'allow_reorder', 'describe_visuals', 'ai_response', 'ai_response_input_id'].forEach(key => { if (key in data) saved[key] = data[key]; });
    if (data.name?.trim()) assert.equal(data.name.trim(), saved.name, 'Saved names cannot change');
    if (data.asset_ids) saved.assets = data.asset_ids.map(id => saved.assets.find(a => a.id === id));
    saved.workspace_revision += 1;
    if (saved.analysis && saved.analysisSignature !== signature(saved)) saved.status = 'draft';
  }
  function add(saved, files) { files.forEach(file => saved.assets.push({ id: 'clip_' + (saved.assets.length + 1), name: file.name, analyzed: false })); saved.workspace_revision += 1; saved.status = 'draft'; }
  const context = {
    document: { getElementById: get, createElement: tag => new Element(tag), createTextNode: text => ({ text }) },
    window: { location: new URL('http://localhost/editor' + (selected ? '?project=' + selected : '')), history: { replaceState(_, __, url) { context.window.location.href = String(url); } }, addEventListener(name, callback) { windowEvents[name] = callback; } },
    localStorage: { getItem: key => local.get(key), setItem: (key, value) => local.set(key, value), removeItem: key => local.delete(key) },
    URL, URLSearchParams, Option: class extends Element {},
    FormData: class { constructor() { this.values = new Map(); } set(key, value) { this.values.set(key, value); } get(key) { return this.values.get(key); } append(key, value) { this.values.set(key, [...(this.values.get(key) || []), value]); } },
    setInterval(callback) { tick = callback; }, setTimeout(callback) { timers.set(++timerId, callback); return timerId; }, clearTimeout(id) { timers.delete(id); },
    navigator: { clipboard: { async writeText(text) { context.copied = text; } } },
    async fetch(url, options = {}) {
      requests.push({ url, method: options.method || 'GET' });
      let body, ok = true;
      const mutation = options.method === 'PATCH' || options.method === 'DELETE' || url === '/api/editor/workspace' || url.endsWith('/clips');
      if (mutation && pause) { const pending = pause; pause = null; await pending; }
      if (mutation && failure) { failure = false; return { ok: false, async json() { return { detail: 'Disk unavailable' }; } }; }
      if (url === '/api/editor/workspace') {
        const data = JSON.parse(options.body.get('workspace'));
        let number = 1; while (db.some(s => s.name === 'Project_' + number)) number++;
        const saved = { id: 'project' + (db.length + 1), name: data.name || 'Project_' + number, status: 'draft', created_at: '2026-01-01', assets: [], topic: '', context: '', language: '', allow_reorder: false, describe_visuals: true, workspace_revision: 0 };
        changes(saved, data); add(saved, options.body.get('videos') || []); db.push(saved); body = view(saved);
      } else if (url === '/api/editor/projects') body = db.map(s => ({ id: s.id, name: s.name, status: s.status }));
      else {
        const match = url.match(/^\/api\/editor\/projects\/([^/]+)(.*)$/); assert.ok(match, url);
        const saved = state(match[1]), suffix = match[2];
        if (options.method === 'DELETE') { db.splice(db.indexOf(saved), 1); body = null; }
        else if (suffix === '/workspace') { changes(saved, JSON.parse(options.body)); body = view(saved); }
        else if (suffix === '/clips') { add(saved, options.body.get('videos') || []); body = view(saved); }
        else if (suffix === '/prompt') body = 'Prompt for ' + saved.analysis.input_id;
        else if (suffix === '/analyze') { saved.status = 'analyzing'; body = {}; }
        else if (suffix === '/plan') {
          let plan; try { plan = JSON.parse(options.body); } catch (_) {}
          ok = plan?.input_id === saved.analysis.input_id;
          body = ok ? { script: 'Accepted script' } : { detail: 'Invalid or outdated AI response' };
          if (ok) { saved.resolved = body; saved.planInputId = plan.input_id; saved.plan_revision = plan.input_id; saved.ai_response = options.body; saved.ai_response_input_id = plan.input_id; saved.status = 'planned'; }
        } else if (suffix === '/render') { ok = !failRender; saved.status = ok ? 'rendering' : 'failed'; body = ok ? {} : { detail: 'Renderer unavailable' }; }
        else body = view(saved);
      }
      return { ok, async json() { return structuredClone(body); }, async text() { return body; } };
    },
  };
  vm.runInNewContext(script, context); await settle();
  return {
    get, db, requests, context, form, windowEvents,
    failNextSave() { failure = true; },
    pauseNextSave() { let release; pause = new Promise(resolve => { release = resolve; }); return release; },
    async timers() { for (const [id, callback] of [...timers]) { timers.delete(id); callback(); } await settle(); },
    async type(key, value) { form.elements[key].value = value; await form.emit('input', { target: form.elements[key] }); },
    async name(value) { get('project-name').value = value; await get('project-name').emit('input'); },
    async save() { await get('save-editor-draft').emit('click'); },
    async leave(choice, selected) {
      let navigation;
      if (selected === undefined) navigation = get('new-editor-project').emit('click');
      else { get('project-list').value = selected; navigation = get('project-list').emit('change'); }
      await settle();
      assert.equal(get('leave-project-dialog').open, true);
      await get('leave-project-' + choice).emit('click');
      await navigation;
    },
    async clips(names) { get('editor-files').files = names.map(name => ({ name, type: name.endsWith('.mp4') ? 'video/mp4' : 'image/png', size: 100 })); await get('editor-files').emit('change'); },
    async paste(value) { get('editor-plan').value = value; await get('editor-plan').emit('input'); },
    async finishAnalysis(id = db[0].id) { const saved = state(id); saved.analysis = { input_id: 'analysis_' + (saved.analysisVersion = (saved.analysisVersion || 0) + 1) }; saved.analysisSignature = signature(saved); saved.assets.forEach(a => { a.analyzed = true; }); saved.status = 'analyzed'; await tick(); await settle(); },
    async finishRender(id = db[0].id) { const saved = state(id); saved.video = { file: 'renders/' + saved.analysis.input_id + '.mp4', signature: signature(saved), plan_revision: saved.plan_revision, script: 'Accepted script' }; saved.status = 'completed'; await tick(); await settle(); },
    async poll() { await tick(); await settle(); },
  };
}
async function analyzed() { const ui = await setup(); await ui.save(); await ui.clips(['one.mp4']); await ui.get('editor-upload-form').emit('submit'); await ui.finishAnalysis(); return ui; }

test('saved projects with older segmentation can analyze again without changing content', async () => {
  const original = await analyzed();
  assert.equal(original.get('analyze-clips').disabled, true);
  original.db[0].analysis_upgrade_available = true;
  const ui = await setup({ database: original.db, selected: original.db[0].id });
  assert.equal(ui.get('analyze-clips').disabled, false);
  await ui.get('editor-upload-form').emit('submit');
  assert.equal(ui.db[0].status, 'analyzing');
});

test('delete confirms the selected name; Cancel and Escape preserve the project', async () => {
  const ui = await analyzed();
  for (const choice of ['cancel', '']) {
    const deletion = ui.get('delete-editor-project').emit('click'); await settle();
    assert.equal(ui.get('delete-project-dialog').open, true);
    assert.match(ui.get('delete-project-description').textContent, /Project_1/);
    assert.equal(ui.get('project-list').disabled, true);
    if (choice) await ui.get('delete-project-cancel').emit('click');
    else ui.get('delete-project-dialog').close('');
    await deletion;
    assert.equal(ui.db.length, 1);
    assert.equal(ui.get('delete-editor-project').disabled, false);
  }
  assert.equal(ui.requests.some(r => r.method === 'DELETE'), false);
});

test('confirmed deletion clears playback and selection and preserves other projects', async () => {
  const ui = await analyzed(); await ui.paste(JSON.stringify({ input_id: 'analysis_1' })); await ui.timers();
  await ui.get('validate-editor-plan').emit('click'); await ui.finishRender();
  const original = ui.db[0].id;
  const other = structuredClone(ui.db[0]); other.id = 'other'; other.name = 'Other project'; ui.db.push(other);
  await ui.type('topic', 'An unsaved edit');
  const deletion = ui.get('delete-editor-project').emit('click'); await settle();
  await ui.get('delete-project-confirm').emit('click'); await deletion; await ui.timers();
  assert.equal(ui.db.length, 1); assert.equal(ui.db[0].id, 'other');
  assert.equal(ui.requests.filter(r => r.method === 'DELETE').length, 1);
  assert.equal(ui.requests.find(r => r.method === 'DELETE').url, '/api/editor/projects/' + original);
  assert.equal(ui.get('project-name').value, ''); assert.equal(ui.get('project-list').value, '');
  assert.equal(ui.get('editor-playback').hidden, true); assert.equal(ui.get('edited-video').src, undefined);
  assert.equal(new URL(ui.context.window.location.href).searchParams.has('project'), false);
  assert.equal(ui.context.localStorage.getItem('scene-scribe-project'), undefined);
  assert.equal(ui.get('delete-editor-project').disabled, true);
  assert.equal(ui.get('editor-files').disabled, true);
  await ui.clips(['blocked.mp4']);
  assert.equal(ui.get('editor-file-list').children.length, 0);
  assert.equal(ui.get('editor-status').textContent, 'Project deleted.');
  assert.equal(ui.get('project-list').children.length, 2);
  await ui.save();
  assert.equal(ui.get('editor-files').disabled, false);
});

test('failed deletion keeps the selected project and permits retry', async () => {
  const ui = await analyzed(); ui.failNextSave();
  const deletion = ui.get('delete-editor-project').emit('click'); await settle();
  await ui.get('delete-project-confirm').emit('click'); await deletion;
  assert.equal(ui.db.length, 1); assert.equal(ui.get('project-name').value, 'Project_1');
  assert.match(ui.get('editor-error').textContent, /Disk unavailable/);
  assert.equal(ui.get('delete-editor-project').disabled, false);
});

test('delete is disabled for unsaved projects, saving, analysis and rendering', async () => {
  const ui = await setup(); assert.equal(ui.get('delete-editor-project').disabled, true);
  await ui.save(); await ui.clips(['one.mp4']);
  const release = ui.pauseNextSave(); await ui.type('context', 'Saving'); await ui.timers();
  assert.equal(ui.get('delete-editor-project').disabled, true); release(); await settle();
  await ui.form.emit('submit'); assert.equal(ui.get('delete-editor-project').disabled, true);
  await ui.finishAnalysis(); assert.equal(ui.get('delete-editor-project').disabled, false);
  await ui.paste(JSON.stringify({ input_id: 'analysis_1' })); await ui.timers();
  await ui.get('validate-editor-plan').emit('click'); assert.equal(ui.get('delete-editor-project').disabled, true);
});

test('saving and analyzing works without option controls and uses automatic analysis defaults', async () => {
  const ui = await setup();
  for (const key of ['language', 'allow_reorder', 'describe_visuals']) assert.equal(ui.form.elements[key], undefined);
  await ui.save(); await ui.clips(['one.mp4']);
  assert.equal(ui.db[0].language, '');
  assert.equal(ui.db[0].allow_reorder, false);
  assert.equal(ui.db[0].describe_visuals, true);
  await ui.form.emit('submit'); await ui.finishAnalysis();
  assert.equal(ui.get('copy-editor-prompt').disabled, false);
});

test('older projects adopt automatic defaults before reanalysis and keep previous video', async () => {
  const original = await analyzed();
  const saved = original.db[0];
  saved.language = 'ur'; saved.allow_reorder = true; saved.describe_visuals = false;
  saved.analysisSignature = signature(saved);
  saved.video = { file: 'previous.mp4', signature: signature(saved), script: 'Previous result' };
  const ui = await setup({ database: original.db, selected: saved.id });
  assert.equal(ui.db[0].language, 'ur', 'Opening alone preserves existing saved settings');
  assert.equal(ui.get('copy-editor-prompt').disabled, true);
  assert.equal(ui.get('analyze-clips').disabled, false);
  await ui.form.emit('submit');
  assert.equal(ui.db[0].language, ''); assert.equal(ui.db[0].allow_reorder, false); assert.equal(ui.db[0].describe_visuals, true);
  assert.equal(ui.db[0].status, 'analyzing');
  assert.ok(ui.requests.findIndex(r => r.method === 'PATCH') < ui.requests.findIndex(r => r.url.endsWith('/analyze')));
  assert.equal(ui.db[0].video.file, 'previous.mp4');
  await ui.finishAnalysis();
  assert.equal(ui.get('copy-editor-prompt').disabled, false);
});

test('new content waits for Save draft; saved names lock and later changes autosave', async () => {
  const ui = await setup();
  await ui.get('new-editor-project').emit('click');
  await ui.name('My video'); await ui.timers();
  assert.equal(ui.db.length, 0);
  await ui.type('topic', 'Audio'); await ui.timers();
  assert.equal(ui.db.length, 0); assert.equal(ui.get('project-save-status').textContent, '');
  assert.equal(ui.get('project-name').readOnly, false);
  await ui.save();
  assert.equal(ui.db.length, 1); assert.equal(ui.db[0].name, 'My video');
  assert.equal(ui.get('project-name').readOnly, true); assert.equal(ui.get('save-editor-draft').hidden, true);
  assert.equal(ui.get('project-name').value, 'My video'); assert.equal(ui.get('project-save-status').textContent, 'Saved');
  await ui.type('context', 'Room noise'); await ui.timers();
  assert.equal(ui.db.length, 1); assert.equal(ui.db[0].context, 'Room noise');
});

test('clips persist before analysis and reopen without another upload', async () => {
  const ui = await setup();
  assert.equal(ui.get('editor-files').disabled, true);
  assert.match(ui.get('editor-upload-button').title, /Save draft/);
  await ui.clips(['blocked.mp4']);
  assert.equal(ui.get('editor-file-list').children.length, 0);
  assert.equal(ui.db.length, 0); assert.equal(ui.get('analyze-clips').disabled, true);
  await ui.save();
  assert.equal(ui.get('editor-files').disabled, false);
  assert.equal(ui.get('analyze-clips').disabled, true);
  await ui.clips(['one.mp4']);
  assert.equal(ui.db[0].assets.length, 1); assert.equal(ui.get('analyze-clips').disabled, false);
  assert.equal(ui.get('copy-editor-prompt').disabled, true);
  const reopened = await setup({ database: ui.db, selected: ui.db[0].id });
  assert.equal(reopened.get('editor-file-list').children.length, 1);
  assert.equal(reopened.get('analyze-clips').disabled, false);
  assert.equal(reopened.get('project-name').value, 'Project_1');
  assert.equal(reopened.get('project-name').readOnly, true);
});

test('adding clips updates the same project, refreshes prompt readiness, and requires a fresh AI response', async () => {
  const ui = await analyzed();
  assert.equal(ui.get('analyze-clips').disabled, true); assert.equal(ui.get('copy-editor-prompt').disabled, false);
  await ui.get('copy-editor-prompt').emit('click'); assert.equal(ui.context.copied, 'Prompt for analysis_1');
  await ui.paste('invalid'); await ui.timers();
  await ui.get('validate-editor-plan').emit('click');
  assert.match(ui.get('plan-validation-message').textContent, /Invalid/);
  assert.equal(ui.requests.some(r => r.url.endsWith('/render')), false);
  await ui.paste(JSON.stringify({ input_id: 'analysis_1' })); await ui.timers();
  await ui.get('validate-editor-plan').emit('click'); await ui.finishRender();
  assert.equal(ui.get('copy-editor-prompt').disabled, false);
  await ui.clips(['two.mp4']);
  assert.equal(ui.db.length, 1); assert.equal(ui.get('editor-file-list').children.length, 2);
  assert.equal(ui.get('copy-editor-prompt').disabled, true); assert.equal(ui.get('validate-editor-plan').disabled, true);
  assert.equal(ui.get('editor-playback').hidden, false); assert.equal(ui.get('previous-video-label').hidden, false);
  await ui.get('editor-upload-form').emit('submit'); await ui.finishAnalysis();
  assert.equal(ui.get('copy-editor-prompt').disabled, false); assert.equal(ui.get('editor-plan').value, '');
  assert.equal(ui.get('validate-editor-plan').disabled, true);
});

test('removing newly added clips restores the earlier prompt and saved AI response', async () => {
  const ui = await analyzed();
  await ui.paste(JSON.stringify({ input_id: 'analysis_1' })); await ui.timers();
  await ui.clips(['two.mp4']);
  const second = ui.get('editor-file-list').children[1];
  await second.querySelectorAll('button')[2].emit('click');
  assert.equal(ui.db[0].assets.length, 1);
  assert.equal(ui.get('copy-editor-prompt').disabled, false);
  assert.equal(ui.get('validate-editor-plan').disabled, false);
});

test('refresh restores analyzed clips, saved response and finished video', async () => {
  const ui = await analyzed(); await ui.paste(JSON.stringify({ input_id: 'analysis_1' })); await ui.timers();
  await ui.get('validate-editor-plan').emit('click'); await ui.finishRender();
  const reopened = await setup({ database: ui.db, selected: ui.db[0].id });
  assert.equal(reopened.get('copy-editor-prompt').disabled, false);
  assert.equal(reopened.get('validate-editor-plan').disabled, false);
  assert.equal(reopened.get('editor-playback').hidden, false);
  assert.equal(reopened.get('previous-video-label').hidden, true);
  const preview = new URL(reopened.get('edited-video').src, 'http://localhost');
  assert.equal(preview.searchParams.get('preview'), 'true');
  assert.equal(preview.searchParams.get('v'), ui.db[0].video.file);
  const download = new URL(reopened.get('download-editor-video').href, 'http://localhost');
  assert.equal(download.searchParams.get('download'), 'true');
  assert.equal(download.searchParams.has('preview'), false);
});

test('failed saves keep selected clips for retry and warn before leaving', async () => {
  const ui = await setup(); await ui.save(); ui.failNextSave(); await ui.clips(['one.mp4']);
  assert.equal(ui.get('project-save-status').textContent, "Couldn't save");
  assert.equal(ui.get('analyze-clips').disabled, true); assert.equal(ui.db.length, 1);
  let warned = false; ui.windowEvents.beforeunload({ preventDefault() { warned = true; } }); assert.equal(warned, true);
  await ui.get('retry-project-save').emit('click');
  assert.equal(ui.db[0].assets.length, 1); assert.equal(ui.get('project-save-status').textContent, 'Saved');
});

test('typing during a save keeps the newer content and saves it afterwards', async () => {
  const ui = await setup(); await ui.type('topic', 'First');
  const release = ui.pauseNextSave(); const saving = ui.save(); await settle();
  assert.equal(ui.get('project-name').disabled, true);
  await ui.type('topic', 'Second'); release(); await saving; await settle();
  assert.equal(ui.form.elements.topic.value, 'Second'); await ui.timers();
  assert.equal(ui.db.length, 1); assert.equal(ui.db[0].topic, 'Second');
  assert.equal(ui.get('project-save-status').textContent, 'Saved');
});

test('unsupported file selections do not disturb the existing analyzed project', async () => {
  const ui = await analyzed(); await ui.clips(['photo.png']);
  assert.equal(ui.db[0].assets.length, 1); assert.equal(ui.get('copy-editor-prompt').disabled, false);
  assert.match(ui.get('editor-error').textContent, /MP4 video clips only/);
});

test('Save draft saves the suggested name once; New project shows a fresh editable suggestion', async () => {
  const ui = await setup();
  assert.equal(ui.get('project-name').placeholder, 'Project_1');
  await ui.save();
  assert.equal(ui.db[0].name, 'Project_1'); assert.equal(ui.db[0].status, 'draft');
  await ui.get('new-editor-project').emit('click');
  assert.equal(ui.get('editor-files').disabled, true);
  assert.equal(ui.db.length, 1); assert.equal(ui.get('project-name').value, '');
  assert.equal(ui.get('project-name').placeholder, 'Project_2'); assert.equal(ui.get('project-name').readOnly, false);
  await ui.save(); assert.equal(ui.db[1].name, 'Project_2');
  assert.equal(ui.get('editor-files').disabled, false);
});

test('switching from an unsaved project offers Cancel, Discard, and Save draft', async () => {
  const ui = await analyzed(), previous = ui.db[0].id;
  await ui.get('new-editor-project').emit('click');
  await ui.name('Unfinished'); await ui.type('context', 'New work'); await ui.timers();
  assert.equal(ui.db.length, 1);
  await ui.leave('cancel', previous);
  assert.equal(ui.db.length, 1); assert.equal(ui.get('project-name').value, 'Unfinished');
  assert.equal(ui.get('project-list').value, ''); assert.equal(ui.form.elements.context.value, 'New work');
  await ui.leave('discard', previous);
  assert.equal(ui.db.length, 1); assert.equal(ui.get('project-name').value, 'Project_1');
  assert.equal(ui.get('copy-editor-prompt').disabled, false);
  await ui.get('new-editor-project').emit('click');
  await ui.name('Keep me'); await ui.type('context', 'Saved before uploading');
  await ui.leave('save', previous);
  assert.equal(ui.db.length, 2); assert.equal(ui.db[1].name, 'Keep me'); assert.equal(ui.db[1].assets.length, 0);
  assert.equal(ui.get('project-name').value, 'Project_1');
  ui.get('project-list').value = ui.db[1].id; await ui.get('project-list').emit('change');
  assert.equal(ui.get('project-name').value, 'Keep me'); assert.equal(ui.get('project-name').readOnly, true);
});

test('New project also confirms name-only unsaved work and handles Escape as Cancel', async () => {
  const ui = await setup(); await ui.name('Name only');
  const navigation = ui.get('new-editor-project').emit('click'); await settle();
  assert.equal(ui.get('leave-project-dialog').open, true);
  ui.get('leave-project-dialog').close(''); await navigation;
  assert.equal(ui.get('project-name').value, 'Name only'); assert.equal(ui.db.length, 0);
  await ui.leave('save');
  assert.equal(ui.db[0].name, 'Name only'); assert.equal(ui.get('project-name').value, '');
});

test('failed Save draft while switching keeps new work and the current selection', async () => {
  const ui = await analyzed(), previous = ui.db[0].id;
  await ui.get('new-editor-project').emit('click'); await ui.type('context', 'Unsaved project details');
  ui.failNextSave(); await ui.leave('save', previous);
  assert.equal(ui.db.length, 1); assert.equal(ui.get('project-list').value, '');
  assert.equal(ui.form.elements.context.value, 'Unsaved project details');
  assert.match(ui.get('editor-error').textContent, /Disk unavailable/);
  await ui.get('retry-project-save').emit('click'); assert.equal(ui.db.length, 2);
});

test('switching away from a saved project flushes its latest changes without a dialog', async () => {
  const ui = await analyzed(), previous = ui.db[0].id;
  await ui.get('new-editor-project').emit('click'); await ui.save();
  await ui.type('context', 'Keep this change');
  ui.get('project-list').value = previous; await ui.get('project-list').emit('change');
  assert.equal(ui.db[1].context, 'Keep this change');
  assert.equal(ui.get('project-name').value, 'Project_1'); assert.ok(!ui.get('leave-project-dialog').open);
});

test('duplicate names block first save until the user chooses an available name', async () => {
  const ui = await analyzed(); await ui.get('new-editor-project').emit('click');
  await ui.name('project_1');
  assert.equal(ui.get('save-editor-draft').disabled, true);
  assert.match(ui.get('project-name-message').textContent, /already exists/);
  await ui.save(); assert.equal(ui.db.length, 1);
  await ui.name('Another video'); await ui.save();
  assert.equal(ui.db.length, 2); assert.equal(ui.db[1].name, 'Another video');
});

test('a failed autosave blocks switching from a saved project and preserves edited content', async () => {
  const ui = await analyzed(), previous = ui.db[0].id;
  await ui.get('new-editor-project').emit('click'); await ui.save();
  await ui.type('context', 'Still working'); ui.failNextSave();
  ui.get('project-list').value = previous; await ui.get('project-list').emit('change');
  assert.equal(ui.get('project-name').value, 'Project_2'); assert.equal(ui.get('project-list').value, ui.db[1].id);
  assert.equal(ui.form.elements.context.value, 'Still working');
  await ui.get('retry-project-save').emit('click'); assert.equal(ui.db[1].context, 'Still working');
});
