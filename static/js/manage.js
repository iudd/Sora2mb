
        let allTokens=[];
        let quotaFlashIds=new Set();
        let quotaAnimMap=new Map();
        let testingTokenIds=new Set();
        let rowPulseMap=new Map();
        let tokenTableRenderQueued=false;
        let quotaTotalFlashTs=0;
        const DAILY_QUOTA=30;
        const TEST_CONCURRENCY=6;
        const TOKEN_TEST_TIMEOUT_MS=120000;
        const QUOTA_FLASH_MS=5200;
        let characterCards=[];
        let characterSelectedIds=new Set();
        let characterUi={query:'',sort:'newest',view:'grid',modalId:null};
        let charactersUiInited=false;
        const $=(id)=>document.getElementById(id),
        checkAuth=()=>{const t=localStorage.getItem('adminToken');return t||(location.href='/login',null),t},
        apiRequest=async(url,opts={})=>{const t=checkAuth();if(!t)return null;const r=await fetch(url,{...opts,headers:{...opts.headers,Authorization:`Bearer ${t}`,'Content-Type':'application/json'}});try{let cached=null,cachedErr=null,done=false;r.json=async()=>{if(done){if(cachedErr)throw cachedErr;return cached}done=true;const text=await r.text();if(!text){cached=null;return cached}try{cached=JSON.parse(text);return cached}catch(e){cachedErr=new Error(`响应解析失败（可能被浏览器插件/拦截器改写）：${(e&&e.message)||String(e)}`);try{cachedErr.__raw_text=String(text).slice(0,1200)}catch(_){}throw cachedErr}}}catch(_){}return r.status===401?(localStorage.removeItem('adminToken'),location.href='/login',null):r},
        loadStats=async()=>{try{const r=await apiRequest('/api/stats');if(!r)return;const d=await r.json();$('statTotal').textContent=d.total_tokens||0;$('statActive').textContent=d.active_tokens||0;$('statImages').textContent=(d.today_images||0)+'/'+(d.total_images||0);$('statVideos').textContent=(d.today_videos||0)+'/'+(d.total_videos||0);$('statErrors').textContent=(d.today_errors||0)+'/'+(d.total_errors||0)}catch(e){console.error('加载统计失败:',e)}},
        loadTokens=async()=>{try{const r=await apiRequest('/api/tokens');if(!r)return;allTokens=await r.json();renderTokens()}catch(e){console.error('加载Token失败:',e)}},
        formatExpiry=exp=>{if(!exp)return'-';const d=new Date(exp),now=new Date(),diff=d-now;const dateStr=d.toLocaleDateString('zh-CN',{year:'numeric',month:'2-digit',day:'2-digit'}).replace(/\//g,'-');const timeStr=d.toLocaleTimeString('zh-CN',{hour:'2-digit',minute:'2-digit',hour12:false});if(diff<0)return`<span class="text-red-600">${dateStr} ${timeStr}</span>`;const days=Math.floor(diff/864e5);if(days<7)return`<span class="text-orange-600">${dateStr} ${timeStr}</span>`;return`${dateStr} ${timeStr}`},
        formatPlanType=type=>{if(!type)return'-';const typeMap={'chatgpt_team':'Team','chatgpt_plus':'Plus','chatgpt_pro':'Pro','chatgpt_free':'Free'};return typeMap[type]||type},
        formatSora2=(t)=>{if(t.sora2_supported===true){const remaining=t.sora2_total_count-t.sora2_redeemed_count;const tooltipText=`邀请码: ${t.sora2_invite_code||'无'}\n可用次数: ${remaining}/${t.sora2_total_count}\n已用次数: ${t.sora2_redeemed_count}`;return`<div class="inline-flex items-center gap-1"><span class="inline-flex items-center rounded px-2 py-0.5 text-xs bg-green-50 text-green-700 cursor-pointer" title="${tooltipText}" onclick="copySora2Code('${t.sora2_invite_code||''}')">支持</span><span class="text-xs text-muted-foreground" title="${tooltipText}">${remaining}/${t.sora2_total_count}</span></div>`}else if(t.sora2_supported===false){return`<span class="inline-flex items-center rounded px-2 py-0.5 text-xs bg-gray-100 text-gray-700 cursor-pointer" title="点击使用邀请码激活" onclick="openSora2Modal(${t.id})">不支持</span>`}else{return'-'}},
        formatPlanTypeWithTooltip=(t)=>{const tooltipText=t.subscription_end?`套餐到期: ${new Date(t.subscription_end).toLocaleDateString('zh-CN',{year:'numeric',month:'2-digit',day:'2-digit'}).replace(/\//g,'-')} ${new Date(t.subscription_end).toLocaleTimeString('zh-CN',{hour:'2-digit',minute:'2-digit',hour12:false})}`:'';return`<span class="inline-flex items-center rounded px-2 py-0.5 text-xs bg-blue-50 text-blue-700 cursor-pointer" title="${tooltipText||t.plan_title||'-'}">${formatPlanType(t.plan_type)}</span>`},
        formatSora2Remaining=(t)=>{if(t.sora2_supported===true&&typeof t.sora2_remaining_count==='number'){const remaining=Math.max(0,t.sora2_remaining_count);return`<span class="text-xs inline-block" title="来源：测试接口返回的真实剩余次数">${remaining}/${DAILY_QUOTA}</span>`}const used=(t.image_count||0)+(t.video_count||0);const remaining=Math.max(0,DAILY_QUOTA-used);return`<span class="text-xs inline-block" title="来源：本地统计估算（可点击测试获取真实剩余次数）">${remaining}/${DAILY_QUOTA}</span>`},
        formatClientId=(clientId)=>{if(!clientId)return'-';const short=clientId.substring(0,8)+'...';return`<span class="text-xs font-mono cursor-pointer hover:text-primary" title="${clientId}" onclick="navigator.clipboard.writeText('${clientId}').then(()=>showToast('已复制','success'))">${short}</span>`},
        renderTokens=()=>{
          const tb=$('tokenTableBody');
          tb.innerHTML=allTokens.map(t=>{
            const tokenId=Number(t&&t.id);
            const isTesting=testingTokenIds.has(tokenId);
            const testingAttr=isTesting?' data-testing="1" aria-busy="true"':'';
            const pulse=rowPulseMap.get(tokenId);
            const pulseAttr=pulse?` data-pulse="${pulse}"`:'';
            const imageDisplay=t.image_enabled?`${t.image_count||0}`:'-';
            const videoDisplay=(t.video_enabled&&t.sora2_supported)?`${t.video_count||0}`:'-';
            const testLabel=isTesting?'测试中':'测试';
            const testCls=isTesting?'opacity-60 pointer-events-none':'';
            const quotaLoading=isTesting?`<div class="quota-loading" aria-hidden="true"><span class="quota-loading-pill">测试中</span><span class="quota-loading-dots"></span></div>`:'';

            return `
              <tr data-token-id="${t.id}"${testingAttr}${pulseAttr}>
                <td class="py-2.5 px-3">${t.email}</td>
                <td class="py-2.5 px-3">
                  <span class="inline-flex items-center rounded px-2 py-0.5 text-xs ${t.is_active?'bg-green-50 text-green-700':'bg-gray-100 text-gray-700'}">${t.is_active?'活跃':'禁用'}</span>
                </td>
                <td class="py-2.5 px-3">${formatClientId(t.client_id)}</td>
                <td class="py-2.5 px-3 text-xs">${formatExpiry(t.expiry_time)}</td>
                <td class="py-2.5 px-3 text-xs">${formatPlanTypeWithTooltip(t)}</td>
                <td class="py-2.5 px-3 text-xs">${formatSora2(t)}</td>
                <td class="py-2.5 px-3 quota-cell" data-col="quota" data-token-id="${t.id}"${isTesting?' data-testing="1"':''}>
                  ${formatSora2Remaining(t)}
                  ${quotaLoading}
                </td>
                <td class="py-2.5 px-3">${imageDisplay}</td>
                <td class="py-2.5 px-3">${videoDisplay}</td>
                <td class="py-2.5 px-3">${t.error_count||0}</td>
                <td class="py-2.5 px-3 text-xs text-muted-foreground">${t.remark||'-'}</td>
                <td class="py-2.5 px-3 text-right">
                  <button data-action="test" onclick="testToken(${t.id})" class="inline-flex items-center justify-center rounded-md hover:bg-blue-50 hover:text-blue-700 h-7 px-2 text-xs mr-1 ${testCls}">${testLabel}</button>
                  <button onclick="openEditModal(${t.id})" class="inline-flex items-center justify-center rounded-md hover:bg-green-50 hover:text-green-700 h-7 px-2 text-xs mr-1">编辑</button>
                  <button onclick="toggleToken(${t.id},${t.is_active})" class="inline-flex items-center justify-center rounded-md hover:bg-accent h-7 px-2 text-xs mr-1">${t.is_active?'禁用':'启用'}</button>
                  <button onclick="deleteToken(${t.id})" class="inline-flex items-center justify-center rounded-md hover:bg-destructive/10 hover:text-destructive h-7 px-2 text-xs">删除</button>
                </td>
              </tr>
            `;
          }).join('');
        },
        refreshTokens=async()=>{await loadTokens();await loadStats();updateQuotaStats()},
        updateQuotaStats=()=>{const total=DAILY_QUOTA*allTokens.length;const remaining=allTokens.reduce((s,t)=>{if(t&&t.sora2_supported===true&&typeof t.sora2_remaining_count==='number')return s+Math.max(0,t.sora2_remaining_count);const used=(t.image_count||0)+(t.video_count||0);return s+Math.max(0,DAILY_QUOTA-used)},0);const el=$('statQuota');if(!el)return;const nextText=allTokens.length?`${remaining} / ${total}`:'-';const prev=el.textContent||'';el.textContent=nextText;if(prev&&prev!==nextText){try{const reduce=window.matchMedia&&window.matchMedia('(prefers-reduced-motion: reduce)').matches;if(reduce)return;const now=Date.now();if(quotaTotalFlashTs&&now-quotaTotalFlashTs<900)return;quotaTotalFlashTs=now;el.classList.remove('quota-total-flash');void el.offsetWidth;el.classList.add('quota-total-flash');setTimeout(()=>{try{el.classList.remove('quota-total-flash')}catch(_){}},2400)}catch(_){}}},
        applyTokenTestResultToList=(id,d)=>{
          const targetId=Number(id);
          const idx=allTokens.findIndex(t=>Number(t&&t.id)===targetId);
          if(idx<0) return false;
          const cur=allTokens[idx]||{};
          const next={...cur};
          if(d.email) next.email=d.email;
          if(d.username) next.name=d.username;
          if(d.sora2_supported!==undefined) next.sora2_supported=d.sora2_supported;
          if(d.sora2_invite_code!==undefined) next.sora2_invite_code=d.sora2_invite_code;
          if(d.sora2_redeemed_count!==undefined) next.sora2_redeemed_count=d.sora2_redeemed_count;
          if(d.sora2_total_count!==undefined) next.sora2_total_count=d.sora2_total_count;
          if(d.sora2_remaining_count!==undefined){
            const prevReal=(typeof cur.sora2_remaining_count==='number')?cur.sora2_remaining_count:null;
            const nxt=Number(d.sora2_remaining_count);
            if(Number.isFinite(nxt)){
              next.sora2_remaining_count=nxt;
              // 没有历史真实值时，用本地估算当作动画起点（更顺滑、更“有生命力”）
              const used=(cur.image_count||0)+(cur.video_count||0);
              const prevFallback=Math.max(0,DAILY_QUOTA-used);
              const from=(typeof prevReal==='number'&&Number.isFinite(prevReal))?prevReal:prevFallback;
              if(Number.isFinite(from)&&from!==nxt){
                quotaAnimMap.set(targetId,{from,to:nxt,at:Date.now()});
              }
            }else{
              next.sora2_remaining_count=nxt;
            }
          }
          allTokens[idx]=next;
          return true;
        },
        setBtnLabel=(btn,text)=>{if(!btn)return;const span=btn.querySelector('span');if(span)span.textContent=text;else btn.textContent=text;},
        setTokenTesting=(id,testing)=>{try{const tokenId=Number(id);if(!Number.isFinite(tokenId))return;if(testing)testingTokenIds.add(tokenId);else testingTokenIds.delete(tokenId);const row=document.querySelector(`#tokenTableBody tr[data-token-id="${tokenId}"]`);if(!row)return;if(testing){row.dataset.testing='1';row.setAttribute('aria-busy','true')}else{try{delete row.dataset.testing}catch(_){}row.removeAttribute('aria-busy')}const cell=row.querySelector('td[data-col="quota"]');if(cell){if(testing)cell.dataset.testing='1';else{try{delete cell.dataset.testing}catch(_){}}const loading=cell.querySelector('.quota-loading');if(testing){if(!loading){cell.insertAdjacentHTML('beforeend',`<div class="quota-loading" aria-hidden="true"><span class="quota-loading-pill">测试中</span><span class="quota-loading-dots"></span></div>`);}}else{if(loading)loading.remove();}}const btn=row.querySelector('button[data-action="test"]');if(btn){if(testing){btn.textContent='测试中';btn.classList.add('opacity-60','pointer-events-none');btn.dataset.loading='1'}else{btn.textContent='测试';btn.classList.remove('opacity-60','pointer-events-none');try{delete btn.dataset.loading}catch(_){}}}}catch(_){} },
        pulseTokenRow=(id,kind)=>{try{const reduce=window.matchMedia&&window.matchMedia('(prefers-reduced-motion: reduce)').matches;if(reduce)return;const tokenId=Number(id);if(!Number.isFinite(tokenId))return;const k=(kind==='ok'?'ok':'fail');rowPulseMap.set(tokenId,k);setTimeout(()=>{try{rowPulseMap.delete(tokenId)}catch(_){}},1350);const row=document.querySelector(`#tokenTableBody tr[data-token-id="${tokenId}"]`);if(!row)return;row.dataset.pulse=k;setTimeout(()=>{try{delete row.dataset.pulse}catch(_){}},1300)}catch(_){} },
        spawnQuotaDelta=(cell,diff)=>{try{if(!cell||!Number.isFinite(diff)||diff===0)return;const reduce=window.matchMedia&&window.matchMedia('(prefers-reduced-motion: reduce)').matches;if(reduce)return;const el=document.createElement('div');el.className=`quota-delta ${diff>0?'up':'down'}`;el.textContent=diff>0?`+${Math.abs(diff)}`:`-${Math.abs(diff)}`;cell.appendChild(el);setTimeout(()=>{try{el.remove()}catch(_){}},QUOTA_FLASH_MS)}catch(_){} },
        animateQuotaNumber=(cell,from,to)=>{try{if(!cell)return;if(!Number.isFinite(from)||!Number.isFinite(to)||from===to)return;const reduce=window.matchMedia&&window.matchMedia('(prefers-reduced-motion: reduce)').matches;if(reduce)return;const span=cell.querySelector('span');if(!span)return;const start=(typeof performance!=='undefined'&&performance.now)?performance.now():Date.now();const duration=1900;const f=Math.max(0,Math.round(from));const t=Math.max(0,Math.round(to));const easeOutCubic=p=>1-Math.pow(1-p,3);const tick=(now)=>{const n=(now-start)/duration;const p=Math.min(1,Math.max(0,n));const v=Math.round(f+(t-f)*easeOutCubic(p));span.textContent=`${Math.max(0,Math.min(DAILY_QUOTA,v))}/${DAILY_QUOTA}`;if(p<1)requestAnimationFrame(tick)};requestAnimationFrame(tick)}catch(_){}},
        spawnQuotaSparkles=(cell,diff)=>{try{if(!cell||!Number.isFinite(diff)||diff===0)return;const reduce=window.matchMedia&&window.matchMedia('(prefers-reduced-motion: reduce)').matches;if(reduce)return;const isDown=diff<0;try{cell.querySelectorAll('.quota-spark').forEach(n=>n.remove())}catch(_){}
          const count=Math.max(6,Math.min(12,6+Math.floor(Math.abs(diff))));
          for(let i=0;i<count;i++){
            const el=document.createElement('i');
            el.className=`quota-spark ${isDown?'down':'up'}`;
            const x0=Math.round((Math.random()*2-1)*10);
            const y0=Math.round((Math.random()*2-1)*8);
            const x1=Math.round(x0+(Math.random()*2-1)*22);
            const y1=Math.round(y0-(18+Math.random()*18));
            const s=Math.round(6+Math.random()*7);
            const dly=(Math.random()*0.18).toFixed(3)+'s';
            el.style.setProperty('--x0',x0+'px');
            el.style.setProperty('--y0',y0+'px');
            el.style.setProperty('--x1',x1+'px');
            el.style.setProperty('--y1',y1+'px');
            el.style.setProperty('--s',s+'px');
            el.style.setProperty('--d',dly);
            cell.appendChild(el);
            setTimeout(()=>{try{el.remove()}catch(_){}},QUOTA_FLASH_MS+250);
          }
        }catch(_){} },
        flashQuotaCell=(id)=>{
          const tokenId=Number(id);
          const cell=document.querySelector(`#tokenTableBody tr[data-token-id="${tokenId}"] td[data-col="quota"]`);
          if(!cell) return;
          const anim=quotaAnimMap.get(tokenId);
          let diff=0;
          if(anim){
            quotaAnimMap.delete(tokenId);
            diff=Math.round(anim.to-anim.from);
            animateQuotaNumber(cell,anim.from,anim.to);
            spawnQuotaDelta(cell,diff);
          }
          cell.classList.remove('quota-flash','quota-up','quota-down','quota-neutral');
          void cell.offsetWidth;
          cell.classList.add('quota-flash',diff<0?'quota-down':diff>0?'quota-up':'quota-neutral');
          if(diff) spawnQuotaSparkles(cell,diff);
          setTimeout(()=>cell.classList.remove('quota-flash','quota-up','quota-down','quota-neutral'),QUOTA_FLASH_MS);
        },
        queueTokenTableRender=()=>{if(tokenTableRenderQueued)return;tokenTableRenderQueued=true;requestAnimationFrame(()=>{tokenTableRenderQueued=false;renderTokens();updateQuotaStats();quotaFlashIds.forEach(flashQuotaCell);quotaFlashIds.clear();});},
        markQuotaUpdated=(id)=>{quotaFlashIds.add(Number(id));queueTokenTableRender();},
        apiRequestTimed=async(url,opts={},timeoutMs=TOKEN_TEST_TIMEOUT_MS)=>{const controller=typeof AbortController!=='undefined'?new AbortController():null;const merged=controller?{...opts,signal:controller.signal}:opts;let timer=null;try{const p=apiRequest(url,merged);if(!timeoutMs||timeoutMs<=0)return await p;return await Promise.race([p,new Promise((_,rej)=>{timer=setTimeout(()=>{try{controller&&controller.abort()}catch(_){}rej(new Error('请求超时'))},timeoutMs)})])}finally{if(timer)clearTimeout(timer)}},
        readJson=(r)=>r.text().then(t=>{if(!t)return null;try{return JSON.parse(t)}catch(e){return {__raw_text:t,__parse_error:(e&&e.message)||String(e)}}}),
        openAddModal=()=>$('addModal').classList.remove('hidden'),
        closeAddModal=()=>{$('addModal').classList.add('hidden');$('addTokenAT').value='';$('addTokenST').value='';$('addTokenRT').value='';$('addTokenClientId').value='';$('addTokenRemark').value='';$('addTokenImageEnabled').checked=true;$('addTokenVideoEnabled').checked=true;$('addTokenImageConcurrency').value='-1';$('addTokenVideoConcurrency').value='-1';$('addRTRefreshHint').classList.add('hidden')},
        openEditModal=(id)=>{const token=allTokens.find(t=>t.id===id);if(!token)return showToast('Token不存在','error');$('editTokenId').value=token.id;$('editTokenAT').value=token.token||'';$('editTokenST').value=token.st||'';$('editTokenRT').value=token.rt||'';$('editTokenClientId').value=token.client_id||'';$('editTokenRemark').value=token.remark||'';$('editTokenImageEnabled').checked=token.image_enabled!==false;$('editTokenVideoEnabled').checked=token.video_enabled!==false;$('editTokenImageConcurrency').value=token.image_concurrency||'-1';$('editTokenVideoConcurrency').value=token.video_concurrency||'-1';$('editModal').classList.remove('hidden')},
        closeEditModal=()=>{$('editModal').classList.add('hidden');$('editTokenId').value='';$('editTokenAT').value='';$('editTokenST').value='';$('editTokenRT').value='';$('editTokenClientId').value='';$('editTokenRemark').value='';$('editTokenImageEnabled').checked=true;$('editTokenVideoEnabled').checked=true;$('editTokenImageConcurrency').value='';$('editTokenVideoConcurrency').value='';$('editRTRefreshHint').classList.add('hidden')},
        submitEditToken=async()=>{const id=parseInt($('editTokenId').value),at=$('editTokenAT').value.trim(),st=$('editTokenST').value.trim(),rt=$('editTokenRT').value.trim(),clientId=$('editTokenClientId').value.trim(),remark=$('editTokenRemark').value.trim(),imageEnabled=$('editTokenImageEnabled').checked,videoEnabled=$('editTokenVideoEnabled').checked,imageConcurrency=$('editTokenImageConcurrency').value?parseInt($('editTokenImageConcurrency').value):null,videoConcurrency=$('editTokenVideoConcurrency').value?parseInt($('editTokenVideoConcurrency').value):null;if(!id)return showToast('Token ID无效','error');if(!at)return showToast('请输入 Access Token','error');const btn=$('editTokenBtn'),btnText=$('editTokenBtnText'),btnSpinner=$('editTokenBtnSpinner');btn.disabled=true;btnText.textContent='保存中...';btnSpinner.classList.remove('hidden');try{const r=await apiRequest(`/api/tokens/${id}`,{method:'PUT',body:JSON.stringify({token:at,st:st||null,rt:rt||null,client_id:clientId||null,remark:remark||null,image_enabled:imageEnabled,video_enabled:videoEnabled,image_concurrency:imageConcurrency,video_concurrency:videoConcurrency})});if(!r){btn.disabled=false;btnText.textContent='保存';btnSpinner.classList.add('hidden');return}const d=await r.json();if(d.success){closeEditModal();await refreshTokens();showToast('Token更新成功','success')}else{showToast('更新失败: '+(d.detail||d.message||'未知错误'),'error')}}catch(e){showToast('更新失败: '+e.message,'error')}finally{btn.disabled=false;btnText.textContent='保存';btnSpinner.classList.add('hidden')}},
        convertST2AT=async()=>{const st=$('addTokenST').value.trim();if(!st)return showToast('请先输入 Session Token','error');try{showToast('正在转换 ST→AT...','info');const r=await apiRequest('/api/tokens/st2at',{method:'POST',body:JSON.stringify({st:st})});if(!r)return;const d=await r.json();if(d.success&&d.access_token){$('addTokenAT').value=d.access_token;showToast('转换成功！AT已自动填入','success')}else{showToast('转换失败: '+(d.message||d.detail||'未知错误'),'error')}}catch(e){showToast('转换失败: '+e.message,'error')}},
        convertRT2AT=async()=>{const rt=$('addTokenRT').value.trim();if(!rt)return showToast('请先输入 Refresh Token','error');const hint=$('addRTRefreshHint');hint.classList.add('hidden');try{showToast('正在转换 RT→AT...','info');const r=await apiRequest('/api/tokens/rt2at',{method:'POST',body:JSON.stringify({rt:rt})});if(!r)return;const d=await r.json();if(d.success&&d.access_token){$('addTokenAT').value=d.access_token;if(d.refresh_token){$('addTokenRT').value=d.refresh_token;hint.classList.remove('hidden');showToast('转换成功！AT已自动填入，RT已被刷新并更新','success')}else{showToast('转换成功！AT已自动填入','success')}}else{showToast('转换失败: '+(d.message||d.detail||'未知错误'),'error')}}catch(e){showToast('转换失败: '+e.message,'error')}},
        convertEditST2AT=async()=>{const st=$('editTokenST').value.trim();if(!st)return showToast('请先输入 Session Token','error');try{showToast('正在转换 ST→AT...','info');const r=await apiRequest('/api/tokens/st2at',{method:'POST',body:JSON.stringify({st:st})});if(!r)return;const d=await r.json();if(d.success&&d.access_token){$('editTokenAT').value=d.access_token;showToast('转换成功！AT已自动填入','success')}else{showToast('转换失败: '+(d.message||d.detail||'未知错误'),'error')}}catch(e){showToast('转换失败: '+e.message,'error')}},
        convertEditRT2AT=async()=>{const rt=$('editTokenRT').value.trim();if(!rt)return showToast('请先输入 Refresh Token','error');const hint=$('editRTRefreshHint');hint.classList.add('hidden');try{showToast('正在转换 RT→AT...','info');const r=await apiRequest('/api/tokens/rt2at',{method:'POST',body:JSON.stringify({rt:rt})});if(!r)return;const d=await r.json();if(d.success&&d.access_token){$('editTokenAT').value=d.access_token;if(d.refresh_token){$('editTokenRT').value=d.refresh_token;hint.classList.remove('hidden');showToast('转换成功！AT已自动填入，RT已被刷新并更新','success')}else{showToast('转换成功！AT已自动填入','success')}}else{showToast('转换失败: '+(d.message||d.detail||'未知错误'),'error')}}catch(e){showToast('转换失败: '+e.message,'error')}},
        submitAddToken=async()=>{const at=$('addTokenAT').value.trim(),st=$('addTokenST').value.trim(),rt=$('addTokenRT').value.trim(),clientId=$('addTokenClientId').value.trim(),remark=$('addTokenRemark').value.trim(),imageEnabled=$('addTokenImageEnabled').checked,videoEnabled=$('addTokenVideoEnabled').checked,imageConcurrency=parseInt($('addTokenImageConcurrency').value)||(-1),videoConcurrency=parseInt($('addTokenVideoConcurrency').value)||(-1);if(!at)return showToast('请输入 Access Token 或使用 ST/RT 转换','error');const btn=$('addTokenBtn'),btnText=$('addTokenBtnText'),btnSpinner=$('addTokenBtnSpinner');btn.disabled=true;btnText.textContent='添加中...';btnSpinner.classList.remove('hidden');try{const r=await apiRequest('/api/tokens',{method:'POST',body:JSON.stringify({token:at,st:st||null,rt:rt||null,client_id:clientId||null,remark:remark||null,image_enabled:imageEnabled,video_enabled:videoEnabled,image_concurrency:imageConcurrency,video_concurrency:videoConcurrency})});if(!r){btn.disabled=false;btnText.textContent='添加';btnSpinner.classList.add('hidden');return}if(r.status===409){const d=await r.json();const msg=d.detail||'Token 已存在';btn.disabled=false;btnText.textContent='添加';btnSpinner.classList.add('hidden');if(!confirmStep('overwrite_add_'+at,msg+'（再次点击“添加”将删除旧 Token 并重新添加）',{ttl:5200,type:'warn'}))return;const existingToken=allTokens.find(t=>t.token===at);if(existingToken){const deleted=await deleteToken(existingToken.id,true);if(deleted){showToast('正在重新添加...','info',{duration:2600});setTimeout(()=>submitAddToken(),450)}else{showToast('删除旧 Token 失败','error',{duration:3200})}}else{showToast('未找到旧 Token，请刷新列表后重试','error',{duration:3200})}return}const d=await r.json();if(d.success){closeAddModal();await refreshTokens();showToast('Token添加成功','success')}else{showToast('添加失败: '+(d.detail||d.message||'未知错误'),'error')}}catch(e){showToast('添加失败: '+e.message,'error')}finally{btn.disabled=false;btnText.textContent='添加';btnSpinner.classList.add('hidden')}},
        testToken=async(id)=>{
          const tokenId=Number(id);
          if(Number.isFinite(tokenId)&&testingTokenIds.has(tokenId)){
            showToast('该账号正在测试中，请稍候…','info');
            return;
          }

          setTokenTesting(tokenId,true);
          try{
            showToast('正在测试Token...','info');
            const r=await apiRequestTimed(`/api/tokens/${tokenId}/test`,{method:'POST'});
            if(!r) return;
            const d=await readJson(r);
            if(d&&d.success&&d.status==='success'){
              applyTokenTestResultToList(tokenId,d);
              pulseTokenRow(tokenId,'ok');
              if(d.sora2_supported===true&&d.sora2_remaining_count!==undefined)markQuotaUpdated(tokenId);
              let msg=`Token有效！用户: ${d.email||'未知'}`;
              if(d.sora2_supported){
                const remaining=d.sora2_total_count-d.sora2_redeemed_count;
                msg+=`\nSora2: 支持 (${remaining}/${d.sora2_total_count})`;
                if(d.sora2_remaining_count!==undefined){
                  msg+=`\n可用次数: ${d.sora2_remaining_count}`;
                }
              }
              showToast(msg,'success');
            }else{
              pulseTokenRow(tokenId,'fail');
              const m=(d&&(d.message||d.detail))||'未知错误';
              showToast(`Token无效: ${typeof m==='string'?m:JSON.stringify(m)}`,'error');
            }
          }catch(e){
            pulseTokenRow(tokenId,'fail');
            showToast('测试失败: '+(e&&e.message?e.message:String(e)),'error');
          }finally{
            setTokenTesting(tokenId,false);
          }
        },
        testAllTokens=async()=>{
          if(!allTokens.length) return showToast('暂无Token','error');
          const btn=$('btnTestAll');
          const ids=allTokens.map(t=>t&&t.id).filter(id=>id!==undefined&&id!==null);
          const total=ids.length;
          const concurrency=Math.max(1,Math.min(TEST_CONCURRENCY,total));
          if(btn){
            btn.disabled=true;
            btn.dataset.loading='1';
            setBtnLabel(btn,'测试中...');
          }
          showToast(`开始批量测试：${total} 个账号（并发 ${concurrency}）`,'info');

          let ok=0,fail=0,done=0;
          const failBy=new Map();
          let firstFailHint='';
          let progressQueued=false;
          let ended=false;
          let firstExceptionLogged=false;
          const bumpFail=(key)=>failBy.set(key,(failBy.get(key)||0)+1);
          const scheduleProgress=()=>{
            if(progressQueued) return;
            progressQueued=true;
            requestAnimationFrame(()=>{
              progressQueued=false;
              // 可能出现：批量结束后，最后一次 rAF 仍会把按钮文案写回“测试中... (n/n)”
              // 这里用 ended 兜底，避免 UI 看起来像“永远在测试中”。
              if(ended) return;
              if(btn) setBtnLabel(btn,`测试中... (${done}/${total})`);
            });
          };
          const extractMsg=(d)=>{
            if(!d) return '';
            const m=(d.message!==undefined?d.message:d.detail!==undefined?d.detail:d.error!==undefined?d.error:'');
            if(Array.isArray(m)) return m[0]&&m[0].msg?m[0].msg:JSON.stringify(m[0]||m);
            if(m&&typeof m==='object') return JSON.stringify(m);
            return String(m||'');
          };
          const tokenLabel=(id)=>{
            const token=allTokens.find(t=>Number(t&&t.id)===Number(id));
            return token?(token.email||token.name||`#${id}`):`#${id}`;
          };
          const isTimeout=(e)=>{
            const msg=(e&&e.message)?String(e.message):String(e||'');
            return (e&&e.name==='AbortError')||/超时|timeout/i.test(msg);
          };

          const runOne=async(id)=>{
            const tokenId=Number(id);
            let okThis=false;
            setTokenTesting(tokenId,true);
            try{
              const r=await apiRequestTimed(`/api/tokens/${tokenId}/test`,{method:'POST'});
              if(!r){
                fail++; bumpFail('请求失败');
                return;
              }
              const d=await readJson(r);
              if(d&&d.__parse_error){
                fail++; bumpFail(`响应解析失败(${r.status||'?'})`);
                if(!firstFailHint) firstFailHint=`${tokenLabel(tokenId)}：HTTP ${r.status||'?'} 响应不是JSON`;
                return;
              }
              if(d&&d.success&&d.status==='success'){
                ok++; okThis=true;
                applyTokenTestResultToList(tokenId,d);
                if(d.sora2_supported===true&&d.sora2_remaining_count!==undefined)markQuotaUpdated(tokenId);
              }else{
                fail++; bumpFail(`失败(${r.status||'?'})`);
                if(!firstFailHint){
                  const msg=extractMsg(d)||'测试失败';
                  firstFailHint=`${tokenLabel(tokenId)}：${msg}`;
                }
              }
            }catch(e){
              fail++; bumpFail(isTimeout(e)?'超时':'异常');
              if(!firstFailHint) firstFailHint=`${tokenLabel(tokenId)}：${(e&&e.message)?e.message:String(e)}`;
              if(!firstExceptionLogged){
                firstExceptionLogged=true;
                console.error('一键测试首个异常（用于定位）:',e);
              }
            }finally{
              setTokenTesting(tokenId,false);
              pulseTokenRow(tokenId,okThis?'ok':'fail');
              done++;
              scheduleProgress();
            }
          };

          let cursor=0;
          const worker=async()=>{
            for(;;){
              const i=cursor++;
              if(i>=total) break;
              await runOne(ids[i]);
            }
          };

          try{
            await Promise.all(Array.from({length:concurrency},()=>worker()));
          }catch(e){
            showToast('一键测试异常: '+(e&&e.message?e.message:String(e)),'error');
          }finally{
            ended=true;
            // 防止极端情况下 UI 卡在“测试中”
            try{testingTokenIds.clear();}catch(_){}
            try{document.querySelectorAll('#tokenTableBody tr[data-testing=\"1\"]').forEach(r=>{try{delete r.dataset.testing}catch(_){}r.removeAttribute('aria-busy')});}catch(_){}
            try{document.querySelectorAll('#tokenTableBody td[data-col=\"quota\"][data-testing=\"1\"]').forEach(c=>{try{delete c.dataset.testing}catch(_){}try{c.querySelector('.quota-loading')?.remove()}catch(_){} });}catch(_){}
            // 兜底：表格可能在测试中被重渲染过（quota-loading 来自 renderTokens 的字符串拼接，不一定带 data-testing）
            try{document.querySelectorAll('#tokenTableBody .quota-loading').forEach(el=>{try{el.remove()}catch(_){} });}catch(_){}

            try{queueTokenTableRender();}catch(e){console.warn('批量测试结束：渲染失败（不影响按钮复原）',e)}
            if(btn){
              btn.disabled=false;
              delete btn.dataset.loading;
              btn.dataset.done=fail>0?'warn':'ok';
              setTimeout(()=>{try{delete btn.dataset.done}catch(_){}} ,900);
              setBtnLabel(btn,'一键测试');
            }
          }

          showToast(`测试完成：成功 ${ok} / 失败 ${fail}`,'info');
          if(fail>0){
            const summary=Object.fromEntries(failBy);
            // 部分浏览器环境/扩展会 hook console，传入 Object 可能直接抛错；这里仅输出 JSON 字符串并做 try/catch 降噪
            try{console.warn('一键测试失败摘要(JSON)：'+JSON.stringify(summary));}catch(_){try{console.warn('一键测试失败摘要：无法序列化');}catch(__){}}
          }
          if(firstFailHint&&fail>0){
            showToast(`失败示例：${firstFailHint}`,'error');
          }
        },
        toggleToken=async(id,isActive)=>{const action=isActive?'disable':'enable';try{const r=await apiRequest(`/api/tokens/${id}/${action}`,{method:'POST'});if(!r)return;const d=await r.json();d.success?(await refreshTokens(),showToast(isActive?'Token已禁用':'Token已启用','success')):showToast('操作失败','error')}catch(e){showToast('操作失败: '+e.message,'error')}},
        toggleTokenStatus=async(id,active)=>{try{const r=await apiRequest(`/api/tokens/${id}/status`,{method:'PUT',body:JSON.stringify({is_active:active})});if(!r)return;const d=await r.json();d.success?(await refreshTokens(),showToast('状态更新成功','success')):showToast('更新失败','error')}catch(e){showToast('更新失败: '+e.message,'error')}},
        deleteToken=async(id,skipConfirm=false)=>{if(!skipConfirm&&!confirmStep('delete_token_'+id,`再次点击确认删除 Token（ID: ${id}）`,{ttl:5200,type:'warn'}))return;try{const r=await apiRequest(`/api/tokens/${id}`,{method:'DELETE'});if(!r)return;const d=await r.json();if(d.success){await refreshTokens();if(!skipConfirm)showToast('删除成功','success');return true}else{if(!skipConfirm)showToast('删除失败','error');return false}}catch(e){if(!skipConfirm)showToast('删除失败: '+e.message,'error');return false}},
        copySora2Code=async(code)=>{if(!code){showToast('没有可复制的邀请码','error');return}try{if(navigator.clipboard&&navigator.clipboard.writeText){await navigator.clipboard.writeText(code);showToast(`邀请码已复制: ${code}`,'success')}else{const textarea=document.createElement('textarea');textarea.value=code;textarea.style.position='fixed';textarea.style.opacity='0';document.body.appendChild(textarea);textarea.select();const success=document.execCommand('copy');document.body.removeChild(textarea);if(success){showToast(`邀请码已复制: ${code}`,'success')}else{showToast('复制失败: 浏览器不支持','error')}}}catch(e){showToast('复制失败: '+e.message,'error')}},
        openSora2Modal=(id)=>{$('sora2TokenId').value=id;$('sora2InviteCode').value='';$('sora2Modal').classList.remove('hidden')},
        closeSora2Modal=()=>{$('sora2Modal').classList.add('hidden');$('sora2TokenId').value='';$('sora2InviteCode').value=''},
        openImportModal=()=>{$('importModal').classList.remove('hidden');$('importFile').value=''},
        closeImportModal=()=>{$('importModal').classList.add('hidden');$('importFile').value=''},
        exportTokens=()=>{if(allTokens.length===0){showToast('没有Token可导出','error');return}const exportData=allTokens.map(t=>({email:t.email,access_token:t.token,session_token:t.st||null,refresh_token:t.rt||null,is_active:t.is_active,image_enabled:t.image_enabled!==false,video_enabled:t.video_enabled!==false,image_concurrency:t.image_concurrency||(-1),video_concurrency:t.video_concurrency||(-1)}));const dataStr=JSON.stringify(exportData,null,2);const dataBlob=new Blob([dataStr],{type:'application/json'});const url=URL.createObjectURL(dataBlob);const link=document.createElement('a');link.href=url;link.download=`tokens_${new Date().toISOString().split('T')[0]}.json`;document.body.appendChild(link);link.click();document.body.removeChild(link);URL.revokeObjectURL(url);showToast(`已导出 ${allTokens.length} 个Token`,'success')},
        submitImportTokens=async()=>{const fileInput=$('importFile');if(!fileInput.files||fileInput.files.length===0){showToast('请选择文件','error');return}const file=fileInput.files[0];if(!file.name.endsWith('.json')){showToast('请选择JSON文件','error');return}try{const fileContent=await file.text();const importData=JSON.parse(fileContent);if(!Array.isArray(importData)){showToast('JSON格式错误：应为数组','error');return}if(importData.length===0){showToast('JSON文件为空','error');return}const btn=$('importBtn'),btnText=$('importBtnText'),btnSpinner=$('importBtnSpinner');btn.disabled=true;btnText.textContent='导入中...';btnSpinner.classList.remove('hidden');try{const r=await apiRequest('/api/tokens/import',{method:'POST',body:JSON.stringify({tokens:importData})});if(!r){btn.disabled=false;btnText.textContent='导入';btnSpinner.classList.add('hidden');return}const d=await r.json();if(d.success){closeImportModal();await refreshTokens();const msg=`导入成功！新增: ${d.added||0}, 更新: ${d.updated||0}`;showToast(msg,'success')}else{showToast('导入失败: '+(d.detail||d.message||'未知错误'),'error')}}catch(e){showToast('导入失败: '+e.message,'error')}finally{btn.disabled=false;btnText.textContent='导入';btnSpinner.classList.add('hidden')}}catch(e){showToast('文件解析失败: '+e.message,'error')}},
        submitSora2Activate=async()=>{const tokenId=parseInt($('sora2TokenId').value),inviteCode=$('sora2InviteCode').value.trim();if(!tokenId)return showToast('Token ID无效','error');if(!inviteCode)return showToast('请输入邀请码','error');if(inviteCode.length!==6)return showToast('邀请码必须是6位','error');const btn=$('sora2ActivateBtn'),btnText=$('sora2ActivateBtnText'),btnSpinner=$('sora2ActivateBtnSpinner');btn.disabled=true;btnText.textContent='激活中...';btnSpinner.classList.remove('hidden');try{showToast('正在激活Sora2...','info');const r=await apiRequest(`/api/tokens/${tokenId}/sora2/activate?invite_code=${inviteCode}`,{method:'POST'});if(!r){btn.disabled=false;btnText.textContent='激活';btnSpinner.classList.add('hidden');return}const d=await r.json();if(d.success){closeSora2Modal();await refreshTokens();if(d.already_accepted){showToast('Sora2已激活（之前已接受）','success')}else{showToast(`Sora2激活成功！邀请码: ${d.invite_code||'无'}`,'success')}}else{showToast('激活失败: '+(d.message||'未知错误'),'error')}}catch(e){showToast('激活失败: '+e.message,'error')}finally{btn.disabled=false;btnText.textContent='激活';btnSpinner.classList.add('hidden')}},
        loadAdminConfig=async()=>{try{const r=await apiRequest('/api/admin/config');if(!r)return;const d=await r.json();$('cfgErrorBan').value=d.error_ban_threshold||3;$('cfgAdminUsername').value=d.admin_username||'admin';$('cfgCurrentAPIKey').value=d.api_key||'';$('cfgDebugEnabled').checked=d.debug_enabled||false}catch(e){console.error('加载配置失败:',e)}},
        saveAdminConfig=async()=>{try{const r=await apiRequest('/api/admin/config',{method:'POST',body:JSON.stringify({error_ban_threshold:parseInt($('cfgErrorBan').value)||3})});if(!r)return;const d=await r.json();d.success?showToast('配置保存成功','success'):showToast('保存失败','error')}catch(e){showToast('保存失败: '+e.message,'error')}},
        updateAdminPassword=async()=>{const username=$('cfgAdminUsername').value.trim(),oldPwd=$('cfgOldPassword').value.trim(),newPwd=$('cfgNewPassword').value.trim();if(!oldPwd||!newPwd)return showToast('请输入旧密码和新密码','error');if(newPwd.length<4)return showToast('新密码至少4个字符','error');try{const r=await apiRequest('/api/admin/password',{method:'POST',body:JSON.stringify({username:username||undefined,old_password:oldPwd,new_password:newPwd})});if(!r)return;const d=await r.json();if(d.success){showToast('密码修改成功，请重新登录','success');setTimeout(()=>{localStorage.removeItem('adminToken');location.href='/login'},2000)}else{showToast('修改失败: '+(d.detail||'未知错误'),'error')}}catch(e){showToast('修改失败: '+e.message,'error')}},
        updateAPIKey=async()=>{const newKey=$('cfgNewAPIKey').value.trim();if(!newKey)return showToast('请输入新的 API Key','error');if(newKey.length<6)return showToast('API Key 至少6个字符','error');if(!confirmStep('update_apikey','再次点击确认更新 API Key（将影响所有客户端）',{ttl:6500,type:'warn'}))return;try{const r=await apiRequest('/api/admin/apikey',{method:'POST',body:JSON.stringify({new_api_key:newKey})});if(!r)return;const d=await r.json();if(d.success){showToast('API Key 更新成功','success');$('cfgCurrentAPIKey').value=newKey;$('cfgNewAPIKey').value=''}else{showToast('更新失败: '+(d.detail||'未知错误'),'error')}}catch(e){showToast('更新失败: '+e.message,'error')}},
        toggleDebugMode=async()=>{const enabled=$('cfgDebugEnabled').checked;try{const r=await apiRequest('/api/admin/debug',{method:'POST',body:JSON.stringify({enabled:enabled})});if(!r)return;const d=await r.json();if(d.success){showToast(enabled?'调试模式已开启':'调试模式已关闭','success')}else{showToast('操作失败: '+(d.detail||'未知错误'),'error');$('cfgDebugEnabled').checked=!enabled}}catch(e){showToast('操作失败: '+e.message,'error');$('cfgDebugEnabled').checked=!enabled}},
        loadProxyConfig=async()=>{try{const r=await apiRequest('/api/proxy/config');if(!r)return;const d=await r.json();$('cfgProxyEnabled').checked=d.proxy_enabled||false;$('cfgProxyUrl').value=d.proxy_url||''}catch(e){console.error('加载代理配置失败:',e)}},
        saveProxyConfig=async()=>{try{const r=await apiRequest('/api/proxy/config',{method:'POST',body:JSON.stringify({proxy_enabled:$('cfgProxyEnabled').checked,proxy_url:$('cfgProxyUrl').value.trim()})});if(!r)return;const d=await r.json();d.success?showToast('代理配置保存成功','success'):showToast('保存失败','error')}catch(e){showToast('保存失败: '+e.message,'error')}},
        loadWatermarkFreeConfig=async()=>{try{const r=await apiRequest('/api/watermark-free/config');if(!r)return;const d=await r.json();$('cfgWatermarkFreeEnabled').checked=d.watermark_free_enabled||false;$('cfgParseMethod').value=d.parse_method||'third_party';$('cfgCustomParseUrl').value=d.custom_parse_url||'';$('cfgCustomParseToken').value=d.custom_parse_token||'';toggleWatermarkFreeOptions();toggleCustomParseOptions()}catch(e){console.error('加载无水印模式配置失败:',e)}},
        saveWatermarkFreeConfig=async()=>{try{const enabled=$('cfgWatermarkFreeEnabled').checked,parseMethod=$('cfgParseMethod').value,customUrl=$('cfgCustomParseUrl').value.trim(),customToken=$('cfgCustomParseToken').value.trim();if(enabled&&parseMethod==='custom'){if(!customUrl)return showToast('请输入解析服务器地址','error');if(!customToken)return showToast('请输入访问密钥','error')}const r=await apiRequest('/api/watermark-free/config',{method:'POST',body:JSON.stringify({watermark_free_enabled:enabled,parse_method:parseMethod,custom_parse_url:customUrl||null,custom_parse_token:customToken||null})});if(!r)return;const d=await r.json();d.success?showToast('无水印模式配置保存成功','success'):showToast('保存失败','error')}catch(e){showToast('保存失败: '+e.message,'error')}},
        toggleWatermarkFreeOptions=()=>{const enabled=$('cfgWatermarkFreeEnabled').checked;$('watermarkFreeOptions').style.display=enabled?'block':'none'},
        toggleCustomParseOptions=()=>{const method=$('cfgParseMethod').value;$('customParseOptions').style.display=method==='custom'?'block':'none'},
        toggleCacheOptions=()=>{const enabled=$('cfgCacheEnabled').checked;$('cacheOptions').style.display=enabled?'block':'none'},
        loadCacheConfig=async()=>{try{console.log('开始加载缓存配置...');const r=await apiRequest('/api/cache/config');if(!r){console.error('API请求失败');return}const d=await r.json();console.log('缓存配置数据:',d);if(d.success&&d.config){const enabled=d.config.enabled!==false;const timeout=d.config.timeout||7200;const baseUrl=d.config.base_url||'';const effectiveUrl=d.config.effective_base_url||'';console.log('设置缓存启用:',enabled);console.log('设置超时时间:',timeout);console.log('设置域名:',baseUrl);console.log('生效URL:',effectiveUrl);$('cfgCacheEnabled').checked=enabled;$('cfgCacheTimeout').value=timeout;$('cfgCacheBaseUrl').value=baseUrl;if(effectiveUrl){$('cacheEffectiveUrlValue').textContent=effectiveUrl;$('cacheEffectiveUrl').classList.remove('hidden')}else{$('cacheEffectiveUrl').classList.add('hidden')}toggleCacheOptions();console.log('缓存配置加载成功')}else{console.error('缓存配置数据格式错误:',d)}}catch(e){console.error('加载缓存配置失败:',e);showToast('加载缓存配置失败: '+e.message,'error')}},
        loadGenerationTimeout=async()=>{try{console.log('开始加载生成超时配置...');const r=await apiRequest('/api/generation/timeout');if(!r){console.error('API请求失败');return}const d=await r.json();console.log('生成超时配置数据:',d);if(d.success&&d.config){const imageTimeout=d.config.image_timeout||300;const videoTimeout=d.config.video_timeout||1500;console.log('设置图片超时:',imageTimeout);console.log('设置视频超时:',videoTimeout);$('cfgImageTimeout').value=imageTimeout;$('cfgVideoTimeout').value=videoTimeout;console.log('生成超时配置加载成功')}else{console.error('生成超时配置数据格式错误:',d)}}catch(e){console.error('加载生成超时配置失败:',e);showToast('加载生成超时配置失败: '+e.message,'error')}},
        saveCacheConfig=async()=>{const enabled=$('cfgCacheEnabled').checked,timeout=parseInt($('cfgCacheTimeout').value)||7200,baseUrl=$('cfgCacheBaseUrl').value.trim();console.log('保存缓存配置:',{enabled,timeout,baseUrl});if(timeout<60||timeout>86400)return showToast('缓存超时时间必须在 60-86400 秒之间','error');if(baseUrl&&!baseUrl.startsWith('http://')&&!baseUrl.startsWith('https://'))return showToast('域名必须以 http:// 或 https:// 开头','error');try{console.log('保存缓存启用状态...');const r0=await apiRequest('/api/cache/enabled',{method:'POST',body:JSON.stringify({enabled:enabled})});if(!r0){console.error('保存缓存启用状态请求失败');return}const d0=await r0.json();console.log('缓存启用状态保存结果:',d0);if(!d0.success){console.error('保存缓存启用状态失败:',d0);return showToast('保存缓存启用状态失败','error')}console.log('保存超时时间...');const r1=await apiRequest('/api/cache/config',{method:'POST',body:JSON.stringify({timeout:timeout})});if(!r1){console.error('保存超时时间请求失败');return}const d1=await r1.json();console.log('超时时间保存结果:',d1);if(!d1.success){console.error('保存超时时间失败:',d1);return showToast('保存超时时间失败','error')}console.log('保存域名...');const r2=await apiRequest('/api/cache/base-url',{method:'POST',body:JSON.stringify({base_url:baseUrl})});if(!r2){console.error('保存域名请求失败');return}const d2=await r2.json();console.log('域名保存结果:',d2);if(d2.success){showToast('缓存配置保存成功','success');console.log('等待配置文件写入完成...');await new Promise(r=>setTimeout(r,200));console.log('重新加载配置...');await loadCacheConfig()}else{console.error('保存域名失败:',d2);showToast('保存域名失败','error')}}catch(e){console.error('保存失败:',e);showToast('保存失败: '+e.message,'error')}},
        saveGenerationTimeout=async()=>{const imageTimeout=parseInt($('cfgImageTimeout').value)||300,videoTimeout=parseInt($('cfgVideoTimeout').value)||1500;console.log('保存生成超时配置:',{imageTimeout,videoTimeout});if(imageTimeout<60||imageTimeout>3600)return showToast('图片超时时间必须在 60-3600 秒之间','error');if(videoTimeout<60||videoTimeout>7200)return showToast('视频超时时间必须在 60-7200 秒之间','error');try{const r=await apiRequest('/api/generation/timeout',{method:'POST',body:JSON.stringify({image_timeout:imageTimeout,video_timeout:videoTimeout})});if(!r){console.error('保存请求失败');return}const d=await r.json();console.log('保存结果:',d);if(d.success){showToast('生成超时配置保存成功','success');await new Promise(r=>setTimeout(r,200));await loadGenerationTimeout()}else{console.error('保存失败:',d);showToast('保存失败','error')}}catch(e){console.error('保存失败:',e);showToast('保存失败: '+e.message,'error')}},
        toggleATAutoRefresh=async()=>{try{const enabled=$('atAutoRefreshToggle').checked;const r=await apiRequest('/api/token-refresh/enabled',{method:'POST',body:JSON.stringify({enabled:enabled})});if(!r){$('atAutoRefreshToggle').checked=!enabled;return}const d=await r.json();if(d.success){showToast(enabled?'AT自动刷新已启用':'AT自动刷新已禁用','success')}else{showToast('操作失败: '+(d.detail||'未知错误'),'error');$('atAutoRefreshToggle').checked=!enabled}}catch(e){showToast('操作失败: '+e.message,'error');$('atAutoRefreshToggle').checked=!enabled}},
        loadATAutoRefreshConfig=async()=>{try{const r=await apiRequest('/api/token-refresh/config');if(!r)return;const d=await r.json();if(d.success&&d.config){$('atAutoRefreshToggle').checked=d.config.at_auto_refresh_enabled||false}else{console.error('AT自动刷新配置数据格式错误:',d)}}catch(e){console.error('加载AT自动刷新配置失败:',e)}},
        manualATAutoRefresh=async()=>{const btn=$('btnManualATRefresh');if(btn){btn.disabled=true;btn.textContent='刷新中...';}try{const r=await apiRequest('/api/token-refresh/refresh',{method:'POST'});if(!r){showToast('请求失败','error');return}const d=await r.json();if(d.success){showToast(d.message||'已尝试刷新即将过期的AT','success');await refreshTokens()}else{showToast(d.detail||d.message||'刷新失败','error')}}catch(e){showToast('刷新失败: '+e.message,'error')}finally{if(btn){btn.disabled=false;btn.textContent='手动刷新';}}},
        /* 角色卡 */
        escapeHtml=s=>String(s??'').replace(/[&<>"']/g,(ch)=>({ '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;' }[ch]||ch)),
        escapeAttr=s=>escapeHtml(s).replace(/`/g,'&#96;'),
        defaultAvatar=(()=>{const svg=`<svg xmlns="http://www.w3.org/2000/svg" width="160" height="160" viewBox="0 0 160 160"><defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#60a5fa"/><stop offset="1" stop-color="#6366f1"/></linearGradient></defs><rect width="160" height="160" rx="32" fill="url(#g)"/><path d="M46 118c4-18 18-28 34-28s30 10 34 28" fill="none" stroke="rgba(255,255,255,0.92)" stroke-width="10" stroke-linecap="round"/><circle cx="80" cy="66" r="22" fill="rgba(255,255,255,0.92)"/></svg>`;return `data:image/svg+xml;utf8,${encodeURIComponent(svg)}`})(),
        buildFullUrl=(p)=>{if(!p)return'';if(p.startsWith('http'))return p;return `${location.origin}${p.startsWith('/')?'':'/'}${p}`},
        copyText=async(text)=>{const val=String(text||'');try{await navigator.clipboard.writeText(val);return true}catch(e){try{const ta=document.createElement('textarea');ta.value=val;ta.setAttribute('readonly','');ta.style.position='fixed';ta.style.top='-1000px';ta.style.opacity='0';document.body.appendChild(ta);ta.select();document.execCommand('copy');document.body.removeChild(ta);return true}catch(_){return false}}},
        loadCharacterUi=()=>{try{const raw=localStorage.getItem('characters_ui_v1');if(!raw)return;const s=JSON.parse(raw);if(!s||typeof s!=='object')return;characterUi.query=typeof s.query==='string'?s.query:'';characterUi.sort=typeof s.sort==='string'?s.sort:'newest';characterUi.view=s.view==='list'?'list':'grid'}catch(_){}},
        saveCharacterUi=()=>{try{localStorage.setItem('characters_ui_v1',JSON.stringify({query:characterUi.query||'',sort:characterUi.sort||'newest',view:characterUi.view||'grid'}))}catch(_){}},
        formatCharacterTime=(t)=>{try{return t?new Date(t).toLocaleString('zh-CN'):'-'}catch(_){return'-'}},
        getCharacterName=(c)=>{const n=(c?.display_name||'').trim();return n||c?.username||'角色'},
        normalize=(s)=>String(s||'').toLowerCase().trim(),
        getVisibleCharacters=()=>{const q=normalize(characterUi.query);let list=[...(characterCards||[])];if(q){list=list.filter(c=>{const hay=[getCharacterName(c),c?.username,c?.cameo_id,c?.character_id,c?.description,String(c?.id||'')].filter(Boolean).join(' ').toLowerCase();return hay.includes(q)})}const byName=(a,b)=>getCharacterName(a).localeCompare(getCharacterName(b),'zh-CN',{numeric:true,sensitivity:'base'});const byCreated=(a,b)=>{const ta=Date.parse(a?.created_at||'')||0;const tb=Date.parse(b?.created_at||'')||0;return tb-ta};switch(characterUi.sort){case'oldest':list.sort((a,b)=>-byCreated(a,b));break;case'name_asc':list.sort(byName);break;case'name_desc':list.sort((a,b)=>-byName(a,b));break;case'newest':default:list.sort(byCreated);break}return list},
        updateCharacterToolbar=(visible,total)=>{const count=$('characterCount');if(count){if(!total)count.textContent='0';else if(visible===total)count.textContent=`共 ${total} 个`;else count.textContent=`显示 ${visible} / ${total}`}},
        updateCharacterViewButtons=()=>{const btnGrid=$('characterViewGrid'),btnList=$('characterViewList');if(!btnGrid||!btnList)return;const isGrid=characterUi.view!=='list';const apply=(btn,active)=>{btn.setAttribute('aria-pressed',active?'true':'false');btn.classList.toggle('bg-primary',active);btn.classList.toggle('text-primary-foreground',active);btn.classList.toggle('border-transparent',active);btn.classList.toggle('bg-background/70',!active)};apply(btnGrid,isGrid);apply(btnList,!isGrid)},
        updateCharacterBulkBar=()=>{const bar=$('characterBulkBar');const count=$('characterSelectedCount');if(!bar||!count)return;const n=characterSelectedIds.size||0;count.textContent=String(n);bar.classList.toggle('hidden',n===0)},
        setCharactersEmpty=(mode)=>{const empty=$('characterEmpty');const subtitle=$('characterEmptySubtitle');if(!empty)return;empty.classList.toggle('hidden',mode==='hide');if(subtitle){subtitle.textContent=mode==='nomatch'?'没有匹配的角色卡，试试换个关键词或清空搜索。':'去“生成面板”上传参考视频创建一个角色卡，或稍后刷新。'}},
        renderCharacterSkeleton=(n=8)=>{const grid=$('characterGrid');if(!grid)return;setCharactersEmpty('hide');grid.className='grid gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4';grid.innerHTML=Array.from({length:n}).map((_,i)=>`<div class="cc-enter rounded-2xl border border-border bg-background/70 backdrop-blur p-3 shadow-sm animate-pulse" style="--i:${i}"><div class="flex items-start gap-3"><div class="h-14 w-14 rounded-2xl bg-slate-200"></div><div class="flex-1 space-y-2"><div class="h-4 w-2/3 bg-slate-200 rounded"></div><div class="h-3 w-1/2 bg-slate-200 rounded"></div><div class="h-3 w-3/4 bg-slate-200 rounded"></div></div></div><div class="mt-3 h-8 w-full bg-slate-200 rounded-xl"></div></div>`).join('')},
        renderCharacters=()=>{const grid=$('characterGrid'),empty=$('characterEmpty');if(!grid||!empty)return;const total=characterCards?.length||0;const visibleList=getVisibleCharacters();updateCharacterToolbar(visibleList.length,total);updateCharacterViewButtons();updateCharacterBulkBar();if(!total){grid.innerHTML='';setCharactersEmpty('nocards');return}if(visibleList.length===0){grid.innerHTML='';setCharactersEmpty('nomatch');return}setCharactersEmpty('hide');if(characterUi.view==='list'){grid.className='flex flex-col gap-2';grid.innerHTML=visibleList.map((c,i)=>{const id=Number(c?.id||0);const name=getCharacterName(c);const username=c?.username||'';const avatar=buildFullUrl(c?.avatar_path||'');const avatarSrc=avatar||defaultAvatar;const created=formatCharacterTime(c?.created_at);const selected=characterSelectedIds.has(id);return `<div class="cc-enter cc-focus group relative rounded-xl border border-border bg-background/70 backdrop-blur p-3 shadow-sm hover:shadow-md transition-shadow" style="--i:${i}" data-character-card="1" data-id="${id}" tabindex="0" role="button" aria-label="打开角色卡详情：@${escapeAttr(username)}"><div class="flex items-center gap-3"><button class="cc-btn cc-focus h-8 w-8 rounded-md border ${selected?'bg-primary text-primary-foreground border-transparent':'bg-white/70 text-slate-700 border-border'} backdrop-blur hover:bg-white flex items-center justify-center" type="button" data-action="toggle-select" aria-pressed="${selected?'true':'false'}" title="${selected?'取消选择':'选择'}">${selected?'✓':''}</button><img src="${escapeAttr(avatarSrc)}" class="h-12 w-12 rounded-2xl object-cover border border-border bg-white" alt="${escapeAttr(name)}" loading="lazy" data-role-avatar="1"><div class="min-w-0 flex-1"><div class="flex items-center justify-between gap-2"><div class="min-w-0"><div class="text-sm font-semibold truncate">${escapeHtml(name)}</div><div class="text-xs text-muted-foreground truncate">@${escapeHtml(username||'-')}</div></div><div class="shrink-0 flex items-center gap-2"><button class="cc-btn cc-focus inline-flex items-center justify-center rounded-md border border-input bg-background hover:bg-accent h-8 px-3 text-sm" type="button" data-action="copy-username" data-username="${escapeAttr(username)}">复制</button><button class="cc-btn cc-focus inline-flex items-center justify-center rounded-md bg-destructive text-destructive-foreground hover:bg-destructive/90 h-8 px-3 text-sm" type="button" data-action="delete">删除</button></div></div><div class="mt-1 text-[11px] text-muted-foreground truncate">ID: ${escapeHtml(String(id||'-'))} · 创建：${escapeHtml(created)}</div></div></div></div>`}).join('')}else{grid.className='grid gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4';grid.innerHTML=visibleList.map((c,i)=>{const id=Number(c?.id||0);const name=getCharacterName(c);const username=c?.username||'';const avatar=buildFullUrl(c?.avatar_path||'');const avatarSrc=avatar||defaultAvatar;const created=formatCharacterTime(c?.created_at);const cameo=c?.cameo_id||'';const selected=characterSelectedIds.has(id);const chip=(label,action,val)=>`<button type="button" class="cc-btn cc-focus inline-flex items-center rounded-full border border-border bg-white/70 backdrop-blur px-2 py-0.5 text-xs font-medium text-slate-700 hover:bg-white" data-action="${action}" data-value="${escapeAttr(val)}" title="点击复制">${label}</button>`;return `<div class="cc-enter cc-focus group relative rounded-2xl border border-border bg-background/70 backdrop-blur p-3 shadow-sm hover:shadow-md transition-shadow cursor-pointer" style="--i:${i}" data-character-card="1" data-id="${id}" tabindex="0" role="button" aria-label="打开角色卡详情：@${escapeAttr(username)}"><button class="cc-btn cc-focus absolute right-3 top-3 h-8 w-8 rounded-md border ${selected?'bg-primary text-primary-foreground border-transparent':'bg-white/70 text-slate-700 border-border'} backdrop-blur hover:bg-white flex items-center justify-center" type="button" data-action="toggle-select" aria-pressed="${selected?'true':'false'}" title="${selected?'取消选择':'选择'}">${selected?'✓':''}</button><div class="flex items-start gap-3 pr-10"><img src="${escapeAttr(avatarSrc)}" class="h-14 w-14 rounded-2xl object-cover border border-border bg-white" alt="${escapeAttr(name)}" loading="lazy" data-role-avatar="1"><div class="min-w-0 flex-1"><div class="text-sm font-semibold truncate">${escapeHtml(name)}</div><div class="mt-1 flex flex-wrap items-center gap-1.5">${chip('@'+(username||'-'),'copy','@'+username)}${cameo?chip('cameo_id','copy',cameo):''}</div><div class="mt-1 text-[11px] text-muted-foreground truncate">ID: ${escapeHtml(String(id||'-'))} · 创建：${escapeHtml(created)}</div></div></div><div class="mt-3 flex items-center justify-between gap-2"><div class="flex items-center gap-2"><button class="cc-btn cc-focus inline-flex items-center justify-center rounded-md border border-input bg-background hover:bg-accent h-8 px-3 text-sm" type="button" data-action="copy-username" data-username="${escapeAttr(username)}">复制</button>${avatar?`<button class="cc-btn cc-focus inline-flex items-center justify-center rounded-md border border-input bg-background hover:bg-accent h-8 px-3 text-sm" type="button" data-action="open-url" data-url="${escapeAttr(avatar)}">头像</button>`:''}${c?.source_video?`<button class="cc-btn cc-focus inline-flex items-center justify-center rounded-md border border-input bg-background hover:bg-accent h-8 px-3 text-sm" type="button" data-action="open-url" data-url="${escapeAttr(buildFullUrl(c.source_video))}">来源</button>`:''}</div><button class="cc-btn cc-focus inline-flex items-center justify-center rounded-md bg-destructive text-destructive-foreground hover:bg-destructive/90 h-8 px-3 text-sm" type="button" data-action="delete">删除</button></div></div>`}).join('')}grid.querySelectorAll('img[data-role-avatar=\"1\"]').forEach(img=>{img.addEventListener('error',()=>{img.src=defaultAvatar},{once:true})})},
        openCharacterModal=(id)=>{const modal=$('characterModal');if(!modal)return;const card=(characterCards||[]).find(c=>Number(c?.id||0)===Number(id));if(!card)return;characterUi.modalId=Number(id);const avatar=buildFullUrl(card.avatar_path||'');const avatarSrc=avatar||defaultAvatar;const title=$('characterModalTitle');const sub=$('characterModalSub');const chip=$('characterModalCopyUsernameChip');const img=$('characterModalAvatar');const dn=$('characterModalDisplayName');const cameo=$('characterModalCameoId');const cid=$('characterModalCharacterId');const desc=$('characterModalDesc');if(title)title.textContent=getCharacterName(card);if(sub)sub.textContent=`ID: ${card.id||'-'} · 创建：${formatCharacterTime(card.created_at)}`;if(chip){chip.textContent='@'+(card.username||'-');chip.dataset.username=card.username||'';}if(img){img.src=avatarSrc;img.dataset.url=avatar||'';img.alt=getCharacterName(card);}if(dn){dn.value=card.display_name||'';dn.dataset.id=String(card.id||'');}if(cameo){cameo.textContent=card.cameo_id||'-';}if(cid){cid.textContent=card.character_id||'-';}if(desc){desc.textContent=(card.description||'').trim()||'（无）';}const openSource=$('characterModalOpenSource');const copySource=$('characterModalCopySource');const src=card.source_video?buildFullUrl(card.source_video):'';if(openSource){openSource.disabled=!src;openSource.dataset.url=src;}if(copySource){copySource.disabled=!src;copySource.dataset.url=src;}modal.classList.remove('hidden');modal.setAttribute('aria-hidden','false')},
        closeCharacterModal=()=>{const modal=$('characterModal');if(!modal)return;modal.classList.add('hidden');modal.setAttribute('aria-hidden','true');characterUi.modalId=null},
        updateCharacterDisplayName=async(id,newName)=>{const name=String(newName||'').trim();if(!name){showToast('显示名不能为空','error');return false}try{const r=await apiRequest(`/api/characters/${id}/display_name`,{method:'PUT',body:JSON.stringify({display_name:name})});if(!r){showToast('请求失败','error');return false}const d=await r.json();if(d.success){const idx=(characterCards||[]).findIndex(c=>Number(c?.id||0)===Number(id));if(idx>=0){characterCards[idx].display_name=d.display_name||name}showToast('已保存显示名','success');return true}else{showToast(d.detail||d.message||'保存失败','error');return false}}catch(e){showToast('保存失败: '+e.message,'error');return false}},
        deleteCharacter=async(id)=>{const card=(characterCards||[]).find(c=>Number(c?.id||0)===Number(id));const label=card?`${getCharacterName(card)} (@${card.username||'-'})`:String(id);if(!id)return showToast('ID 无效','error');if(!confirmStep('delete_character_'+id,`再次点击确认删除角色卡：${label}\n（同时会删除本地头像文件）`,{ttl:6500,type:'warn'}))return;try{const r=await apiRequest(`/api/characters/${id}`,{method:'DELETE'});if(!r)return;const d=await r.json();if(d.success){characterSelectedIds.delete(Number(id));if(characterUi.modalId===Number(id))closeCharacterModal();showToast('删除成功','success');await loadCharacters()}else{showToast('删除失败','error')}}catch(e){showToast('删除失败: '+e.message,'error')}},
        loadCharacters=async()=>{renderCharacterSkeleton(8);try{const r=await apiRequest('/api/characters');if(!r)return;const d=await r.json();characterCards=Array.isArray(d)?d:[];renderCharacters()}catch(e){console.error('加载角色卡失败:',e);showToast('加载角色卡失败: '+e.message,'error');characterCards=[];renderCharacters()}},
        refreshCharacters=async()=>{await loadCharacters()},
        initCharactersUi=()=>{if(charactersUiInited)return;charactersUiInited=true;loadCharacterUi();updateCharacterViewButtons();const search=$('characterSearch');const sort=$('characterSort');const btnGrid=$('characterViewGrid');const btnList=$('characterViewList');const btnRefresh=$('characterRefreshBtn');const btnEmptyRefresh=$('characterEmptyRefreshBtn');const btnGoGenerate=$('characterGoGenerateBtn');const btnClear=$('characterSearchClear');const bulkCopy=$('characterBulkCopy');const bulkClear=$('characterBulkClear');if(search){search.value=characterUi.query||'';const syncClear=()=>{if(btnClear)btnClear.classList.toggle('hidden',!search.value)};syncClear();search.addEventListener('input',()=>{characterUi.query=search.value||'';saveCharacterUi();syncClear();renderCharacters()});search.addEventListener('keydown',(e)=>{if(e.key==='Escape'){search.value='';characterUi.query='';saveCharacterUi();syncClear();renderCharacters();search.blur();}});}
            if(btnClear&&search){btnClear.addEventListener('click',()=>{search.value='';characterUi.query='';saveCharacterUi();btnClear.classList.add('hidden');renderCharacters();search.focus();})}
            if(sort){sort.value=characterUi.sort||'newest';sort.addEventListener('change',()=>{characterUi.sort=sort.value||'newest';saveCharacterUi();renderCharacters()})}
            if(btnGrid)btnGrid.addEventListener('click',()=>{characterUi.view='grid';saveCharacterUi();updateCharacterViewButtons();renderCharacters()});
            if(btnList)btnList.addEventListener('click',()=>{characterUi.view='list';saveCharacterUi();updateCharacterViewButtons();renderCharacters()});
            if(btnRefresh)btnRefresh.addEventListener('click',()=>refreshCharacters());
            if(btnEmptyRefresh)btnEmptyRefresh.addEventListener('click',()=>refreshCharacters());
            if(btnGoGenerate)btnGoGenerate.addEventListener('click',()=>switchTab('generate'));
            if(bulkCopy)bulkCopy.addEventListener('click',async()=>{const ids=[...characterSelectedIds.values()];if(!ids.length)return;const names=ids.map(id=>{const c=(characterCards||[]).find(x=>Number(x?.id||0)===Number(id));return c?.username?`@${c.username}`:''}).filter(Boolean);if(!names.length)return showToast('没有可复制的 @username','error');const ok=await copyText(names.join(' '));showToast(ok?`已复制 ${names.length} 个 @username`:'复制失败','info')});
            if(bulkClear)bulkClear.addEventListener('click',()=>{characterSelectedIds.clear();updateCharacterBulkBar();renderCharacters()});
            const grid=$('characterGrid');if(grid){grid.addEventListener('click',async(e)=>{const actionEl=e.target.closest('[data-action]');const cardEl=e.target.closest('[data-character-card=\"1\"]');const id=cardEl?Number(cardEl.dataset.id||0):0;if(actionEl){const action=actionEl.dataset.action; if(action==='toggle-select'){if(!id)return; if(characterSelectedIds.has(id))characterSelectedIds.delete(id); else characterSelectedIds.add(id); updateCharacterBulkBar(); renderCharacters(); return;} if(action==='delete'){if(!id)return; await deleteCharacter(id); return;} if(action==='open-url'){const url=actionEl.dataset.url||''; if(url) window.open(url,'_blank'); else showToast('链接为空','error'); return;} if(action==='copy'){const v=actionEl.dataset.value||''; if(!v) return showToast('内容为空','error'); const ok=await copyText(v); showToast(ok?'已复制':'复制失败',ok?'success':'error'); return;} if(action==='copy-username'){const u=actionEl.dataset.username||''; if(!u) return showToast('用户名为空','error'); const ok=await copyText('@'+u); showToast(ok?('已复制 @'+u):'复制失败',ok?'success':'error'); return;} } if(cardEl&&id){openCharacterModal(id)}});grid.addEventListener('keydown',(e)=>{if(e.key!=='Enter'&&e.key!==' ')return;const cardEl=e.target.closest('[data-character-card=\"1\"]');if(!cardEl)return;e.preventDefault();const id=Number(cardEl.dataset.id||0);if(id)openCharacterModal(id)})}
            const overlay=$('characterModalOverlay');const closeBtn=$('characterModalClose');if(overlay)overlay.addEventListener('click',closeCharacterModal);if(closeBtn)closeBtn.addEventListener('click',closeCharacterModal);document.addEventListener('keydown',(e)=>{const modal=$('characterModal');if(!modal||modal.classList.contains('hidden'))return;if(e.key==='Escape'){e.preventDefault();closeCharacterModal();}});
            const chip=$('characterModalCopyUsernameChip');if(chip)chip.addEventListener('click',async()=>{const u=chip.dataset.username||'';if(!u)return;const ok=await copyText('@'+u);showToast(ok?('已复制 @'+u):'复制失败',ok?'success':'error')});
            const openAvatar=$('characterModalOpenAvatar');const copyAvatar=$('characterModalCopyAvatar');const modalImg=$('characterModalAvatar');if(openAvatar&&modalImg)openAvatar.addEventListener('click',()=>{const url=modalImg.dataset.url||'';if(url)window.open(url,'_blank');else showToast('没有可打开的头像链接','error')});if(copyAvatar&&modalImg)copyAvatar.addEventListener('click',async()=>{const url=modalImg.dataset.url||'';if(!url)return showToast('没有可复制的头像链接','error');const ok=await copyText(url);showToast(ok?'已复制头像链接':'复制失败',ok?'success':'error')});
            const saveName=$('characterModalSaveName');const dn=$('characterModalDisplayName');if(saveName&&dn){const doSave=async()=>{const id=Number(dn.dataset.id||characterUi.modalId||0);if(!id)return;saveName.disabled=true;saveName.textContent='保存中';try{const ok=await updateCharacterDisplayName(id,dn.value);if(ok){renderCharacters();openCharacterModal(id)}}finally{saveName.disabled=false;saveName.textContent='保存'}};saveName.addEventListener('click',doSave);dn.addEventListener('keydown',(e)=>{if(e.key==='Enter'){e.preventDefault();doSave()}else if(e.key==='Escape'){e.preventDefault();openCharacterModal(Number(dn.dataset.id||characterUi.modalId||0));dn.blur();}})}
            const copyCameo=$('characterModalCopyCameoId');const copyChar=$('characterModalCopyCharacterId');if(copyCameo)copyCameo.addEventListener('click',async()=>{const v=($('characterModalCameoId')?.textContent||'').trim();if(!v||v==='-')return showToast('Cameo ID 为空','error');const ok=await copyText(v);showToast(ok?'已复制 Cameo ID':'复制失败',ok?'success':'error')});if(copyChar)copyChar.addEventListener('click',async()=>{const v=($('characterModalCharacterId')?.textContent||'').trim();if(!v||v==='-')return showToast('Character ID 为空','error');const ok=await copyText(v);showToast(ok?'已复制 Character ID':'复制失败',ok?'success':'error')});
            const openSource=$('characterModalOpenSource');const copySource=$('characterModalCopySource');if(openSource)openSource.addEventListener('click',()=>{const url=openSource.dataset.url||'';if(url)window.open(url,'_blank');else showToast('来源为空','error')});if(copySource)copySource.addEventListener('click',async()=>{const url=copySource.dataset.url||'';if(!url)return showToast('来源为空','error');const ok=await copyText(url);showToast(ok?'已复制来源':'复制失败',ok?'success':'error')});
            const del=$('characterModalDelete');if(del)del.addEventListener('click',async()=>{const id=Number(characterUi.modalId||0);if(!id)return;await deleteCharacter(id)});
            renderCharacters()},
        /* 日志 */
        loadLogs=async()=>{try{const r=await apiRequest('/api/logs?limit=100');if(!r)return;const logs=await r.json();const tb=$('logsTableBody');tb.innerHTML=logs.map(l=>`<tr><td class="py-2.5 px-3">${l.operation}</td><td class="py-2.5 px-3"><span class="text-xs ${l.token_email?'text-blue-600':'text-muted-foreground'}">${l.token_email||'未知'}</span></td><td class="py-2.5 px-3"><span class="inline-flex items-center rounded px-2 py-0.5 text-xs ${l.status_code===200?'bg-green-50 text-green-700':'bg-red-50 text-red-700'}">${l.status_code}</span></td><td class="py-2.5 px-3">${l.duration.toFixed(2)}</td><td class="py-2.5 px-3 text-xs text-muted-foreground">${l.created_at?new Date(l.created_at).toLocaleString('zh-CN'):'-'}</td></tr>`).join('')}catch(e){console.error('加载日志失败:',e)}},
        refreshLogs=async()=>{await loadLogs()},
        showToast=(m,t='info',opts={})=>{const d=document.createElement('div'),bc={success:'bg-green-600',error:'bg-destructive',warn:'bg-amber-500',info:'bg-primary'};d.className=`fixed bottom-4 right-4 ${bc[t]||bc.info} text-white px-4 py-2.5 rounded-lg shadow-lg text-sm font-medium z-50 animate-slide-up`;d.textContent=m;document.body.appendChild(d);const dur=typeof opts.duration==='number'?opts.duration:(t==='error'?2600:2000);setTimeout(()=>{d.style.opacity='0';d.style.transition='opacity .3s';setTimeout(()=>d.parentNode&&document.body.removeChild(d),300)},dur)},
        _confirmStepStore=new Map(),
        confirmStep=(key,msg,opts={})=>{const k=String(key||'');const now=Date.now();const ttl=typeof opts.ttl==='number'?opts.ttl:5200;const last=_confirmStepStore.get(k);if(last&&now-last<ttl){_confirmStepStore.delete(k);return true}_confirmStepStore.set(k,now);const type=opts.type==='warn'?'warn':opts.type==='error'?'error':opts.type==='success'?'success':'info';showToast(String(msg||'再次点击确认'),type,{duration:typeof opts.duration==='number'?opts.duration:Math.min(ttl,6200)});setTimeout(()=>{try{if(_confirmStepStore.get(k)===now)_confirmStepStore.delete(k)}catch(_){}},ttl+80);return false},
        logout=()=>{if(!confirmStep('logout','再次点击确认退出登录',{ttl:4200,type:'warn'}))return;localStorage.removeItem('adminToken');location.href='/login'},
        switchTab=t=>{const cap=n=>n.charAt(0).toUpperCase()+n.slice(1);['tokens','settings','logs','generate','characters'].forEach(n=>{const active=n===t;$(`panel${cap(n)}`).classList.toggle('hidden',!active);$(`tab${cap(n)}`).classList.toggle('border-primary',active);$(`tab${cap(n)}`).classList.toggle('text-primary',active);$(`tab${cap(n)}`).classList.toggle('border-transparent',!active);$(`tab${cap(n)}`).classList.toggle('text-muted-foreground',!active)});const genPanel=$('panelGenerate');if(genPanel){genPanel.classList.toggle('full-bleed-panel',t==='generate');}localStorage.setItem('manage_active_tab',t);if(t==='settings'){loadAdminConfig();loadProxyConfig();loadWatermarkFreeConfig();loadCacheConfig();loadGenerationTimeout();loadATAutoRefreshConfig()}else if(t==='logs'){loadLogs()}else if(t==='characters'){refreshCharacters()}};
        window.addEventListener('DOMContentLoaded',()=>{checkAuth();initCharactersUi();const savedTab=localStorage.getItem('manage_active_tab');const initialTab=savedTab||'tokens';switchTab(initialTab);refreshTokens();loadATAutoRefreshConfig();});

        /* 全局任务球：接收子页面消息（生成面板 iframe -> 管理页） */
        let globalTasks=[];
        let taskDrawerOpen=false;
        let taskDrawerFilter='all'; // all | running | error | done
        let taskDrawerSearch='';
        let lastTaskSignature='';

        const normalizeText=s=>String(s||'').toLowerCase().trim();
        const isRunningStatus=s=>s==='running'||s==='queue';
        const statusLabel=s=>({queue:'排队中',running:'生成中',done:'已完成',error:'失败',stalled:'中断'}[s]||String(s||''));
        const statusPillClass=s=>{
          const base='inline-flex items-center rounded-full px-2 py-0.5 text-xs font-semibold border';
          if(isRunningStatus(s)) return `${base} bg-blue-50 text-blue-700 border-blue-200`;
          if(s==='error') return `${base} bg-red-50 text-red-700 border-red-200`;
          if(s==='stalled') return `${base} bg-amber-50 text-amber-700 border-amber-200`;
          if(s==='done') return `${base} bg-green-50 text-green-700 border-green-200`;
          return `${base} bg-slate-100 text-slate-700 border-slate-200`;
        };
        const safeText=s=>String(s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/\"/g,'&quot;').replace(/'/g,'&#39;');
        const metaText=t=>{
          if(!t||!t.meta) return '';
          const m=t.meta;
          if(typeof m==='string') return m;
          const res=m.resolution||m.width&&m.height?`${m.width}x${m.height}`:'';
          const dur=m.duration||m.length?`${m.length}`:'';
          const info=m.info||m.display||'';
          return [res,dur,info].filter(Boolean).join(' · ');
        };
        const getCounts=()=>{
          const total=(globalTasks||[]).length;
          const running=(globalTasks||[]).filter(t=>isRunningStatus(t.status)).length;
          const error=(globalTasks||[]).filter(t=>t.status==='error').length;
          const done=(globalTasks||[]).filter(t=>t.status==='done').length;
          return {total,running,error,done};
        };
        const getGenerateWin=()=>{
          const frame=document.getElementById('generateFrame');
          return frame&&frame.contentWindow?frame.contentWindow:null;
        };
        const postToGenerate=(payload)=>{
          try{const w=getGenerateWin();if(w)w.postMessage(payload,'*')}catch(_){}
        };

        const setBubbleState=(running,total)=>{
          const bubble=document.getElementById('globalTaskBubble');
          const bubbleCount=document.getElementById('globalTaskBubbleCount');
          const bubbleErr=document.getElementById('globalTaskBubbleError');
          if(!bubble) return;

          const showCount=running>0?running:total;
          if(showCount>0){
            if(bubbleCount) bubbleCount.textContent=String(showCount);
            bubble.dataset.running=running>0?'1':'0';
            bubble.title=running>0?`有 ${running} 个任务运行中`:`共有 ${total} 个任务记录`;
            bubble.setAttribute('aria-label',bubble.title);
            bubble.setAttribute('aria-expanded',taskDrawerOpen?'true':'false');
            bubble.classList.remove('hidden');
          }else{
            bubble.classList.add('hidden');
            bubble.dataset.running='0';
            bubble.setAttribute('aria-expanded','false');
          }

          // 错误角标：来自 task_state（更可靠）
          if(bubbleErr){
            const {error}=getCounts();
            if(error>0){
              bubbleErr.textContent=String(Math.min(99,error));
              bubbleErr.classList.remove('hidden');
            }else{
              bubbleErr.classList.add('hidden');
            }
          }
        };

        const syncFilterPills=()=>{
          const pills=Array.from(document.querySelectorAll('.task-filter-pill'));
          pills.forEach(btn=>{
            const f=btn.getAttribute('data-filter')||'all';
            const active=f===taskDrawerFilter;
            btn.classList.toggle('bg-primary',active);
            btn.classList.toggle('text-white',active);
            btn.classList.toggle('border-transparent',active);
            btn.classList.toggle('bg-white/80',!active);
          });
        };

        const renderTaskDrawer=()=>{
          const drawer=document.getElementById('taskDrawer');
          const list=document.getElementById('taskDrawerList');
          const summary=document.getElementById('taskDrawerSummary');
          if(!drawer||!list) return;

          const {total,running,error,done}=getCounts();
          if(summary){
            summary.textContent=`运行中 ${running} · 错误 ${error} · 已完成 ${done} · 共 ${total}`;
          }

          const q=normalizeText(taskDrawerSearch);
          const matches=(t)=>{
            if(taskDrawerFilter==='running'&&!isRunningStatus(t.status)) return false;
            if(taskDrawerFilter==='error'&&t.status!=='error') return false;
            if(taskDrawerFilter==='done'&&t.status!=='done') return false;
            if(!q) return true;
            const hay=[t.prompt,t.message,String(t.id||''),metaText(t)].filter(Boolean).join(' ').toLowerCase();
            return hay.includes(q);
          };

          const order=(s)=>isRunningStatus(s)?0:s==='error'?1:s==='stalled'?2:s==='done'?3:9;
          const items=(globalTasks||[]).slice().filter(matches).sort((a,b)=>{
            const oa=order(a.status),ob=order(b.status);
            if(oa!==ob) return oa-ob;
            const ia=parseInt(a.id||0,10)||0;
            const ib=parseInt(b.id||0,10)||0;
            return ib-ia;
          });

          if(!items.length){
            list.innerHTML=`
              <div class="rounded-xl border border-slate-200/70 bg-white/70 backdrop-blur p-4 text-sm text-slate-600">
                暂无任务（或当前筛选/搜索没有匹配项）。
              </div>
            `;
            syncFilterPills();
            return;
          }

          list.innerHTML=items.map(t=>{
            const title=safeText(t.prompt||`任务 ${t.id||''}`||'-');
            const st=safeText(statusLabel(t.status));
            const stRaw=safeText(t.status||'');
            const meta=safeText(metaText(t));
            const msg=t.message?safeText(t.message):'';
            const url=t.url?String(t.url):'';
            const safeUrl=safeText(url);
            const progress=Math.max(0,Math.min(100,parseFloat(t.progress||0)||0));
            const showProgress=isRunningStatus(t.status)&&progress>0&&progress<100;
            const sb=t.storyboard&&t.storyboard.label?safeText(String(t.storyboard.label)):'';
            const sbChip=sb?`<span class="inline-flex items-center rounded-full px-2 py-0.5 text-xs font-semibold border bg-indigo-50 text-indigo-700 border-indigo-200">${sb}</span>`:'';
            return `
              <div class="group rounded-2xl border border-slate-200/70 bg-white/70 backdrop-blur p-3 shadow-sm hover:shadow-md transition cursor-pointer" data-task-row="1" data-task-id="${safeText(String(t.id||''))}">
                <div class="flex items-start justify-between gap-3">
                  <div class="min-w-0 flex-1">
                    <div class="flex items-center gap-2 flex-wrap">
                      <div class="text-sm font-semibold truncate">${title}</div>
                      ${sbChip}
                    </div>
                    <div class="text-xs text-slate-500 mt-1">
                      任务 #${safeText(String(t.id||''))}${meta?` · ${meta}`:''}
                    </div>
                  </div>
                  <span class="${statusPillClass(stRaw)}">${st}</span>
                </div>
                ${msg?`<div class="mt-2 text-xs ${t.status==='error'?'text-red-600':'text-slate-600'}">${msg}</div>`:''}
                ${showProgress?`
                  <div class="mt-2">
                    <div class="h-2 rounded-full bg-slate-200 overflow-hidden" role="progressbar" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${progress}">
                      <div class="h-full bg-gradient-to-r from-blue-600 to-indigo-600" style="width:${progress}%;"></div>
                    </div>
                    <div class="mt-1 text-[11px] text-slate-500">进度 ${progress}%</div>
                  </div>
                `:''}
                <div class="mt-3 flex items-center justify-end gap-2 flex-wrap">
                  ${url?`<button class="inline-flex items-center justify-center rounded-md border border-slate-200 bg-white hover:bg-slate-50 h-8 px-3 text-xs" data-action="open" data-url="${safeUrl}" data-task-id="${safeText(String(t.id||''))}">查看</button>`:''}
                  ${url?`<button class="inline-flex items-center justify-center rounded-md border border-slate-200 bg-white hover:bg-slate-50 h-8 px-3 text-xs" data-action="external" data-url="${safeUrl}">外链</button>`:''}
                  ${url?`<button class="inline-flex items-center justify-center rounded-md border border-slate-200 bg-white hover:bg-slate-50 h-8 px-3 text-xs" data-action="copy" data-url="${safeUrl}">复制链接</button>`:''}
                  <button class="inline-flex items-center justify-center rounded-md border border-slate-200 bg-white hover:bg-slate-50 h-8 px-3 text-xs" data-action="locate" data-task-id="${safeText(String(t.id||''))}">定位任务</button>
                </div>
              </div>
            `;
          }).join('');

          // Bind per-item actions (simple & robust for self-hosted UI)
          list.querySelectorAll('[data-action=\"open\"]').forEach(btn=>{
            btn.addEventListener('click',(e)=>{
              e.stopPropagation();
              const url=btn.getAttribute('data-url')||'';
              const taskId=parseInt(btn.getAttribute('data-task-id')||'0',10)||0;
              // 在生成面板里打开预览（更一致）
              switchTab('generate');
              hideDrawer();
              setTimeout(()=>{
                postToGenerate({type:'open_preview',url,taskId});
              },120);
            });
          });
          list.querySelectorAll('[data-action=\"external\"]').forEach(btn=>{
            btn.addEventListener('click',(e)=>{
              e.stopPropagation();
              const url=btn.getAttribute('data-url')||'';
              if(url) window.open(url,'_blank','noopener');
            });
          });
          list.querySelectorAll('[data-action=\"copy\"]').forEach(btn=>{
            btn.addEventListener('click',async(e)=>{
              e.stopPropagation();
              const url=btn.getAttribute('data-url')||'';
              const ok=await copyText(url);
              showToast(ok?'已复制链接':'复制失败',ok?'success':'error');
            });
          });
          list.querySelectorAll('[data-action=\"locate\"]').forEach(btn=>{
            btn.addEventListener('click',(e)=>{
              e.stopPropagation();
              const id=parseInt(btn.getAttribute('data-task-id')||'0',10)||0;
              if(!id) return;
              switchTab('generate');
              hideDrawer();
              setTimeout(()=>postToGenerate({type:'focus_task',id}),120);
            });
          });
          list.querySelectorAll('[data-task-row=\"1\"]').forEach(row=>{
            row.addEventListener('click',()=>{
              const id=parseInt(row.getAttribute('data-task-id')||'0',10)||0;
              if(!id) return;
              switchTab('generate');
              hideDrawer();
              setTimeout(()=>postToGenerate({type:'focus_task',id}),120);
            });
          });

          syncFilterPills();
        };

        const showDrawer=()=>{
          const drawer=document.getElementById('taskDrawer');
          if(!drawer) return;
          taskDrawerOpen=true;
          drawer.classList.remove('hidden');
          // display:none -> visible 的同一帧直接加 open 可能不触发过渡；用 rAF 保证动画稳定
          requestAnimationFrame(()=>drawer.classList.add('open'));
          drawer.setAttribute('aria-hidden','false');
          const bubble=document.getElementById('globalTaskBubble');
          if(bubble) bubble.setAttribute('aria-expanded','true');
          renderTaskDrawer();
          const search=document.getElementById('taskDrawerSearch');
          if(search){try{search.focus({preventScroll:true})}catch(_){search.focus()}}
        };
        const hideDrawer=()=>{
          const drawer=document.getElementById('taskDrawer');
          if(!drawer) return;
          taskDrawerOpen=false;
          drawer.classList.remove('open');
          drawer.setAttribute('aria-hidden','true');
          const bubble=document.getElementById('globalTaskBubble');
          if(bubble) bubble.setAttribute('aria-expanded','false');
          // 等动画结束再 hidden
          setTimeout(()=>drawer.classList.add('hidden'),230);
        };

        // 消息监听（来自 generate.html iframe）
        window.addEventListener('message',e=>{try{const d=e.data||{};if(d.type==='task_count'){const running=parseInt(d.running||0,10)||0;const total=parseInt(d.total||0,10)||0;setBubbleState(running,total)}else if(d.type==='task_state'){const next=Array.isArray(d.tasks)?d.tasks:[];const sig=next.map(t=>`${t.id}:${t.status}:${t.url?'1':'0'}`).join('|');const changed=sig&&sig!==lastTaskSignature;lastTaskSignature=sig;globalTasks=next;renderTaskDrawer();const counts=getCounts();setBubbleState(counts.running,counts.total);if(changed&&!taskDrawerOpen){const bubble=document.getElementById('globalTaskBubble');if(bubble){bubble.classList.remove('flash');void bubble.offsetWidth;bubble.classList.add('flash');setTimeout(()=>bubble.classList.remove('flash'),600)}}}}catch(_){}});

        // 交互绑定：任务球、抽屉
        const bubble=document.getElementById('globalTaskBubble');
        if(bubble){
          bubble.addEventListener('click',showDrawer);
          bubble.addEventListener('keydown',(e)=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();showDrawer()}});
        }
        const drawerClose=document.getElementById('taskDrawerClose');
        const drawerCloseBtn=document.getElementById('taskDrawerCloseBtn');
        const drawerGoGenerate=document.getElementById('taskDrawerGoGenerate');
        if(drawerClose) drawerClose.addEventListener('click',hideDrawer);
        if(drawerCloseBtn) drawerCloseBtn.addEventListener('click',hideDrawer);
        if(drawerGoGenerate) drawerGoGenerate.addEventListener('click',()=>{switchTab('generate');});
        const search=document.getElementById('taskDrawerSearch');
        if(search) search.addEventListener('input',()=>{taskDrawerSearch=search.value||'';renderTaskDrawer();});
        document.querySelectorAll('.task-filter-pill').forEach(btn=>{
          btn.addEventListener('click',()=>{taskDrawerFilter=btn.getAttribute('data-filter')||'all';renderTaskDrawer();});
        });
        document.addEventListener('keydown',(e)=>{
          const drawer=document.getElementById('taskDrawer');
          if(!drawer||drawer.classList.contains('hidden')) return;
          if(e.key==='Escape'){e.preventDefault();hideDrawer();}
        });
    
