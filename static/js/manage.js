/**
 * Sora2API Management Console Script
 * Expanded and refactored for clarity.
 */

// === Global State ===
let allTokens = [];
let quotaFlashIds = new Set();
let quotaAnimMap = new Map();
let testingTokenIds = new Set();
let rowPulseMap = new Map();
let tokenTableRenderQueued = false;
let quotaTotalFlashTs = 0;
const DAILY_QUOTA = 30;
const TEST_CONCURRENCY = 6;
const TOKEN_TEST_TIMEOUT_MS = 120000;
const QUOTA_FLASH_MS = 5200;

// Character Card State
let characterCards = [];
let characterSelectedIds = new Set();
let characterUi = { query: '', sort: 'newest', view: 'grid', modalId: null };
let charactersUiInited = false;

// Task Drawer State
let globalTasks = [];
let taskDrawerOpen = false;
let taskDrawerFilter = 'all'; // all | running | error | done
let taskDrawerSearch = '';
let lastTaskSignature = '';

// === Utility Functions ===
const $ = (id) => document.getElementById(id);

const checkAuth = () => {
    const t = localStorage.getItem('adminToken');
    if (!t) location.href = '/login';
    return t;
};

const showToast = (m, t = 'info', opts = {}) => {
    const d = document.createElement('div');
    const bc = { success: 'bg-green-600', error: 'bg-destructive', warn: 'bg-amber-500', info: 'bg-primary' };
    d.className = `fixed bottom-4 right-4 ${bc[t] || bc.info} text-white px-4 py-2.5 rounded-lg shadow-lg text-sm font-medium z-50 animate-slide-up`;
    d.textContent = m;
    document.body.appendChild(d);
    const dur = typeof opts.duration === 'number' ? opts.duration : (t === 'error' ? 2600 : 2000);
    setTimeout(() => {
        d.style.opacity = '0';
        d.style.transition = 'opacity .3s';
        setTimeout(() => d.parentNode && document.body.removeChild(d), 300)
    }, dur);
};

// Rate limited or simple confirmations
const _confirmStepStore = new Map();
const confirmStep = (key, msg, opts = {}) => {
    const k = String(key || '');
    const now = Date.now();
    const ttl = typeof opts.ttl === 'number' ? opts.ttl : 5200;
    const last = _confirmStepStore.get(k);
    if (last && now - last < ttl) {
        _confirmStepStore.delete(k);
        return true;
    }
    _confirmStepStore.set(k, now);
    const type = opts.type === 'warn' ? 'warn' : opts.type === 'error' ? 'error' : opts.type === 'success' ? 'success' : 'info';
    showToast(String(msg || '再次点击确认'), type, { duration: typeof opts.duration === 'number' ? opts.duration : Math.min(ttl, 6200) });
    setTimeout(() => { try { if (_confirmStepStore.get(k) === now) _confirmStepStore.delete(k) } catch (_) { } }, ttl + 80);
    return false;
};

const apiRequest = async (url, opts = {}) => {
    const t = checkAuth();
    if (!t) return null;
    try {
        const r = await fetch(url, {
            ...opts,
            headers: {
                ...opts.headers,
                Authorization: `Bearer ${t}`,
                'Content-Type': 'application/json'
            }
        });
        // Monkey-patch .json() to handle weird browser extension interference
        const originalJson = r.json.bind(r);
        r.json = async () => {
            const text = await r.text();
            if (!text) return null;
            try {
                return JSON.parse(text);
            } catch (e) {
                console.error("JSON Parse Error:", e, text);
                throw new Error(`Response parse failed: ${e.message}`);
            }
        };

        if (r.status === 401) {
            localStorage.removeItem('adminToken');
            location.href = '/login';
            return null;
        }
        return r;
    } catch (e) {
        console.error("Fetch Error:", e);
        showToast('网络请求失败', 'error');
        return null;
    }
};

const apiRequestTimed = async (url, opts = {}, timeoutMs = TOKEN_TEST_TIMEOUT_MS) => {
    const controller = typeof AbortController !== 'undefined' ? new AbortController() : null;
    const merged = controller ? { ...opts, signal: controller.signal } : opts;
    let timer = null;
    try {
        const p = apiRequest(url, merged);
        if (!timeoutMs || timeoutMs <= 0) return await p;
        return await Promise.race([
            p,
            new Promise((_, rej) => {
                timer = setTimeout(() => {
                    try { controller && controller.abort() } catch (_) { }
                    rej(new Error('请求超时'))
                }, timeoutMs)
            })
        ]);
    } finally {
        if (timer) clearTimeout(timer);
    }
};

