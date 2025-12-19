(() => {
  const $ = (id) => document.getElementById(id);

  const btnSend = $('btnSend');
  const btnClear = $('btnClear');
  const btnCopyLog = $('btnCopyLog');
  const out = $('output');
  const previewGrid = $('previewGrid');
  const taskList = $('taskList');
  const taskCount = $('taskCount');
  const dropzone = $('dropzone');
  const fileInput = $('file');
  const promptBox = $('prompt');
  const tagBar = $('tagBar');
  const roleList = $('roleList');
  const roleSearch = $('roleSearch');
  const btnReloadRoles = $('btnReloadRoles');
  const attachedRolesBox = $('attachedRoles');
  const formStorageKey = 'gen_form_v1';
  const btnClearDone = $('btnClearDone');
  const btnClearAll = $('btnClearAll');
  const taskStorageKey = 'gen_tasks_v1';
  const roleStorageKey = 'gen_roles_v1';
  const authHeaderKey = 'adminToken';
  const batchPromptList = $('batchPromptList');
  const batchModeBar = $('batchModeBar');
  const batchConcurrencyInput = $('batchConcurrency');
  const btnExportBatch = $('btnExportBatch');
  const btnImportBatch = $('btnImportBatch');
  const importBatchFile = $('importBatchFile');

  let tasks = [];
  let taskIdCounter = 1;
  let roles = [];
  let attachedRoles = [];
  const getAuthHeaders = () => {
    const t = localStorage.getItem(authHeaderKey);
    return t ? { Authorization: `Bearer ${t}` } : {};
  };

  const showToast = (msg) => {
    const d = document.createElement('div');
    d.className =
      'fixed bottom-4 right-4 bg-slate-800 text-white px-4 py-2.5 rounded-lg shadow-lg text-sm font-medium z-50';
    d.textContent = msg;
    document.body.appendChild(d);
    setTimeout(() => {
      d.style.opacity = '0';
      d.style.transition = 'opacity .3s';
      setTimeout(() => d.parentNode && document.body.removeChild(d), 300);
    }, 1800);
  };

  const log = (msg) => {
    const line = `[${new Date().toLocaleTimeString()}] ${msg}`;
    // 仅保留最�?4000 字，避免日志无限增高
    const next = (out.textContent || '') + line + '\n';
    out.textContent = next.slice(-4000);
    out.scrollTop = out.scrollHeight;
  };

  const setTaskCount = () => {
    taskCount.textContent = `${tasks.length} 个任务`;
  };

  const renderTasks = () => {
    const html = tasks
      .map((t) => {
        const statusText = {
          queue: '排队�?,
          running: '生成�?,
          done: '已完�?,
          error: '失败',
          stalled: '中断'
        }[t.status] || '未知';
        const statusClass = `status ${t.status}`;
        const msg = t.message || '';
        const metaText = t.meta
          ? [t.meta.resolution, t.meta.duration].filter(Boolean).join(' · ')
          : '';
        const stepIdx = t.status === 'queue' ? 1 : t.status === 'running' ? 2 : 3;
        const stepClass = t.status === 'error' ? 'error' : 'active';
        const missingUrlWarn = t.status === 'done' && !t.url ? '<div style="margin-top:6px;font-size:12px;color:#b45309;">未返回视频链接，可能生成失败或后台未返回地址</div>' : '';
        const progress = t.progress ?? (t.status === 'done' ? 100 : 0);
        return `
          <div class="task-card">
            <div>
              <div class="${statusClass}">${statusText}</div>
              <div class="muted" style="margin-top:6px;">${t.promptSnippet || '-'}</div>
              ${metaText ? `<div class="muted" style="margin-top:4px;font-size:12px;">${metaText}</div>` : ''}
              ${msg ? `<div style="margin-top:6px;font-size:12px;color:#f87171;">${msg}</div>` : ''}
              ${missingUrlWarn}
              <div style="margin-top:8px;">
                <div style="height:8px;border-radius:4px;background:#e5e7eb;overflow:hidden;">
                  <div style="height:100%;width:${progress}%;background:#2563eb;transition:width .2s ease;"></div>
                </div>
                <div class="muted" style="font-size:12px;margin-top:4px;">进度�?{progress}%</div>
              </div>
              <div class="task-steps">
                <div class="task-step ${stepIdx>=1?stepClass:''}"></div>
                <div class="task-step ${stepIdx>=2?stepClass:''}"></div>
                <div class="task-step ${stepIdx>=3?stepClass:''}"></div>
              </div>
            </div>
            <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap;justify-content:flex-end;">
              ${t.url ? `<button class="link-btn" data-url="${t.url}" data-type="${t.type || 'video'}">预览</button>` : ''}
              ${(!t.url && t.status==='done') ? `<button class="link-btn" data-retry="${t.id}">重试</button>` : ''}
              ${t.promptFull ? `<button class="link-btn" data-reuse="${t.id}">复用提示</button>` : ''}
              ${t.logTail ? `<button class="link-btn" data-log="${t.id}">查看日志片段</button>` : ''}
            </div>
          </div>
        `;
      })
      .join('');
    taskList.innerHTML = html || '<div class="muted">暂无任务</div>';

    // 绑定预览按钮
    taskList.querySelectorAll('.link-btn').forEach((btn) => {
      btn.addEventListener('click', () => {
        const url = btn.getAttribute('data-url');
        const type = btn.getAttribute('data-type');
        addPreviewCard(url, type);
      });
    });
    taskList.querySelectorAll('[data-reuse]').forEach((btn) => {
      btn.addEventListener('click', () => {
        const id = parseInt(btn.getAttribute('data-reuse'), 10);
        const t = tasks.find((x) => x.id === id);
        if (t && t.promptFull) {
          promptBox.value = t.promptFull;
          analyzePromptHints();
          showToast('已复用提示词');
        }
      });
    });
    taskList.querySelectorAll('[data-retry]').forEach((btn) => {
      btn.addEventListener('click', async () => {
        const id = parseInt(btn.getAttribute('data-retry'), 10);
        const t = tasks.find((x) => x.id === id);
        if (!t || !t.promptFull) { showToast('无可用提示词，无法重�?); return; }
        const apiKey = $('apiKey').value.trim();
        const baseUrl = getBaseUrl();
        if (!apiKey || !baseUrl) {
          showToast('请先填写 API Key �?服务器地址');
          return;
        }
        await runJobs([{ prompt: t.promptFull, file: null, model: $('model').value }], apiKey, baseUrl, 1);
      });
    });
    taskList.querySelectorAll('[data-log]').forEach((btn) => {
      btn.addEventListener('click', () => {
        const id = parseInt(btn.getAttribute('data-log'), 10);
        const t = tasks.find((x) => x.id === id);
        if (t && t.logTail) {
          out.textContent = t.logTail;
          out.scrollTop = out.scrollHeight;
        }
      });
    });

    setTaskCount();
    updateTaskBubble();
    // 同步任务概要给父页面，用于全局任务抽屉
    try {
      if (window.parent && window.parent !== window) {
        const summary = tasks.map((t) => ({
          id: t.id,
          status: t.status,
          prompt: t.promptSnippet,
          url: t.url,
          meta: t.meta,
          message: t.message,
          progress: t.progress ?? 0
        }));
        window.parent.postMessage({ type: 'task_state', tasks: summary }, '*');
      }
    } catch (_) {}
  };

  const renderPreviews = () => {
    previewGrid.innerHTML = '';
    tasks
      .filter((t) => t.url)
      .forEach((t) => addPreviewCard(t.url, t.type, false));
  };

  const addPreviewCard = (url, type = 'video', push = true, meta = null) => {
    if (!url || !isValidMediaUrl(url)) return;
    // 去重：如果已存在�?url 的卡片则不再新增
    const exists = Array.from(previewGrid.querySelectorAll('.preview-card')).some((card) => {
      const src = card.querySelector('video,img')?.getAttribute(type === 'image' ? 'src' : 'src');
      return src === url;
    });
    if (exists) return;
    const card = document.createElement('div');
    card.className = 'preview-card';
    if (type === 'image') {
      card.innerHTML = `<img src="${url}" alt="preview">`;
    } else {
      card.innerHTML = `<video src="${url}" controls></video>`;
    }
    const info = document.createElement('div');
    info.className = 'preview-info';
    info.innerHTML = `
      <span class="muted" style="flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${url}</span>
      ${meta ? `<span class="chip">${meta}</span>` : ''}
      <a class="link-btn" href="${url}" download target="_blank">下载</a>
      <button class="link-btn" data-copy="${url}">复制链接</button>
    `;
    card.appendChild(info);
    previewGrid.prepend(card);

    card.querySelectorAll('[data-copy]').forEach((btn) => {
      btn.addEventListener('click', () => {
        navigator.clipboard.writeText(btn.getAttribute('data-copy')).then(
          () => showToast('已复制链�?),
          () => showToast('复制失败')
        );
      });
    });

    if (push) {
      // 仅作为临时预览，不写回任�?    }
  };

  const persistTasks = () => {
    const compact = tasks
      .slice(0, 20)
      .map(({ id, status, promptSnippet, url, type, message, meta, promptFull, logTail, progress }) => ({
        id,
        status,
        promptSnippet,
        url,
        type,
        message,
        meta,
        promptFull,
        logTail,
        progress
      }));
    localStorage.setItem(taskStorageKey, JSON.stringify(compact));
  };

  const loadTasksFromStorage = () => {
    try {
      const saved = JSON.parse(localStorage.getItem(taskStorageKey) || '[]');
      if (Array.isArray(saved)) {
        tasks = saved.map((t) => {
          // 刷新后将进行中的标记为“可能中断�?          if (t.status === 'running' || t.status === 'queue') {
            return { ...t, status: 'stalled', message: '刷新后任务可能中断，请重�?, progress: t.progress ?? 0 };
          }
          return t;
        });
        if (tasks.length) {
          taskIdCounter = Math.max(...tasks.map((t) => t.id)) + 1;
        }
      }
    } catch (_) {
      tasks = [];
    }
  };

  const persistRoles = () => {
    localStorage.setItem(roleStorageKey, JSON.stringify(attachedRoles));
  };

  const loadRolesFromStorage = () => {
    try {
      attachedRoles = JSON.parse(localStorage.getItem(roleStorageKey) || '[]');
      if (!Array.isArray(attachedRoles)) attachedRoles = [];
    } catch (_) {
      attachedRoles = [];
    }
  };

  const addTask = (promptSnippet, promptFull) => {
    const t = {
      id: taskIdCounter++,
      status: 'queue',
      promptSnippet,
      promptFull,
      url: null,
      type: 'video',
      meta: null,
      logTail: ''
    };
    tasks.unshift(t);
    renderTasks();
    persistTasks();
    return t.id;
  };

  const updateTask = (id, patch) => {
    tasks = tasks.map((t) => (t.id === id ? { ...t, ...patch } : t));
    renderTasks();
    renderPreviews();
    persistTasks();
  };

  const updateTaskBubble = () => {
    const running = tasks.filter((t) => t.status === 'running' || t.status === 'queue').length;
    const total = tasks.length;
    // 通知父页面（如管理页 iframe 容器）更新全局任务�?    try {
      if (window.parent && window.parent !== window) {
        window.parent.postMessage({ type: 'task_count', running, total }, '*');
      }
    } catch (_) {}
  };

  // 核心：执行一组任务（支持并发�?  const runJobs = async (jobs, apiKey, baseUrl, concurrency = 1) => {
    if (!jobs || !jobs.length) return;
    const poolSize = Math.min(concurrency, jobs.length);
    let cursor = 0;

    const isValidMediaUrl = (u) => {
      if (!u) return false;
      const s = u.toString();
      const domainOk = /videos\.openai\.com|oscdn\d?\.dyysy\.com/i.test(s);
      const extOk = /\.(mp4|webm|mov|m4v|mpg|mpeg|avi|gif|png|jpg|jpeg|webp)(\?|$)/i.test(s);
      return domainOk || extOk;
    };

    const runJob = async (job) => {
      const contentArr = [];
      if (job.prompt) contentArr.push({ type: 'text', text: job.prompt });
      if (job.file) {
        log(`读取文件: ${job.file.name}`);
        const dataUrl = await fileToDataUrl(job.file);
        if (job.file.type.startsWith('video')) {
          contentArr.push({ type: 'video_url', video_url: { url: dataUrl } });
        } else {
          contentArr.push({ type: 'image_url', image_url: { url: dataUrl } });
        }
      }

      const body = {
        model: job.model,
        stream: true,
        messages: [
          {
            role: 'user',
            content: contentArr.length ? contentArr : job.prompt
          }
        ]
      };

      const taskId = addTask((job.prompt || '').slice(0, 80) || (job.file ? job.file.name : '(空提�?'), job.prompt);
      updateTask(taskId, { status: 'running', progress: 0 });

      const url = `${baseUrl}/v1/chat/completions`;
      let lastChunk = '';
      try {
        const resp = await fetch(url, {
          method: 'POST',
          headers: {
            Authorization: 'Bearer ' + apiKey,
            'Content-Type': 'application/json',
            Accept: 'text/event-stream'
          },
          body: JSON.stringify(body)
        });

        if (!resp.ok || !resp.body) {
          throw new Error('HTTP ' + resp.status);
        }

        const reader = resp.body.getReader();
        const decoder = new TextDecoder();
        let mediaUrl = null;
        let mediaType = 'video';
        let mediaMeta = null;

        log(`连接成功，开始接收流... [任务#${taskId}]`);
        while (true) {
          const { value, done } = await reader.read();
          if (done) break;
          const chunk = decoder.decode(value, { stream: true });
          lastChunk = chunk || lastChunk;
          chunk.split(/\n\n/).forEach((line) => {
            if (!line.startsWith('data:')) return;
            const data = line.replace(/^data:\s*/, '');
            if (data === '[DONE]') {
              log('[DONE]');
              return;
            }
            log(data);
            try {
              const obj = JSON.parse(data);
              // 解析进度
              let progress = t => t;
              const pctMatch = data.match(/(\\d{1,3})%/);
              if (obj.progress !== undefined && !isNaN(parseFloat(obj.progress))) {
                progress = parseFloat(obj.progress);
              } else if (pctMatch) {
                progress = Math.min(100, parseFloat(pctMatch[1]));
              }
              if (!isNaN(progress)) {
                updateTask(taskId, { progress });
              }
              // 先走结构化字�?              const candidates = [
                obj.url,
                obj.video_url && obj.video_url.url,
                obj.image_url && obj.image_url.url,
                obj.output && obj.output[0] && (obj.output[0].url || obj.output[0].video_url || obj.output[0].image_url)
              ].filter(Boolean);

              let extractedUrl = candidates[0];

              // 兜底：从 content/markdown 里提�?<video src='...'> �?http...mp4/png/jpg/webp
              if (!extractedUrl && obj.content) {
                const htmlMatch = obj.content.match(/<video[^>]+src=['"]([^'"]+)['"]/i);
                if (htmlMatch) extractedUrl = htmlMatch[1];
                const mdMatch = obj.content.match(/https?:[^\\s)'"<>]+\\.(mp4|mov|m4v|webm|png|jpg|jpeg|webp)/i);
                if (!extractedUrl && mdMatch) extractedUrl = mdMatch[0];
              }
              // 再兜底：用最�?chunk 文本尝试�?url
              if (!extractedUrl) {
                const urlMatch = lastChunk.match(/https?:[^\\s)'"<>]+\\.(mp4|mov|m4v|webm|png|jpg|jpeg|webp)/i);
                if (urlMatch) extractedUrl = urlMatch[0];
              }

              if (extractedUrl) {
                mediaUrl = extractedUrl;
              }
              if (mediaUrl) {
                mediaType = (mediaUrl && mediaUrl.toString().match(/\.(png|jpg|jpeg|webp)$/i)) ? 'image' : 'video';
                const reso =
                  obj.resolution ||
                  (obj.meta && obj.meta.resolution) ||
                  (obj.width && obj.height ? `${obj.width}x${obj.height}` : null);
                const dur =
                  obj.duration ||
                  (obj.meta && obj.meta.duration) ||
                  (obj.length && `${obj.length}s`);
                mediaMeta = [reso, dur].filter(Boolean).join(' · ');
                updateTask(taskId, { url: mediaUrl, type: mediaType, meta: { resolution: reso || '', duration: dur || '' }, logTail: lastChunk, progress: 100 });
              } else {
                updateTask(taskId, { logTail: lastChunk });
              }

              // 补充解析：兼�?OpenAI choices.delta.content，任�?http(s) 链接
              if (!mediaUrl) {
                const choice = (obj.choices && obj.choices[0]) || {};
                const delta = choice.delta || {};
                const msg = choice.message || {};
                const contentField = delta.content ?? msg.content ?? obj.content;
                const outputField = delta.output ?? msg.output ?? obj.output;
                const tryExtract = (text) => {
                  if (!text) return null;
                  const htmlMatch = text.match(/<video[^>]+src=['"]([^'"]+)['"]/i);
                  if (htmlMatch) return htmlMatch[1];
                  const anyMatch = text.match(/https?:[^\s)'"<>]+/i);
                  return anyMatch ? anyMatch[0] : null;
                };
                let extracted = tryExtract(contentField) || tryExtract(lastChunk);
                if (!extracted && outputField && outputField[0]) {
                  extracted = outputField[0].url || outputField[0].video_url || outputField[0].image_url || null;
                }
                if (extracted) {
                  mediaUrl = extracted;
                  mediaType = (mediaUrl && mediaUrl.toString().match(/\.(png|jpg|jpeg|webp)$/i)) ? 'image' : 'video';
                  updateTask(taskId, { url: mediaUrl, type: mediaType, logTail: lastChunk, progress: 100 });
                }
              }
            } catch (e) {
              updateTask(taskId, { logTail: lastChunk });
            }
          });
        }

        // 最后一搏：如果循环里没抓到 URL，再从最后一段文本里尝试匹配任意 http(s) 链接
        if (!mediaUrl) {
          const tailMatch = lastChunk.match(/https?:[^\s)'"<>]+/i);
          if (tailMatch) {
            mediaUrl = tailMatch[0];
            mediaType = mediaUrl.match(/\.(png|jpg|jpeg|webp)$/i) ? 'image' : 'video';
          }
        }

        // 白名单校验，防止把错误提�?URL 当作视频
        if (mediaUrl && !isValidMediaUrl(mediaUrl)) {
          mediaUrl = null;
        }

        if (mediaUrl) {
          updateTask(taskId, {
            status: 'done',
            url: mediaUrl,
            type: mediaType,
            meta: mediaMeta ? { info: mediaMeta } : null,
            logTail: lastChunk,
            progress: 100
          });
          addPreviewCard(mediaUrl, mediaType, true, mediaMeta);
        } else {
          updateTask(taskId, { status: 'done', logTail: lastChunk, progress: 100 });
        }
      } catch (e) {
        log('错误: ' + e.message);
        updateTask(taskId, { status: 'error', message: e.message, logTail: lastChunk, progress: 0 });
      }
    };

    const runners = Array.from({ length: poolSize }).map(async () => {
      while (cursor < jobs.length) {
        const idx = cursor++;
        await runJob(jobs[idx]);
      }
    });
    await Promise.all(runners);
  };

  const analyzePromptHints = () => {
    const txt = promptBox.value;
    const hints = [];
    const timeMatch = txt.match(/(\d+)\s?(s|sec|seconds|�?/i);
    if (timeMatch) hints.push(`时长 ${timeMatch[1]}s`);
    const resMatch = txt.match(/(\d{3,4})\s?[xX]\s?(\d{3,4})/);
    if (resMatch) hints.push(`分辨�?${resMatch[1]}x${resMatch[2]}`);
    const fpsMatch = txt.match(/(\d+)\s?fps/i);
    if (fpsMatch) hints.push(`帧率 ${fpsMatch[1]}fps`);
    if (!hints.length) hints.push('提示：描述镜头、光线、主体、动作，越具体越�?);
    $('promptHints').innerHTML = hints.map((h) => `<span class="chip">${h}</span>`).join('');
  };

  const getBaseUrl = () => $('baseUrl').value.trim().replace(/\/$/, '');

  const setBatchType = (val) => {
    batchModeBar.querySelectorAll('input[name="batchType"]').forEach((r) => {
      r.checked = r.value === val;
    });
    toggleBatchTextarea();
    saveForm();
  };

  const getBatchType = () => {
    const checked = batchModeBar.querySelector('input[name="batchType"]:checked');
    return checked ? checked.value : 'single';
  };

  const toggleBatchTextarea = () => {
    const t = getBatchType();
    batchPromptList.style.display = t === 'multi_prompt' ? 'block' : 'none';
  };

  const saveForm = () => {
    const data = {
      apiKey: $('apiKey').value,
      baseUrl: $('baseUrl').value,
      model: $('model').value,
      prompt: promptBox.value,
      batchPrompts: batchPromptList.value,
      batchType: getBatchType(),
      batchConcurrency: batchConcurrencyInput.value
    };
    localStorage.setItem(formStorageKey, JSON.stringify(data));
  };

  const loadForm = () => {
    try {
      const data = JSON.parse(localStorage.getItem(formStorageKey) || '{}');
      if (data.apiKey) $('apiKey').value = data.apiKey;
      if (data.baseUrl) $('baseUrl').value = data.baseUrl;
      if (data.model) $('model').value = data.model;
      if (data.prompt) promptBox.value = data.prompt;
      if (data.batchPrompts) batchPromptList.value = data.batchPrompts;
      if (data.batchType) setBatchType(data.batchType);
      if (data.batchConcurrency) batchConcurrencyInput.value = data.batchConcurrency;
    } catch (_) {
      /* ignore */
    }
  };

  const handleSend = async () => {
    out.textContent = '';
    const apiKey = $('apiKey').value.trim();
    const model = $('model').value;
    const baseUrl = getBaseUrl();
    const prompt = promptBox.value.trim();
    const files = Array.from((fileInput.files && fileInput.files.length ? fileInput.files : []) || []);
    const batchType = getBatchType();
    const concurrency = Math.max(1, Math.min(5, parseInt(batchConcurrencyInput.value || '1', 10) || 1));

    if (!apiKey) {
      alert('请填�?API Key');
      return;
    }

    const roleContext = attachedRoles.length ? attachedRoles.map((r) => `@${r.display}`).join(' ') : '';
    const promptWithRoles = roleContext && prompt ? `${roleContext}\n${prompt}` : prompt || roleContext;

    const jobs = [];
    if (batchType === 'same_prompt_files') {
      if (!promptWithRoles) return alert('同提示批量需填写提示�?);
      if (!files.length) return alert('请选择至少一个文�?);
      files.forEach((f) => jobs.push({ prompt: promptWithRoles, file: f, model }));
    } else if (batchType === 'multi_prompt') {
      const lines = batchPromptList.value
        .split('\n')
        .map((l) => l.trim())
        .filter(Boolean);
      if (!lines.length) return alert('请在批量输入框填入多行提�?);
      lines.forEach((p) => {
        const finalPrompt = roleContext ? `${roleContext}\n${p}` : p;
        jobs.push({ prompt: finalPrompt, file: null, model });
      });
    } else {
      // single
      if (!promptWithRoles && !files.length) return alert('请至少填写提示词或上传文�?);
      jobs.push({ prompt: promptWithRoles, file: files[0] || null, model });
    }

    btnSend.disabled = true;
    btnSend.textContent = `生成�?(${jobs.length} �?...`;

    await runJobs(jobs, apiKey, baseUrl, concurrency);

    btnSend.disabled = false;
    btnSend.textContent = '开始生�?;
  };

  const fileToDataUrl = (file) =>
    new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => resolve(reader.result);
      reader.onerror = reject;
      reader.readAsDataURL(file);
    });

  // 拖拽/选择文件
  dropzone.addEventListener('click', () => fileInput.click());
  dropzone.addEventListener('dragover', (e) => {
    e.preventDefault();
    dropzone.classList.add('dragover');
  });
  dropzone.addEventListener('dragleave', () => dropzone.classList.remove('dragover'));
  dropzone.addEventListener('drop', (e) => {
    e.preventDefault();
    dropzone.classList.remove('dragover');
    if (e.dataTransfer.files && e.dataTransfer.files.length) {
      fileInput.files = e.dataTransfer.files;
      dropzone.textContent = `已选择�?{e.dataTransfer.files[0].name}`;
    }
  });
  fileInput.addEventListener('change', () => {
    if (fileInput.files && fileInput.files[0]) {
      dropzone.textContent = `已选择�?{fileInput.files[0].name}`;
    } else {
      dropzone.textContent = '拖拽文件到这里，或点击选择';
    }
  });

  // 快捷标签
  tagBar.querySelectorAll('[data-snippet]').forEach((btn) => {
    btn.addEventListener('click', () => {
      const snippet = btn.getAttribute('data-snippet');
      const cur = promptBox.value;
      promptBox.value = cur ? `${cur}\n${snippet}` : snippet;
      analyzePromptHints();
    });
  });

  // Prompt 变更
  promptBox.addEventListener('input', analyzePromptHints);
  promptBox.addEventListener('dragover', (e) => e.preventDefault());
  promptBox.addEventListener('drop', (e) => {
    e.preventDefault();
    const text = e.dataTransfer.getData('text/plain');
    if (text) {
      try {
        const obj = JSON.parse(text);
        if (obj.display) {
          addAttachedRole(obj);
          return;
        }
      } catch (_) {
        // �?JSON 拖入则忽�?      }
    }
  });

  // 角色�?  const renderAttachedRoles = () => {
    attachedRolesBox.innerHTML =
      attachedRoles
        .map(
          (r, idx) =>
            `<span class="chip" data-attached="${idx}" draggable="true" style="display:inline-flex;align-items:center;gap:6px;">
                ${r.avatar ? `<img src="${r.avatar}" style="width:20px;height:20px;border-radius:50%;object-fit:cover;">` : ''}
                @${r.display}
                <span style="margin-left:6px;cursor:pointer;">�?/span>
             </span>`
        )
        .join('') || '';
    attachedRolesBox.querySelectorAll('[data-attached]').forEach((el) => {
      el.addEventListener('dragstart', (e) => {
        e.dataTransfer.setData('text/plain', el.getAttribute('data-attached'));
      });
      el.addEventListener('dragover', (e) => e.preventDefault());
      el.addEventListener('drop', (e) => {
        e.preventDefault();
        const from = parseInt(e.dataTransfer.getData('text/plain'), 10);
        const to = parseInt(el.getAttribute('data-attached'), 10);
        if (isNaN(from) || isNaN(to) || from === to) return;
        const tmp = attachedRoles[from];
        attachedRoles.splice(from, 1);
        attachedRoles.splice(to, 0, tmp);
        renderAttachedRoles();
        persistRoles();
      });
      el.addEventListener('click', () => {
        const idx = parseInt(el.getAttribute('data-attached'), 10);
        attachedRoles.splice(idx, 1);
        renderAttachedRoles();
        persistRoles();
      });
    });
  };

  const addAttachedRole = (roleObj) => {
    if (!roleObj || !roleObj.display) return;
    if (attachedRoles.find((r) => r.display === roleObj.display)) return;
    attachedRoles.push(roleObj);
    renderAttachedRoles();
    persistRoles();
  };

  const renderRoles = () => {
    const keyword = roleSearch.value.trim().toLowerCase();
    const filtered = roles.filter((r) => {
      const name = (r.display_name || r.username || '').toLowerCase();
      return !keyword || name.includes(keyword);
    });
    roleList.innerHTML =
      filtered
        .map((r) => {
          const avatar = r.avatar_path || '';
          const desc = (r.description || r.bio || '').slice(0, 50) || '暂无描述';
          const uname = r.username ? '@' + r.username : '';
          const roleData = {
            display: r.display_name || r.username || '角色',
            desc,
            username: r.username || '',
            avatar: avatar
          };
          return `
            <div class="role-card" draggable="true" data-role='${JSON.stringify(roleData)}'>
              <img class="role-avatar" src="${avatar || 'https://via.placeholder.com/120?text=Avatar'}" onerror="this.src='https://via.placeholder.com/120?text=Avatar'">
              <div class="role-meta">
                <div class="role-name">${roleData.display}</div>
                <div class="role-username">${uname}</div>
                <div class="role-desc">${desc}</div>
                <div class="role-actions">
                  <button class="pill-btn role-attach">挂载</button>
                  <button class="pill-btn role-copy">复制 @username</button>
                </div>
              </div>
            </div>
          `;
        })
        .join('') || '<div class="muted" style="padding:8px 4px;">暂无角色�?/div>';

    roleList.querySelectorAll('.role-card').forEach((card) => {
      const data = JSON.parse(card.getAttribute('data-role'));
      card.addEventListener('dragstart', (e) => {
        e.dataTransfer.setData('text/plain', JSON.stringify(data));
      });
      card.querySelector('.role-attach').addEventListener('click', () => {
        addAttachedRole(data);
      });
      const copyBtn = card.querySelector('.role-copy');
      copyBtn.addEventListener('click', () => {
        navigator.clipboard.writeText(`@${data.username || data.display}`).then(
          () => log('已复�?@username'),
          () => log('复制失败')
        );
      });
    });
  };

  const loadRoles = async () => {
    const baseUrl = getBaseUrl();
    try {
      const r = await fetch(`${baseUrl}/api/characters`, { headers: { ...getAuthHeaders() } });
      if (!r.ok) throw new Error('HTTP ' + r.status);
      const data = await r.json();
      roles = Array.isArray(data) ? data : [];
    } catch (e) {
      roles = [];
      log('角色卡获取失败，点击“刷新”重�?);
    }
    renderRoles();
  };

  // 事件绑定
  btnSend.addEventListener('click', handleSend);
  btnClear.addEventListener('click', () => {
    out.textContent = '已清空。\n';
    previewGrid.innerHTML = '';
  });
  btnClearDone.addEventListener('click', () => {
    tasks = tasks.filter((t) => t.status === 'running' || t.status === 'queue');
    renderTasks();
    renderPreviews();
    persistTasks();
  });
  btnClearAll.addEventListener('click', () => {
    tasks = [];
    renderTasks();
    renderPreviews();
    persistTasks();
  });
  btnCopyLog.addEventListener('click', () => {
    navigator.clipboard.writeText(out.textContent || '').then(
      () => showToast('已复制日�?),
      () => showToast('复制失败')
    );
  });
  roleSearch.addEventListener('input', renderRoles);
  btnReloadRoles.addEventListener('click', loadRoles);
  $('apiKey').addEventListener('input', saveForm);
  $('baseUrl').addEventListener('input', saveForm);
  $('model').addEventListener('change', saveForm);
  promptBox.addEventListener('input', saveForm);
  $('baseUrl').addEventListener('change', loadRoles);
  batchPromptList.addEventListener('input', saveForm);
  batchConcurrencyInput.addEventListener('change', saveForm);
  batchModeBar.querySelectorAll('input[name="batchType"]').forEach((r) =>
    r.addEventListener('change', () => setBatchType(r.value))
  );
  btnExportBatch.addEventListener('click', () => {
    const lines = batchPromptList.value.trim();
    const arr =
      lines.length === 0
        ? []
        : lines
            .split('\n')
            .map((l) => l.trim())
            .filter(Boolean)
            .map((prompt) => ({ prompt }));
    const blob = new Blob([JSON.stringify(arr, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = 'batch_prompts.json';
    a.click();
    URL.revokeObjectURL(url);
  });
  btnImportBatch.addEventListener('click', () => importBatchFile.click());
  importBatchFile.addEventListener('change', async () => {
    if (!importBatchFile.files || !importBatchFile.files.length) return;
    const file = importBatchFile.files[0];
    const text = await file.text();
    try {
      const arr = JSON.parse(text);
      if (Array.isArray(arr)) {
        batchPromptList.value = arr.map((x) => x.prompt || '').filter(Boolean).join('\n');
        setBatchType('multi_prompt');
        saveForm();
      }
    } catch (_) {
      showToast('导入失败：格式错�?);
    }
    importBatchFile.value = '';
  });

  // 初始�?  loadForm();
  loadTasksFromStorage();
  loadRolesFromStorage();
  analyzePromptHints();
  renderAttachedRoles();
  renderTasks();
  renderPreviews();
  loadRoles();

  // 浮动任务球点击滚动到任务列表
})();

