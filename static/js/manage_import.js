// Import/Export Functions - Simplified to use backend JSONBin config
const openImportModal = () => {
    $('importModal').classList.remove('hidden');
};

const closeImportModal = () => $('importModal').classList.add('hidden');

const submitImportTokens = async () => {
    const fileInput = $('importFile');

    const btn = $('importBtn');
    const btnText = $('importBtnText');
    const spinner = $('importBtnSpinner');

    const setLoading = (isLoading) => {
        if (btn) btn.disabled = isLoading;
        if (spinner) spinner.classList.toggle('hidden', !isLoading);
        if (btnText) btnText.textContent = isLoading ? '导入中...' : '导入';
    };

    try {
        setLoading(true);

        // 1. File Import
        if (fileInput && fileInput.files.length > 0) {
            const file = fileInput.files[0];
            const text = await file.text();
            let tokens;
            try {
                tokens = JSON.parse(text);
            } catch (e) {
                throw new Error('JSON 文件格式错误');
            }

            if (!Array.isArray(tokens)) throw new Error('导入的数据必须是 Token 数组');

            const mappedTokens = tokens.map(t => ({
                email: t.email || `imported_${Date.now()}_${Math.random().toString(36).substr(2, 5)}@example.com`,
                access_token: t.access_token || t.token,
                session_token: t.session_token || t.st,
                refresh_token: t.refresh_token || t.rt,
                is_active: t.is_active !== false,
                image_enabled: t.image_enabled !== false,
                video_enabled: t.video_enabled !== false,
                image_concurrency: t.image_concurrency || -1,
                video_concurrency: t.video_concurrency || -1
            })).filter(t => t.access_token);

            if (mappedTokens.length === 0) throw new Error('未找到有效的 Token 数据');

            const r = await apiRequest('/api/tokens/import', {
                method: 'POST',
                body: JSON.stringify({ tokens: mappedTokens })
            });

            if (r) {
                const d = await r.json();
                if (d.success) {
                    showToast(`文件导入成功: 新增 ${d.added}, 更新 ${d.updated}`, 'success');
                    closeImportModal();
                    refreshTokens();
                    fileInput.value = '';
                } else {
                    showToast(d.message || '导入失败', 'error');
                }
            }
        }
        // 2. Network Import (use backend JSONBin config from environment variables)
        else {
            showToast('正在从云端同步...', 'info');
            const r = await apiRequest('/api/tokens/sync/jsonbin/pull', { method: 'POST' });
            if (r) {
                const d = await r.json();
                if (d.success) {
                    showToast(`云端同步成功: 新增 ${d.added}, 更新 ${d.updated}`, 'success');
                    closeImportModal();
                    refreshTokens();
                } else {
                    showToast(d.message || '同步失败', 'error');
                }
            }
        }

    } catch (e) {
        showToast('导入失败: ' + e.message, 'error');
    } finally {
        setLoading(false);
    }
};

const exportTokens = async () => {
    try {
        showToast('正在导出 Token...', 'info');

        // 1. Get all tokens from backend
        const r = await apiRequest('/api/tokens');
        if (!r) {
            throw new Error('获取 Token 列表失败');
        }

        const data = await r.json();
        if (!data.success || !data.tokens) {
            throw new Error('获取 Token 数据失败');
        }

        // 2. Format tokens for export
        const exportData = data.tokens.map(t => ({
            email: t.email,
            access_token: t.token,
            session_token: t.st,
            refresh_token: t.rt,
            is_active: t.is_active,
            image_enabled: t.image_enabled,
            video_enabled: t.video_enabled,
            image_concurrency: t.image_concurrency,
            video_concurrency: t.video_concurrency
        }));

        // 3. Download as JSON file
        const blob = new Blob([JSON.stringify(exportData, null, 2)], { type: 'application/json' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `sora_tokens_${new Date().toISOString().split('T')[0]}.json`;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);

        showToast(`已导出 ${exportData.length} 个 Token`, 'success');

        // 4. Auto-sync to JSONBin
        try {
            showToast('正在同步到云端...', 'info');
            const syncR = await apiRequest('/api/tokens/sync/jsonbin/push', { method: 'POST' });
            if (syncR) {
                const syncData = await syncR.json();
                if (syncData.success) {
                    showToast('已同步到云端', 'success');
                } else {
                    console.warn('云端同步失败:', syncData.message);
                }
            }
        } catch (syncError) {
            console.warn('云端同步失败:', syncError);
            // 不影响导出功能，只是警告
        }

    } catch (e) {
        showToast('导出失败: ' + e.message, 'error');
    }
};