// === Tab Switching ===
const switchTab = (t) => {
    const cap = n => n.charAt(0).toUpperCase() + n.slice(1);
    const tabs = ['tokens', 'settings', 'logs', 'generate', 'characters', 'videos'];

    tabs.forEach(n => {
        const active = n === t;
        const panel = $(`panel${cap(n)}`);
        const tabBtn = $(`tab${cap(n)}`);

        if (panel) {
            panel.classList.toggle('hidden', !active);
        }

        if (tabBtn) {
            tabBtn.classList.toggle('border-primary', active);
            tabBtn.classList.toggle('text-primary', active);
            tabBtn.classList.toggle('border-transparent', !active);
            tabBtn.classList.toggle('text-muted-foreground', !active);
        }
    });

    // Special handling for generate panel to be full width
    const genPanel = $('panelGenerate');
    if (genPanel) {
        genPanel.classList.toggle('full-bleed-panel', t === 'generate');
    }

    localStorage.setItem('manage_active_tab', t);

    // Auto-load data for specific tabs
    if (t === 'settings') {
        loadAdminConfig();
        loadProxyConfig();
        loadWatermarkFreeConfig();
        loadCacheConfig();
        loadGenerationTimeout();
        loadATAutoRefreshConfig();
    } else if (t === 'logs') {
        loadLogs();
    } else if (t === 'characters') {
        refreshCharacters();
    }
};

// === Token Management ===
const loadStats = async () => {
    try {
        const r = await apiRequest('/api/stats');
        if (!r) return;
        const d = await r.json();
        $('statTotal').textContent = d.total_tokens || 0;
        $('statActive').textContent = d.active_tokens || 0;
        $('statImages').textContent = (d.today_images || 0) + '/' + (d.total_images || 0);
        $('statVideos').textContent = (d.today_videos || 0) + '/' + (d.total_videos || 0);
        $('statErrors').textContent = (d.today_errors || 0) + '/' + (d.total_errors || 0);
    } catch (e) {
        console.error('加载统计失败:', e);
    }
};

const loadTokens = async () => {
    try {
        const r = await apiRequest('/api/tokens');
        if (!r) return;
        allTokens = await r.json();
        renderTokens();
    } catch (e) {
        console.error('加载Token失败:', e);
    }
};

