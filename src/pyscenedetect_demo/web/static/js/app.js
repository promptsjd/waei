(function () {
  var feedbackLink = document.getElementById('send-feedback');
  var feedbackDialog = document.getElementById('feedback-dialog');
  if (feedbackLink && feedbackDialog && typeof feedbackDialog.showModal === 'function') {
    var feedbackEmail = document.getElementById('feedback-email');
    var feedbackStatus = document.getElementById('feedback-copy-status');
    feedbackLink.addEventListener('click', function (event) {
      event.preventDefault();
      feedbackStatus.textContent = '';
      feedbackDialog.showModal();
    });
    document.getElementById('close-feedback').addEventListener('click', function () {
      feedbackDialog.close();
    });
    document.getElementById('copy-feedback-email').addEventListener('click', async function () {
      try {
        await navigator.clipboard.writeText(feedbackEmail.value);
        feedbackStatus.textContent = 'Email address copied.';
      } catch (_) {
        feedbackEmail.focus();
        feedbackEmail.select();
        feedbackStatus.textContent = 'Copy the selected address with Ctrl+C (or Command+C).';
      }
    });
  }

  // ==================================================================
  // File drop zone
  // ==================================================================
  var dropZone = document.getElementById('drop-zone');
  var fileInput = document.getElementById('file-input');
  var fileInfo = document.getElementById('file-info');
  var fileName = document.getElementById('file-name');
  var fileSize = document.getElementById('file-size');
  var configForm = document.getElementById('config-form');
  var submitBtn = document.getElementById('submit-btn');
  var uploadProgress = document.getElementById('upload-progress');
  var analyzeFields = document.getElementById('analyze-fields');
  var modeInput = configForm && configForm.querySelector('[name="mode"]');

  var selectedFile = null;

  function formatSize(bytes) {
    if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB';
    return (bytes / (1024 * 1024)).toFixed(1) + ' MB';
  }

  function showFile(file) {
    selectedFile = file;
    fileName.textContent = file.name;
    fileSize.textContent = formatSize(file.size);
    fileInfo.classList.remove('hidden');
    configForm.classList.remove('hidden');
    submitBtn.disabled = false;
  }

  // ---- Mode toggle ----
  if (configForm) {
    var modeRadios = configForm.querySelectorAll('[name="_mode"]');
    modeRadios.forEach(function (r) {
      r.addEventListener('change', function () {
        var isShotlist = this.value === 'shotlist';
        if (analyzeFields) {
          analyzeFields.style.display = isShotlist ? 'none' : '';
        }
        modeInput.value = this.value;
        submitBtn.textContent = isShotlist ? 'Generate shot list' : 'Start analysis';
      });
    });
  }

  if (dropZone) {
    dropZone.addEventListener('click', function () {
      fileInput.click();
    });

    dropZone.addEventListener('dragover', function (e) {
      e.preventDefault();
      dropZone.classList.add('drag-over');
    });

    dropZone.addEventListener('dragleave', function () {
      dropZone.classList.remove('drag-over');
    });

    dropZone.addEventListener('drop', function (e) {
      e.preventDefault();
      dropZone.classList.remove('drag-over');
      var files = e.dataTransfer.files;
      if (files.length > 0) {
        var f = files[0];
        if (!f.name.toLowerCase().endsWith('.mp4')) {
          alert('Only MP4 files are supported');
          return;
        }
        showFile(f);
      }
    });

    fileInput.addEventListener('change', function () {
      if (fileInput.files.length > 0) {
        showFile(fileInput.files[0]);
      }
    });
  }

  // ==================================================================
  // Form submit (upload + create job)
  // ==================================================================
  if (configForm) {
    configForm.addEventListener('submit', function (e) {
      e.preventDefault();
      if (!selectedFile) return;

      var formData = new FormData();
      formData.append('video', selectedFile);

      var currentMode = modeInput ? modeInput.value : 'analyze';

      var fields = ['detector', 'threshold', 'min_scene_len'];
      if (currentMode === 'analyze') {
        fields = fields.concat(['transcribe', 'asr_model', 'language', 'describe_visuals', 'vision_model']);
      }
      formData.append('mode', currentMode);

      fields.forEach(function (name) {
        var el = configForm.querySelector('[name="' + name + '"]');
        if (!el) return;
        if (el.type === 'checkbox') {
          if (el.checked) formData.append(name, el.value || 'on');
        } else {
          formData.append(name, el.value);
        }
      });

      submitBtn.disabled = true;
      submitBtn.textContent = 'Uploading...';
      uploadProgress.classList.remove('hidden');
      uploadProgress.value = 0;

      var xhr = new XMLHttpRequest();
      xhr.open('POST', '/api/jobs');

      xhr.upload.onprogress = function (ev) {
        if (ev.lengthComputable) {
          uploadProgress.value = (ev.loaded / ev.total) * 100;
        }
      };

      xhr.onload = function () {
        if (xhr.status >= 200 && xhr.status < 300) {
          var resp = JSON.parse(xhr.responseText);
          window.location.href = '/jobs/' + resp.job_id;
        } else {
          try {
            var err = JSON.parse(xhr.responseText);
            alert('Upload failed: ' + (err.detail || xhr.statusText));
          } catch (_) {
            alert('Upload failed: ' + xhr.statusText);
          }
          submitBtn.disabled = false;
          submitBtn.textContent = currentMode === 'shotlist' ? 'Generate shot list' : 'Start analysis';
          uploadProgress.classList.add('hidden');
        }
      };

      xhr.onerror = function () {
        alert('Network error. Please retry.');
        submitBtn.disabled = false;
        submitBtn.textContent = currentMode === 'shotlist' ? 'Generate shot list' : 'Start analysis';
        uploadProgress.classList.add('hidden');
      };

      xhr.send(formData);
    });
  }

  // ==================================================================
  // Auto-refresh job list (every 10s)
  // ==================================================================
  var jobTable = document.getElementById('job-table');
  if (jobTable) {
    setInterval(function () {
      fetch('/api/jobs')
        .then(function (r) { return r.json(); })
        .then(function (jobs) {
          var tbody = jobTable.querySelector('tbody');
          if (!tbody) return;
          tbody.innerHTML = '';
          if (jobs.length === 0) {
            tbody.innerHTML = '<tr><td colspan="6" class="empty-hint">No jobs yet</td></tr>';
            return;
          }
          jobs.forEach(function (j) {
            var statusLabels = { pending: 'Pending', running: 'Running', completed: 'Completed', failed: 'Failed' };
            var statusLabel = statusLabels[j.status] || j.status;
            var time = (j.created_at || '').substring(0, 19) || '-';
            var typeLabel = j.job_type === 'shotlist' ? 'Shot list' : 'Analysis';
            var count = j.shot_count || j.scene_count || '-';
            tbody.innerHTML +=
              '<tr data-job-id="' + j.id + '">' +
              '<td>' + typeLabel + '</td>' +
              '<td><span class="badge badge-' + j.status + '">' + statusLabel + '</span></td>' +
              '<td class="td-name" title="' + escAttr(j.video_name) + '">' + escHtml(j.video_name) + '</td>' +
              '<td>' + count + '</td>' +
              '<td class="td-time">' + time + '</td>' +
              '<td class="td-actions">' +
              '<a href="/jobs/' + j.id + '" class="btn btn-sm">View</a> ' +
              '<button class="btn btn-sm btn-danger btn-delete" data-job-id="' + j.id + '">Delete</button>' +
              '</td></tr>';
          });
        });
    }, 10000);
  }

  // ==================================================================
  // Delete job buttons (delegated)
  // ==================================================================
  document.addEventListener('click', function (e) {
    var btn = e.target.closest('.btn-delete');
    if (!btn) return;
    var jobId = btn.getAttribute('data-job-id');
    if (!confirm('Delete this job and all its output?')) return;
    fetch('/api/jobs/' + jobId, { method: 'DELETE' }).then(function (r) {
      if (r.ok) {
        var row = btn.closest('tr');
        if (row) row.remove();
      } else {
        alert('Delete failed');
      }
    });
  });

  function escHtml(s) {
    var d = document.createElement('div');
    d.textContent = (s == null ? '' : String(s));
    return d.innerHTML;
  }
  function escAttr(s) {
    return (s == null ? '' : String(s)).replace(/&/g, '&amp;').replace(/"/g, '&quot;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  }
})();
