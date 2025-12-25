
        // ... (Previous existing code)
        let allTokens=[];
        // ...
        
        // 新增：视频同步逻辑
        const syncLatestVideo = async () => {
            const btn = $('btnSyncVideo');
            const btnText = $('btnSyncText');
            const btnSpinner = $('btnSyncSpinner');
            const logEl = $('syncLog');
            const limit = parseInt($('syncLimit').value) || 1;

            if (btn) btn.disabled = true;
            if (btnText) btnText.textContent = '同步中...';
            if (btnSpinner) btnSpinner.classList.remove('hidden');
            if (logEl) logEl.textContent = '开始请求同步...\n';

            try {
                const token = checkAuth();
                if (!token) return;

                const response = await fetch('/v1/videos/sync', {
                    method: 'POST',
                    headers: {
                        'Authorization': `Bearer ${token}`,
                        'Content-Type': 'application/json'
                    },
                    body: JSON.stringify({
                        limit: limit,
                        stream: true
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
                    const lines = chunk.split('\n');
                    
                    for (const line of lines) {
                        if (line.startsWith('data: ')) {
                            const jsonStr = line.slice(6);
                            if (jsonStr === '[DONE]') continue;
                            
                            try {
                                const data = JSON.parse(jsonStr);
                                const delta = data.choices?.[0]?.delta || {};
                                
                                if (delta.reasoning_content) {
                                    logEl.textContent += delta.reasoning_content;
                                    logEl.scrollTop = logEl.scrollHeight;
                                }
                                if (delta.content) {
                                    logEl.textContent += '\n' + delta.content + '\n';
                                    logEl.scrollTop = logEl.scrollHeight;
                                }
                            } catch (e) {
                                console.error('Parse error', e);
                            }
                        }
                    }
                }
                
                logEl.textContent += '\n✅ 同步流程结束';

            } catch (e) {
                if (logEl) logEl.textContent += `\n❌ 发生错误: ${e.message}`;
            } finally {
                if (btn) btn.disabled = false;
                if (btnText) btnText.textContent = '开始同步';
                if (btnSpinner) btnSpinner.classList.add('hidden');
            }
        };


        // Update switchTab to handle 'videos'
        switchTab=t=>{const cap=n=>n.charAt(0).toUpperCase()+n.slice(1);['tokens','settings','logs','generate','characters', 'videos'].forEach(n=>{const active=n===t;$(`panel${cap(n)}`).classList.toggle('hidden',!active);$(`tab${cap(n)}`).classList.toggle('border-primary',active);$(`tab${cap(n)}`).classList.toggle('text-primary',active);$(`tab${cap(n)}`).classList.toggle('border-transparent',!active);$(`tab${cap(n)}`).classList.toggle('text-muted-foreground',!active)});const genPanel=$('panelGenerate');if(genPanel){genPanel.classList.toggle('full-bleed-panel',t==='generate');}localStorage.setItem('manage_active_tab',t);if(t==='settings'){loadAdminConfig();loadProxyConfig();loadWatermarkFreeConfig();loadCacheConfig();loadGenerationTimeout();loadATAutoRefreshConfig()}else if(t==='logs'){loadLogs()}else if(t==='characters'){refreshCharacters()}};
        
        // ... (Rest of the existing code)