const formatExpiry = (exp) => {
    if (!exp) return '-';
    const d = new Date(exp);
    const now = new Date();
    const diff = d - now;
    const dateStr = d.toLocaleDateString('zh-CN', { year: 'numeric', month: '2-digit', day: '2-digit' }).replace(/\//g, '-');
    const timeStr = d.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', hour12: false });

    if (diff < 0) return `<span class="text-red-600">${dateStr} ${timeStr}</span>`;
    const days = Math.floor(diff / 864e5);
    if (days < 7) return `<span class="text-orange-600">${dateStr} ${timeStr}</span>`;
    return `${dateStr} ${timeStr}`;
};

const formatPlanTypeWithTooltip = (t) => {
    const typeMap = { 'chatgpt_team': 'Team', 'chatgpt_plus': 'Plus', 'chatgpt_pro': 'Pro', 'chatgpt_free': 'Free' };
    const label = typeMap[t.plan_type] || t.plan_type || '-';
    const tooltipText = t.subscription_end ? `套餐到期: ${new Date(t.subscription_end).toLocaleDateString()}` : '';
    return `<span class="inline-flex items-center rounded px-2 py-0.5 text-xs bg-blue-50 text-blue-700 cursor-pointer" title="${tooltipText || t.plan_title || '-'}">${label}</span>`;
};

const formatSora2 = (t) => {
    if (t.sora2_supported === true) {
        const remaining = t.sora2_total_count - t.sora2_redeemed_count;
        const tooltip = `邀请码: ${t.sora2_invite_code || '无'}\n可用: ${remaining}/${t.sora2_total_count}\n已用: ${t.sora2_redeemed_count}`;
        return `<div class="inline-flex items-center gap-1"><span class="inline-flex items-center rounded px-2 py-0.5 text-xs bg-green-50 text-green-700 cursor-pointer" title="${tooltip}" onclick="copySora2Code('${t.sora2_invite_code || ''}')">支持</span><span class="text-xs text-muted-foreground" title="${tooltip}">${remaining}/${t.sora2_total_count}</span></div>`;
    } else if (t.sora2_supported === false) {
        return `<span class="inline-flex items-center rounded px-2 py-0.5 text-xs bg-gray-100 text-gray-700 cursor-pointer" title="点击使用邀请码激活" onclick="openSora2Modal(${t.id})">不支持</span>`;
    } else {
        return '-';
    }
};

const formatSora2Remaining = (t) => {
    if (t.sora2_supported === true && typeof t.sora2_remaining_count === 'number') {
        const remaining = Math.max(0, t.sora2_remaining_count);
        return `<span class="text-xs inline-block" title="来源：测试接口返回的真实剩余次数">${remaining}/${DAILY_QUOTA}</span>`;
    }
    const used = (t.image_count || 0) + (t.video_count || 0);
    const remaining = Math.max(0, DAILY_QUOTA - used);
    return `<span class="text-xs inline-block" title="来源：本地统计估算">${remaining}/${DAILY_QUOTA}</span>`;
};

const formatClientId = (clientId) => {
    if (!clientId) return '-';
    const short = clientId.substring(0, 8) + '...';
    return `<span class="text-xs font-mono cursor-pointer hover:text-primary" title="${clientId}" onclick="navigator.clipboard.writeText('${clientId}').then(()=>showToast('已复制','success'))">${short}</span>`;
};

const renderTokens = () => {
    const tb = $('tokenTableBody');
    if (!tb) return;
    tb.innerHTML = allTokens.map(t => {
        const tokenId = Number(t && t.id);
        const isTesting = testingTokenIds.has(tokenId);
        const testingAttr = isTesting ? ' data-testing="1" aria-busy="true"' : '';
        const pulse = rowPulseMap.get(tokenId);
        const pulseAttr = pulse ? ` data-pulse="${pulse}"` : '';
        const imageDisplay = t.image_enabled ? `${t.image_count || 0}` : '-';
        const videoDisplay = (t.video_enabled && t.sora2_supported) ? `${t.video_count || 0}` : '-';
        const testLabel = isTesting ? '测试中' : '测试';
        const testCls = isTesting ? 'opacity-60 pointer-events-none' : '';
        const quotaLoading = isTesting ? `<div class="quota-loading" aria-hidden="true"><span class="quota-loading-pill">测试中</span><span class="quota-loading-dots"></span></div>` : '';

        return `
            <tr data-token-id="${t.id}"${testingAttr}${pulseAttr}>
                <td class="py-2.5 px-3">${t.email}</td>
                <td class="py-2.5 px-3">
                    <span class="inline-flex items-center rounded px-2 py-0.5 text-xs ${t.is_active ? 'bg-green-50 text-green-700' : 'bg-gray-100 text-gray-700'}">${t.is_active ? '活跃' : '禁用'}</span>
                </td>
                <td class="py-2.5 px-3">${formatClientId(t.client_id)}</td>
                <td class="py-2.5 px-3 text-xs">${formatExpiry(t.expiry_time)}</td>
                <td class="py-2.5 px-3 text-xs">${formatPlanTypeWithTooltip(t)}</td>
                <td class="py-2.5 px-3 text-xs">${formatSora2(t)}</td>
                <td class="py-2.5 px-3 quota-cell" data-col="quota" data-token-id="${t.id}"${isTesting ? ' data-testing="1"' : ''}>
                    ${formatSora2Remaining(t)}
                    ${quotaLoading}
                </td>
                <td class="py-2.5 px-3">${imageDisplay}</td>
                <td class="py-2.5 px-3">${videoDisplay}</td>
                <td class="py-2.5 px-3">${t.error_count || 0}</td>
                <td class="py-2.5 px-3 text-xs text-muted-foreground">${t.remark || '-'}</td>
                <td class="py-2.5 px-3 text-right">
                    <button data-action="test" onclick="testToken(${t.id})" class="inline-flex items-center justify-center rounded-md hover:bg-blue-50 hover:text-blue-700 h-7 px-2 text-xs mr-1 ${testCls}">${testLabel}</button>
                    <button onclick="openEditModal(${t.id})" class="inline-flex items-center justify-center rounded-md hover:bg-green-50 hover:text-green-700 h-7 px-2 text-xs mr-1">编辑</button>
                    <button onclick="toggleToken(${t.id},${t.is_active})" class="inline-flex items-center justify-center rounded-md hover:bg-accent h-7 px-2 text-xs mr-1">${t.is_active ? '禁用' : '启用'}</button>
                    <button onclick="deleteToken(${t.id})" class="inline-flex items-center justify-center rounded-md hover:bg-destructive/10 hover:text-destructive h-7 px-2 text-xs">删除</button>
                </td>
            </tr>
        `;
    }).join('');
};

const refreshTokens = async () => {
    await loadTokens();
    await loadStats();
    updateQuotaStats();
};

const updateQuotaStats = () => {
    const total = DAILY_QUOTA * allTokens.length;
    const remaining = allTokens.reduce((s, t) => {
        if (t && t.sora2_supported === true && typeof t.sora2_remaining_count === 'number')
            return s + Math.max(0, t.sora2_remaining_count);
        const used = (t.image_count || 0) + (t.video_count || 0);
        return s + Math.max(0, DAILY_QUOTA - used)
    }, 0);
    const el = $('statQuota');
    if (!el) return;
    el.textContent = allTokens.length ? `${remaining} / ${total}` : '-';
};

// === Video Sync Feature (NEW) ===
const syncLatestVideo = async () => {
    const btn = $('btnSyncVideo');
    const btnText = $('btnSyncText');
    const spinner = $('btnSyncSpinner');
    const logEl = $('syncLog');
    const limitInput = $('syncLimit');
    const limit = limitInput ? (parseInt(limitInput.value) || 1) : 1;

    // Reset UI
    if (btn) btn.disabled = true;
    if (btnText) btnText.textContent = '同步中...';
    if (spinner) spinner.classList.remove('hidden');
    if (logEl) {
        logEl.textContent = '🚀 开始请求同步...\\n';
        logEl.className = "text-xs font-mono whitespace-pre-wrap text-green-400 bg-black p-3 rounded border border-gray-700 h-64 overflow-y-auto";
    }

    try {
        // Get API Key first (required for /v1/ endpoints)
        let apiKey = $('cfgCurrentAPIKey') ? $('cfgCurrentAPIKey').value : '';
        if (!apiKey) {
            // Try to fetch it if not in DOM
            try {
                const r = await apiRequest('/api/admin/config');
                if (r) {
                    const d = await r.json();
                    apiKey = d.api_key;
                    // Update DOM if exists
                    if ($('cfgCurrentAPIKey')) $('cfgCurrentAPIKey').value = apiKey;
                }
            } catch (e) {
                console.error('Failed to fetch API key for sync:', e);
            }
        }

        if (!apiKey) {
            throw new Error("无法获取 API Key，请检查系统配置");
        }

        const response = await fetch('/v1/videos/sync', {
            method: 'POST',
            headers: {
                'Authorization': `Bearer ${apiKey}`,
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                limit: limit,
                stream: true,
                force_upload: true
            })
        });

        if (!response.ok) {
            throw new Error(`HTTP error! status: ${response.status}`);
        }

        const reader = response.body.getReader();
        const decoder = new TextDecoder();

        while (true) {
            const { done, value } = await reader.read();
            if (done) break;

            const chunk = decoder.decode(value);
            const lines = chunk.split('\\n');

            for (const line of lines) {
                if (line.startsWith('data: ')) {
                    const jsonStr = line.slice(6).trim();
                    if (jsonStr === '[DONE]') continue;
                    if (!jsonStr) continue;

                    try {
                        const data = JSON.parse(jsonStr);
                        const delta = data.choices?.[0]?.delta || {};

                        if (delta.reasoning_content) {
                            if (logEl) {
                                logEl.textContent += delta.reasoning_content;
                                logEl.scrollTop = logEl.scrollHeight;
                            }
                        }
                        if (delta.content) {
                            // If it's the final video link, just append it
                            if (logEl) {
                                logEl.textContent += '\\n' + delta.content + '\\n';
                                logEl.scrollTop = logEl.scrollHeight;
                            }
                        }
                    } catch (e) {
                        // ignore malformed lines
                    }
                }
            }
        }

        if (logEl) logEl.textContent += '\\n✅ 同步流程结束';

    } catch (e) {
        if (logEl) logEl.textContent += `\\n❌ 发生错误: ${e.message}`;
    } finally {
        if (btn) btn.disabled = false;
        if (btnText) btnText.textContent = '开始同步';
        if (spinner) spinner.classList.add('hidden');
    }
};


