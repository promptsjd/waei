(function() {
  var status = window.JOB_STATUS;
  var jobId = window.JOB_ID;
  var jobType = window.JOB_TYPE || 'analyze';
  var isShotlist = jobType === 'shotlist';

  if (status === 'pending') {
    var pendingPoll = setInterval(function() {
      fetch('/api/jobs/' + jobId).then(function(r) { if (!r.ok) throw new Error(r.statusText); return r.json(); }).then(function(job) {
        if (job.status !== 'pending') { clearInterval(pendingPoll); window.location.reload(); }
      });
    }, 1000);
  }

  // ---- Start button ----
  var btnStart = document.getElementById('btn-start');
  if (btnStart) {
    btnStart.addEventListener('click', function() {
      btnStart.disabled = true;
      btnStart.textContent = 'Starting...';
      fetch('/api/jobs/' + jobId + '/start', { method: 'POST' })
        .then(function(r) {
          if (r.ok) { window.location.reload(); }
          else { r.json().then(function(e) { alert(e.detail); btnStart.disabled = false; btnStart.textContent = isShotlist ? 'Generate shot list' : 'Start analysis'; }); }
        })
        .catch(function() { btnStart.disabled = false; btnStart.textContent = isShotlist ? 'Generate shot list' : 'Start analysis'; });
    });
  }

  // ---- SSE progress ----
  if (status === 'running') {
    var evtSource = new EventSource('/api/jobs/' + jobId + '/events');
    var bar = document.getElementById('progress-bar');
    var label = document.getElementById('progress-label');

    evtSource.addEventListener('state', function(e) {
      var s = JSON.parse(e.data);
      if (s.status === 'completed' || s.status === 'failed') {
        evtSource.close();
        window.location.reload();
      }
    });

    evtSource.addEventListener('progress', function(e) {
      var p = JSON.parse(e.data);
      var pct = typeof p.overall_percent === 'number' ? p.overall_percent : 0;
      bar.style.width = Math.round(pct) + '%';
      var name = p.stage_label || p.stage;
      label.textContent = name + (p.message ? '  ' + p.message : '');
    });

    evtSource.addEventListener('complete', function() {
      evtSource.close();
      window.location.reload();
    });

    evtSource.addEventListener('failed', function(e) {
      evtSource.close();
      var d = JSON.parse(e.data);
      alert((isShotlist ? 'Shot list failed: ' : 'Analysis failed: ') + (d.error || 'Unknown error'));
      window.location.reload();
    });
  }

  // ---- Load results ----
  if (status === 'completed') {
    if (isShotlist) {
      fetch('/api/jobs/' + jobId + '/shots')
        .then(function(r) { if (!r.ok) throw new Error(r.statusText); return r.json(); })
        .then(function(data) { renderShotlist(data); })
        .catch(function(err) {
          document.getElementById('shotlist-container').innerHTML = '<p class="error-hint">Loading failed: ' + err.message + '</p>';
        });

      document.getElementById('btn-regenerate').addEventListener('click', function() {
        var btn = this;
        btn.disabled = true;
        btn.textContent = 'Generating...';
        fetch('/api/jobs/' + jobId + '/regenerate-shotlist', { method: 'POST' })
          .then(function(r) { if (!r.ok) throw new Error(r.statusText); return r.json(); })
          .then(function(d) {
            document.getElementById('action-status').textContent = 'Shot list updated: ' + d.html_path;
            btn.disabled = false;
            btn.textContent = 'Rebuild shot list';
          })
          .catch(function() { btn.disabled = false; btn.textContent = 'Rebuild shot list'; });
      });
    } else {
      fetch('/api/jobs/' + jobId + '/scenes')
        .then(function(r) { if (!r.ok) throw new Error(r.statusText); return r.json(); })
        .then(function(data) { renderScenes(data); })
        .catch(function(err) {
          document.getElementById('scene-list').innerHTML = '<p class="error-hint">Loading failed: ' + err.message + '</p>';
        });

      document.getElementById('btn-regenerate').addEventListener('click', function() {
        var btn = this;
        btn.disabled = true;
        btn.textContent = 'Generating...';
        fetch('/api/jobs/' + jobId + '/regenerate-report', { method: 'POST' })
          .then(function(r) { if (!r.ok) throw new Error(r.statusText); return r.json(); })
          .then(function(d) {
            document.getElementById('action-status').textContent = 'Report updated: ' + d.html_path;
            btn.disabled = false;
            btn.textContent = 'Rebuild report';
          })
          .catch(function() { btn.disabled = false; btn.textContent = 'Rebuild report'; });
      });

      var btnEnrich = document.getElementById('btn-enrich');
      if (btnEnrich) {
        btnEnrich.addEventListener('click', function() {
          if (!confirm('Generate descriptions locally on CPU? This can take a while.')) return;
          btnEnrich.disabled = true;
          btnEnrich.textContent = 'Processing...';
          fetch('/api/jobs/' + jobId + '/enrich-visuals', { method: 'POST' })
            .then(function(r) { if (!r.ok) throw new Error(r.statusText); return r.json(); })
            .then(function() { window.location.reload(); })
            .catch(function() { btnEnrich.disabled = false; btnEnrich.textContent = 'Add visual descriptions'; });
        });
      }
    }
  }

  function renderShotlist(data) {
    var shots = data.shots || [];
    var container = document.getElementById('shotlist-container');
    if (!shots.length) {
      container.innerHTML = '<p class="empty-hint">No scenes</p>';
      return;
    }
    var html = '<p class="scene-count">Total: ' + shots.length + ' Scene</p>';
    html += '<div class="shotlist-table-wrap"><table class="shotlist-table"><thead><tr><th>#</th><th>Start frame</th><th>End frame</th></tr></thead><tbody>';
    shots.forEach(function(s) {
      var startUrl = '/api/jobs/' + jobId + '/files/' + s.start_frame_path;
      var endUrl = '/api/jobs/' + jobId + '/files/' + s.end_frame_path;
      html += '<tr>' +
        '<td class="shot-num">' + s.shot_id + '</td>' +
        '<td class="frame-cell">' +
          '<img src="' + startUrl + '" alt="Shot ' + s.shot_id + ' start" loading="lazy">' +
          '<div class="frame-tc">' + esc(s.start_timecode) + '</div>' +
        '</td>' +
        '<td class="frame-cell">' +
          '<img src="' + endUrl + '" alt="Shot ' + s.shot_id + ' end" loading="lazy">' +
          '<div class="frame-tc">' + esc(s.end_timecode) + '</div>' +
        '</td>' +
        '</tr>';
    });
    html += '</tbody></table></div>';
    container.innerHTML = html;
  }

  function renderScenes(data) {
    var scenes = data.scenes || [];
    var summary = data.summary || {};
    var container = document.getElementById('scene-list');
    if (!scenes.length) {
      container.innerHTML = '<p class="empty-hint">No scenes</p>';
      return;
    }
    var html = '<p class="scene-count">Total: ' + scenes.length + ' Scene</p>';
    scenes.forEach(function(s) {
      var frameUrl = '/api/jobs/' + jobId + '/files/' + s.screenshot_path;
      var audioUrl = '/api/jobs/' + jobId + '/files/' + s.audio_path;
      html += '<article class="scene-card">'
        + '<div class="scene-header">'
        + '<span class="chip">Scene ' + String(s.scene_id).padStart(3, '0') + '</span>'
        + '<span class="chip">' + esc(s.start_timecode) + ' → ' + esc(s.end_timecode) + '</span>'
        + '<span class="chip">' + fmtNum(s.duration_seconds) + ' s</span>'
        + '</div>'
        + '<div class="scene-layout">'
        + '<div>'
        + '<img class="thumb" src="' + frameUrl + '" alt="Scene ' + s.scene_id + '" loading="lazy">'
        + '<div class="thumb-caption">' + esc(s.screenshot_path) + '</div>'
        + '</div>'
        + '<div class="sheet">'
        + row2('Start time', esc(s.start_timecode), 'End time', esc(s.end_timecode))
        + row2('Duration', fmtNum(s.duration_seconds) + ' s', 'Representative frame', String(s.representative_frame))
        + row2('Shot size', txtOr(s.shot_size), 'Camera motion', txtOr(s.camera_motion))
        + row1('Visual description', txtOr(s.visual_description))
        + row1('Dialogue', txtOr(s.dialogue))
        + row2('Sound effects', txtOr(s.sound_effects), 'BGM', txtOr(s.bgm))
        + row1('Audio', s.audio_path ? '<audio controls preload="none" src="' + audioUrl + '"></audio><br><span class="audio-path">' + esc(s.audio_path) + '</span>' : 'No audio track')
        + row1('Notes', txtOr(s.notes))
        + '</div></div></article>';
    });
    container.innerHTML = html;
  }

  function row1(label, value) {
    return '<div class="sheet-row"><div class="sheet-label">' + label + '</div><div class="sheet-value">' + value + '</div></div>';
  }
  function row2(l1, v1, l2, v2) {
    return '<div class="double-row"><div class="sheet-label">' + l1 + '</div><div class="sheet-value">' + v1 + '</div><div class="sheet-label">' + l2 + '</div><div class="sheet-value">' + v2 + '</div></div>';
  }
  function esc(s) { var d = document.createElement('div'); d.textContent = (s == null ? '' : String(s)); return d.innerHTML; }
  function fmtNum(v) { if (v == null) return '-'; if (typeof v === 'number') { var s = v.toFixed(3); return s.replace(/0+$/, '').replace(/\.$/, ''); } return String(v); }
  function txtOr(v) { if (!v || !String(v).trim()) return '<span class="empty"></span>'; return esc(v); }
})();
