// JSONBin Sync Functions
const syncToCloud = async () => {
    if (!confirm('确定要将当前所有 Token 推送到云端 (JSONBin) 吗？这将覆盖云端现有数据。')) return;

    try {
        showToast('正在推送到云端...', 'info');
        const r = await apiRequest('/api/tokens/sync/jsonbin/push', { method: 'POST' });
        if (r) {
            const d = await r.json();
            if (d.success) {
                showToast('推送成功', 'success');
            } else {
                showToast(d.message || '推送失败', 'error');
            }
        }
    } catch (e) {
        showToast('推送失败: ' + e.message, 'error');
    }
};

const syncFromCloud = async () => {
    if (!confirm('确定要从云端 (JSONBin) 同步 Token 吗？这将合并云端数据到本地。')) return;

    try {
        showToast('正在从云端同步...', 'info');
        const r = await apiRequest('/api/tokens/sync/jsonbin/pull', { method: 'POST' });
        if (r) {
            const d = await r.json();
            if (d.success) {
                showToast(`云端同步成功: 新增 ${d.added}, 更新 ${d.updated}`, 'success');
                refreshTokens();
            } else {
                showToast(d.message || '同步失败', 'error');
            }
        }
    } catch (e) {
        showToast('同步失败: ' + e.message, 'error');
    }
};