// === Settings Loading/Saving ===
const loadAdminConfig = async () => {
    try {
        const r = await apiRequest('/api/admin/config');
        if (!r) return;
        const d = await r.json();
        if ($('cfgErrorBan')) $('cfgErrorBan').value = d.error_ban_threshold || 3;
        if ($('cfgAdminUsername')) $('cfgAdminUsername').value = d.admin_username || 'admin';
        if ($('cfgCurrentAPIKey')) $('cfgCurrentAPIKey').value = d.api_key || '';
        if ($('cfgDebugEnabled')) $('cfgDebugEnabled').checked = d.debug_enabled || false;
    } catch (e) { console.error('加载配置失败:', e); }
};

// ... (Other config loaders: Proxy, Watermark, Cache, Generation, TokenRefresh) ...
const loadProxyConfig = async () => {
    try {
        const r = await apiRequest('/api/proxy/config');
        if (r) {
            const d = await r.json();
            if ($('cfgProxyEnabled')) $('cfgProxyEnabled').checked = d.proxy_enabled || false;
            if ($('cfgProxyUrl')) $('cfgProxyUrl').value = d.proxy_url || '';
        }
    } catch (e) { }
};

const loadWatermarkFreeConfig = async () => {
    try {
        const r = await apiRequest('/api/watermark-free/config');
        if (r) {
            const d = await r.json();
            if ($('cfgWatermarkFreeEnabled')) $('cfgWatermarkFreeEnabled').checked = d.watermark_free_enabled || false;
            if ($('cfgParseMethod')) $('cfgParseMethod').value = d.parse_method || 'third_party';
            if ($('cfgCustomParseUrl')) $('cfgCustomParseUrl').value = d.custom_parse_url || '';
            if ($('cfgCustomParseToken')) $('cfgCustomParseToken').value = d.custom_parse_token || '';
            toggleWatermarkFreeOptions();
            toggleCustomParseOptions();
        }
    } catch (e) { }
};

const loadCacheConfig = async () => {
    try {
        const r = await apiRequest('/api/cache/config');
        if (r) {
            const d = await r.json();
            if (d.success && d.config) {
                if ($('cfgCacheEnabled')) $('cfgCacheEnabled').checked = d.config.enabled !== false;
                if ($('cfgCacheTimeout')) $('cfgCacheTimeout').value = d.config.timeout || 7200;
                if ($('cfgCacheBaseUrl')) $('cfgCacheBaseUrl').value = d.config.base_url || '';
                toggleCacheOptions();
            }
        }
    } catch (e) { }
};
const loadGenerationTimeout = async () => {
    try {
        const r = await apiRequest('/api/generation/timeout');
        if (r) {
            const d = await r.json();
            if (d.success && d.config) {
                if ($('cfgImageTimeout')) $('cfgImageTimeout').value = d.config.image_timeout || 300;
                if ($('cfgVideoTimeout')) $('cfgVideoTimeout').value = d.config.video_timeout || 1500;
            }
        }
    } catch (e) { }
};
const loadATAutoRefreshConfig = async () => {
    try {
        const r = await apiRequest('/api/token-refresh/config');
        if (r) {
            const d = await r.json();
            if (d.success && d.config) {
                if ($('atAutoRefreshToggle')) $('atAutoRefreshToggle').checked = d.config.at_auto_refresh_enabled || false;
            }
        }
    } catch (e) { }
};

// === UI Toggles ===
const toggleWatermarkFreeOptions = () => {
    const enabled = $('cfgWatermarkFreeEnabled')?.checked;
    const opts = $('watermarkFreeOptions');
    if (opts) opts.style.display = enabled ? 'block' : 'none';
};
const toggleCustomParseOptions = () => {
    const method = $('cfgParseMethod')?.value;
    const opts = $('customParseOptions');
    if (opts) opts.style.display = method === 'custom' ? 'block' : 'none';
};
const toggleCacheOptions = () => {
    const enabled = $('cfgCacheEnabled')?.checked;
    const opts = $('cacheOptions');
    if (opts) opts.style.display = enabled ? 'block' : 'none';
};

// === Initialization ===
window.addEventListener('DOMContentLoaded', () => {
    checkAuth();
    // Load last active tab
    const savedTab = localStorage.getItem('manage_active_tab');
    const initialTab = savedTab || 'tokens';
    switchTab(initialTab);

    // Initial data load
    if (initialTab === 'tokens') refreshTokens();

    // Add event listeners for new buttons if they weren't caught by inline onclick
    const syncBtn = $('btnSyncVideo');
    if (syncBtn) {
        // Remove old listeners if any (clone node trick) or just rely on onclick attribute
    }
});

// === Dummy Implementations for missing functions to prevent crash ===
// These should be fully implemented based on previous manage.js content if needed
const logout = () => {
    if (!confirmStep('logout', '再次点击确认退出登录', { ttl: 4200, type: 'warn' })) return;
    localStorage.removeItem('adminToken');
    location.href = '/login';
};

const copySora2Code = async (code) => {
    if (!code) { showToast('没有可复制的邀请码', 'error'); return }
    try {
        await navigator.clipboard.writeText(code);
        showToast(`邀请码已复制: ${code}`, 'success');
    } catch (e) {
        showToast('复制失败', 'error');
    }
};

const openSora2Modal = (id) => {
    $('sora2TokenId').value = id;
    $('sora2InviteCode').value = '';
    $('sora2Modal').classList.remove('hidden');
};

const closeSora2Modal = () => $('sora2Modal').classList.add('hidden');

const deleteToken = async (id, skipConfirm = false) => {
    if (!skipConfirm && !confirmStep('delete_token_' + id, `再次点击确认删除 Token（ID: ${id}）`, { ttl: 5200, type: 'warn' })) return;
    try {
        const r = await apiRequest(`/api/tokens/${id}`, { method: 'DELETE' });
        if (!r) return;
        const d = await r.json();
        if (d.success) {
            await refreshTokens();
            if (!skipConfirm) showToast('删除成功', 'success');
            return true;
        } else {
            if (!skipConfirm) showToast('删除失败', 'error');
            return false;
        }
    } catch (e) {
        if (!skipConfirm) showToast('删除失败: ' + e.message, 'error');
        return false;
    }
};

const testToken = async (id) => {
    const tokenId = Number(id);
    if (Number.isFinite(tokenId) && testingTokenIds.has(tokenId)) {
        showToast('该账号正在测试中，请稍候…', 'info');
        return;
    }
    const row = document.querySelector(`#tokenTableBody tr[data-token-id="${tokenId}"]`);
    if (row) row.dataset.testing = '1';

    testingTokenIds.add(tokenId);
    renderTokens(); // Re-render to show loading state properly

    try {
        showToast('正在测试Token...', 'info');
        const r = await apiRequestTimed(`/api/tokens/${tokenId}/test`, { method: 'POST' });
        if (!r) return;
        const d = await r.json();
        if (d && d.success && d.status === 'success') {
            // Update local data
            const idx = allTokens.findIndex(t => t.id === tokenId);
            if (idx >= 0) {
                // Simplistic merge for display update
                if (d.email) allTokens[idx].email = d.email;
            }
            showToast('Token有效！', 'success');
        } else {
            showToast(`Token无效: ${(d && d.message) || '未知错误'}`, 'error');
        }
    } catch (e) {
        showToast('测试失败: ' + e.message, 'error');
    } finally {
        testingTokenIds.delete(tokenId);
        if (row) delete row.dataset.testing;
        renderTokens();
    }
};

const openEditModal = (id) => {
    const token = allTokens.find(t => t.id === id);
    if (!token) return showToast('Token不存在', 'error');
    $('editTokenId').value = token.id;
    $('editTokenAT').value = token.token || '';
    $('editTokenST').value = token.st || '';
    $('editTokenRT').value = token.rt || '';
    $('editTokenClientId').value = token.client_id || '';
    $('editTokenRemark').value = token.remark || '';
    $('editTokenImageEnabled').checked = token.image_enabled !== false;
    $('editTokenVideoEnabled').checked = token.video_enabled !== false;
    $('editTokenImageConcurrency').value = token.image_concurrency || '-1';
    $('editTokenVideoConcurrency').value = token.video_concurrency || '-1';
    $('editModal').classList.remove('hidden');
};

const toggleToken = async (id, isActive) => {
    const action = isActive ? 'disable' : 'enable';
    try {
        const r = await apiRequest(`/api/tokens/${id}/${action}`, { method: 'POST' });
        if (r) {
            const d = await r.json();
            if (d.success) {
                await refreshTokens();
                showToast(isActive ? 'Token已禁用' : 'Token已启用', 'success');
            } else {
                showToast('操作失败', 'error');
            }
        }
    } catch (e) {
        showToast('操作失败: ' + e.message, 'error');
    }
};

const openAddModal = () => $('addModal').classList.remove('hidden');
const closeAddModal = () => $('addModal').classList.add('hidden');
const closeEditModal = () => $('editModal').classList.add('hidden');


const refreshLogs = async () => { await loadLogs(); };
const loadLogs = async () => {
    try {
        const r = await apiRequest('/api/logs?limit=100');
        if (!r) return;
        const logs = await r.json();
        const tb = $('logsTableBody');
        tb.innerHTML = logs.map(l => `<tr><td class="py-2.5 px-3">${l.operation}</td><td class="py-2.5 px-3"><span class="text-xs ${l.token_email ? 'text-blue-600' : 'text-muted-foreground'}">${l.token_email || '未知'}</span></td><td class="py-2.5 px-3"><span class="inline-flex items-center rounded px-2 py-0.5 text-xs ${l.status_code === 200 ? 'bg-green-50 text-green-700' : 'bg-red-50 text-red-700'}">${l.status_code}</span></td><td class="py-2.5 px-3">${l.duration.toFixed(2)}</td><td class="py-2.5 px-3 text-xs text-muted-foreground">${l.created_at ? new Date(l.created_at).toLocaleString('zh-CN') : '-'}</td></tr>`).join('');
    } catch (e) { console.error('加载日志失败:', e); }
};

const refreshCharacters = () => { /* Stub for char refresh */ };
const initCharactersUi = () => { };
const manualATAutoRefresh = () => { };
const submitAddToken = async () => {
    const at = $('addTokenAT').value.trim();
    if (!at) return showToast('请输入 Access Token', 'warn');

    const data = {
        token: at,
        st: $('addTokenST').value.trim(),
        rt: $('addTokenRT').value.trim(),
        client_id: $('addTokenClientId').value.trim(),
        remark: $('addTokenRemark').value.trim(),
        image_enabled: $('addTokenImageEnabled').checked,
        video_enabled: $('addTokenVideoEnabled').checked,
        image_concurrency: parseInt($('addTokenImageConcurrency').value) || -1,
        video_concurrency: parseInt($('addTokenVideoConcurrency').value) || -1
    };

    const btn = $('addTokenBtn');
    const btnText = $('addTokenBtnText');
    const spinner = $('addTokenBtnSpinner');

    if (btn) btn.disabled = true;
    if (btnText) btnText.textContent = '添加中...';
    if (spinner) spinner.classList.remove('hidden');

    try {
        const r = await apiRequest('/api/tokens', {
            method: 'POST',
            body: JSON.stringify(data)
        });

        if (r) {
            const d = await r.json();
            if (d.success) {
                showToast('添加成功', 'success');
                closeAddModal();
                refreshTokens();
                // Clear inputs
                $('addTokenAT').value = '';
                $('addTokenST').value = '';
                $('addTokenRT').value = '';
                $('addTokenClientId').value = '';
                $('addTokenRemark').value = '';
                if ($('addRTRefreshHint')) $('addRTRefreshHint').classList.add('hidden');
            } else {
                showToast(d.message || '添加失败', 'error');
            }
        }
    } catch (e) {
        showToast('添加失败: ' + e.message, 'error');
    } finally {
        if (btn) btn.disabled = false;
        if (btnText) btnText.textContent = '添加';
        if (spinner) spinner.classList.add('hidden');
    }
};

const submitEditToken = async () => {
    const id = $('editTokenId').value;
    const at = $('editTokenAT').value.trim();
    if (!at) return showToast('请输入 Access Token', 'warn');

    const data = {
        token: at,
        st: $('editTokenST').value.trim(),
        rt: $('editTokenRT').value.trim(),
        client_id: $('editTokenClientId').value.trim(),
        remark: $('editTokenRemark').value.trim(),
        image_enabled: $('editTokenImageEnabled').checked,
        video_enabled: $('editTokenVideoEnabled').checked,
        image_concurrency: parseInt($('editTokenImageConcurrency').value) || -1,
        video_concurrency: parseInt($('editTokenVideoConcurrency').value) || -1
    };

    const btn = $('editTokenBtn');
    const btnText = $('editTokenBtnText');
    const spinner = $('editTokenBtnSpinner');

    if (btn) btn.disabled = true;
    if (btnText) btnText.textContent = '保存中...';
    if (spinner) spinner.classList.remove('hidden');

    try {
        const r = await apiRequest(`/api/tokens/${id}`, {
            method: 'PUT',
            body: JSON.stringify(data)
        });

        if (r) {
            const d = await r.json();
            if (d.success) {
                showToast('保存成功', 'success');
                closeEditModal();
                refreshTokens();
            } else {
                showToast(d.message || '保存失败', 'error');
            }
        }
    } catch (e) {
        showToast('保存失败: ' + e.message, 'error');
    } finally {
        if (btn) btn.disabled = false;
        if (btnText) btnText.textContent = '保存';
        if (spinner) spinner.classList.add('hidden');
    }
};

const convertST2AT = async () => {
    const st = $('addTokenST').value.trim();
    if (!st) return showToast('请先输入 Session Token', 'warn');

    const btn = event.target.closest('button');
    const originalText = btn.textContent;
    btn.disabled = true;
    btn.textContent = '转换中...';

    try {
        const r = await apiRequest('/api/tokens/st2at', {
            method: 'POST',
            body: JSON.stringify({ st })
        });

        if (r) {
            const d = await r.json();
            if (d.success) {
                $('addTokenAT').value = d.access_token;
                showToast('转换成功', 'success');
            } else {
                showToast(d.message || '转换失败', 'error');
            }
        }
    } catch (e) {
        showToast('转换失败: ' + e.message, 'error');
    } finally {
        btn.disabled = false;
        btn.textContent = originalText;
    }
};

const convertRT2AT = async () => {
    const rt = $('addTokenRT').value.trim();
    if (!rt) return showToast('请先输入 Refresh Token', 'warn');

    const btn = event.target.closest('button');
    const originalText = btn.textContent;
    btn.disabled = true;
    btn.textContent = '转换中...';

    try {
        const r = await apiRequest('/api/tokens/rt2at', {
            method: 'POST',
            body: JSON.stringify({ rt })
        });

        if (r) {
            const d = await r.json();
            if (d.success) {
                $('addTokenAT').value = d.access_token;
                if (d.refresh_token) {
                    $('addTokenRT').value = d.refresh_token;
                    if ($('addRTRefreshHint')) $('addRTRefreshHint').classList.remove('hidden');
                }
                showToast('转换成功', 'success');
            } else {
                showToast(d.message || '转换失败', 'error');
            }
        }
    } catch (e) {
        showToast('转换失败: ' + e.message, 'error');
    } finally {
        btn.disabled = false;
        btn.textContent = originalText;
    }
};

const convertEditST2AT = async () => {
    const st = $('editTokenST').value.trim();
    if (!st) return showToast('请先输入 Session Token', 'warn');

    const btn = event.target.closest('button');
    const originalText = btn.textContent;
    btn.disabled = true;
    btn.textContent = '转换中...';

    try {
        const r = await apiRequest('/api/tokens/st2at', {
            method: 'POST',
            body: JSON.stringify({ st })
        });

        if (r) {
            const d = await r.json();
            if (d.success) {
                $('editTokenAT').value = d.access_token;
                showToast('转换成功', 'success');
            } else {
                showToast(d.message || '转换失败', 'error');
            }
        }
    } catch (e) {
        showToast('转换失败: ' + e.message, 'error');
    } finally {
        btn.disabled = false;
        btn.textContent = originalText;
    }
};

const convertEditRT2AT = async () => {
    const rt = $('editTokenRT').value.trim();
    if (!rt) return showToast('请先输入 Refresh Token', 'warn');

    const btn = event.target.closest('button');
    const originalText = btn.textContent;
    btn.disabled = true;
    btn.textContent = '转换中...';

    try {
        const r = await apiRequest('/api/tokens/rt2at', {
            method: 'POST',
            body: JSON.stringify({ rt })
        });

        if (r) {
            const d = await r.json();
            if (d.success) {
                $('editTokenAT').value = d.access_token;
                if (d.refresh_token) {
                    $('editTokenRT').value = d.refresh_token;
                    if ($('editRTRefreshHint')) $('editRTRefreshHint').classList.remove('hidden');
                }
                showToast('转换成功', 'success');
            } else {
                showToast(d.message || '转换失败', 'error');
            }
        }
    } catch (e) {
        showToast('转换失败: ' + e.message, 'error');
    } finally {
        btn.disabled = false;
        btn.textContent = originalText;
    }
};
const exportTokens = () => { };
const openImportModal = () => {
    $('importModal').classList.remove('hidden');
    // Load saved JSONBin settings
    const savedId = localStorage.getItem('sora2_jsonbin_id');
    const savedKey = localStorage.getItem('sora2_jsonbin_key');
    if (savedId) $('importJsonBinId').value = savedId;
    if (savedKey) $('importJsonBinKey').value = savedKey;
};

const closeImportModal = () => $('importModal').classList.add('hidden');

const submitImportTokens = async () => {
    const fileInput = $('importFile');
    const binIdInput = $('importJsonBinId');
    const binKeyInput = $('importJsonBinKey');
    const mergeMode = $('importJsonBinMerge').checked; // Currently backend always appends/updates, so this is just UI for now or we can pass it if backend supported strict replace (backend is append/update by default)

    let tokens = null;

    const btn = $('importBtn');
    const btnText = $('importBtnText');
    const spinner = $('importBtnSpinner');

    // Helper to set loading state
    const setLoading = (isLoading) => {
        if (btn) btn.disabled = isLoading;
        if (spinner) spinner.classList.toggle('hidden', !isLoading);
        if (btnText) btnText.textContent = isLoading ? '导入中...' : '导入';
    };

    try {
        setLoading(true);

        // 1. File Import
        if (fileInput.files.length > 0) {
            const file = fileInput.files[0];
            const text = await file.text();
            try {
                tokens = JSON.parse(text);
            } catch (e) {
                throw new Error('JSON 文件格式错误');
            }
        }
        // 2. JSONBin Import
        else if (binIdInput.value.trim()) {
            let binId = binIdInput.value.trim();
            const binKey = binKeyInput.value.trim();

            // Save to localStorage
            localStorage.setItem('sora2_jsonbin_id', binId);
            localStorage.setItem('sora2_jsonbin_key', binKey);

            // Extract ID if full URL is given
            // Support https://api.jsonbin.io/v3/b/<ID> or https://jsonbin.io/b/<ID>
            const urlMatch = binId.match(/\/b\/([a-zA-Z0-9]+)/);
            if (urlMatch) {
                binId = urlMatch[1];
            }

            const url = `https://api.jsonbin.io/v3/b/${binId}?meta=false`;
            const headers = {};
            if (binKey) {
                headers['X-Master-Key'] = binKey;
                headers['X-Access-Key'] = binKey; // Try both or just Master
            }

            showToast('正在从 JSONBin 获取数据...', 'info');
            const res = await fetch(url, { headers });

            if (!res.ok) {
                if (res.status === 401) throw new Error('JSONBin 访问被拒绝 (401)，请检查 Key');
                if (res.status === 404) throw new Error('JSONBin ID 未找到 (404)');
                throw new Error(`JSONBin 请求失败: ${res.status}`);
            }

            tokens = await res.json();

            // JSONBin v3 with meta=false returns the data directly. 
            // If it was wrapped in record (shouldn't be with meta=false but just in case)
            if (tokens.record && Array.isArray(tokens.record)) {
                tokens = tokens.record;
            }
        } else {
            throw new Error('请选择文件或输入 JSONBin ID');
        }

        if (!Array.isArray(tokens)) {
            throw new Error('导入的数据必须是 Token 数组');
        }

        // 3. Send to Backend
        // Transform data to match ImportTokenItem if necessary
        // The backend expects: email, access_token, etc.
        // We assume the JSON format matches or we map it.
        // Let's try to map common fields just in case
        const mappedTokens = tokens.map(t => ({
            email: t.email || `imported_${Date.now()}_${Math.random().toString(36).substr(2, 5)}@example.com`,
            access_token: t.access_token || t.token, // Support both
            session_token: t.session_token || t.st,
            refresh_token: t.refresh_token || t.rt,
            is_active: t.is_active !== false,
            image_enabled: t.image_enabled !== false,
            video_enabled: t.video_enabled !== false,
            image_concurrency: t.image_concurrency || -1,
            video_concurrency: t.video_concurrency || -1
        })).filter(t => t.access_token); // Filter out invalid ones

        if (mappedTokens.length === 0) {
            throw new Error('未找到有效的 Token 数据 (需包含 access_token)');
        }

        const r = await apiRequest('/api/tokens/import', {
            method: 'POST',
            body: JSON.stringify({ tokens: mappedTokens })
        });

        if (r) {
            const d = await r.json();
            if (d.success) {
                showToast(`导入成功: 新增 ${d.added}, 更新 ${d.updated}`, 'success');
                closeImportModal();
                refreshTokens();
                // Clear file input
                fileInput.value = '';
            } else {
                showToast(d.message || '导入失败', 'error');
            }
        }

    } catch (e) {
        showToast('导入失败: ' + e.message, 'error');
    } finally {
        setLoading(false);
    }
};
const submitSora2Activate = async () => { /* Stub */ };
const saveAdminConfig = async () => {
    try {
        const r = await apiRequest('/api/admin/config', {
            method: 'POST',
            body: JSON.stringify({ error_ban_threshold: parseInt($('cfgErrorBan').value) || 3 })
        });
        if (r) showToast('配置保存成功', 'success');
    } catch (e) { showToast('保存失败', 'error'); }
};
const updateAdminPassword = async () => { };
const updateAPIKey = async () => { };
const toggleDebugMode = async () => { };
const saveProxyConfig = async () => {
    try {
        const r = await apiRequest('/api/proxy/config', { method: 'POST', body: JSON.stringify({ proxy_enabled: $('cfgProxyEnabled').checked, proxy_url: $('cfgProxyUrl').value.trim() }) });
        if (r) showToast('代理配置保存成功', 'success');
    } catch (e) { showToast('保存失败', 'error') }
};
const saveWatermarkFreeConfig = async () => {
    try {
        const r = await apiRequest('/api/watermark-free/config', {
            method: 'POST', body: JSON.stringify({
                watermark_free_enabled: $('cfgWatermarkFreeEnabled').checked,
                parse_method: $('cfgParseMethod').value,
                custom_parse_url: $('cfgCustomParseUrl').value,
                custom_parse_token: $('cfgCustomParseToken').value
            })
        });
        if (r) showToast('配置保存成功', 'success');
    } catch (e) { showToast('保存失败', 'error') }
};
const saveCacheConfig = async () => { /* Stub */ };
const saveGenerationTimeout = async () => { /* Stub */ };
const toggleATAutoRefresh = async () => { /* Stub */ };
