(() => {
  const $ = id => document.getElementById(`agent-${id}`);
  let session = null, busy = false, upload = null, stopAt = null, activeSeconds = 0, lastActivity = Date.now(), cardsVersion = '';
  const pending = new Map(), drafts = new Map();
  let rows = [], reviewOpen = false, sideOpen = false, returnFocus = null, observedSession = null, observedCandidates = new Set();
  const compact = () => matchMedia('(max-width:1099px)').matches;
  function panels(review=false, side=false, restore=false) {
    if (!reviewOpen && !sideOpen && (review || side)) returnFocus=document.activeElement;
    reviewOpen=review; sideOpen=side;
    $('review').hidden=!review; $('sidebar').dataset.open=String(side);
    $('overlay').dataset.open=String(side || (review && compact()));
    $('review-toggle').setAttribute('aria-expanded',String(review));
    $('side-toggle').setAttribute('aria-expanded',String(side));
    if(restore && returnFocus?.isConnected)returnFocus.focus();
    else if(side)$('side-close').focus();
    else if(review && compact())$('review-close').focus();
  }
  function resizeComposer(){const t=$('feedback');t.style.height='auto';t.style.height=Math.min(160,t.scrollHeight)+'px';}
  function drawList(){
    const query=$('search').value.toLocaleLowerCase();
    $('list').innerHTML=rows.filter(s=>(s.brief||'').toLocaleLowerCase().includes(query)).map(s=>`<button class="btn ghost" data-session="${esc(s.id)}" ${s.id===session?.id?'aria-current="true"':''} title="${esc(s.brief)}"><span class="agent-session-name">${esc(s.brief)}</span><small>${esc(label(s.status))}</small></button>`).join('') || '<p class="sub">Tidak ada sesi.</p>';
    $('list').querySelectorAll('button').forEach(b=>b.onclick=()=>{panels();location.hash=b.dataset.session;});
  }
  let renderSelection = new Set(), selectionSession = null;
  const active = () => session && ['queued','preparing','thinking','cancelling'].includes(session.status);
  const fail = error => { $('error').textContent = error.message; $('error').hidden = false; };
  const label = s => ({queued:'Dalam antrean',preparing:'Menyiapkan sumber',thinking:'Meninjau',cancelling:'Membatalkan',cancelled:'Dibatalkan',ready:'Siap ditinjau',failed:'Perlu dicoba ulang',kept:'Dipertahankan',rejected:'Ditolak',pending:'Belum dipilih'}[s]||s);
  const time = n => `${Math.floor(n/60)}:${(n%60).toFixed(1).padStart(4,'0')}`;
  async function api(path, method='GET', body) {
    const response = await fetch(path, {method, headers: body ? {'Content-Type':'application/json'} : {}, body: body ? JSON.stringify(body) : undefined});
    const data = response.status === 204 ? null : await response.json();
    if (!response.ok) {
      const error = Error(Array.isArray(data.detail) ? data.detail.map(x=>x.msg).join('; ') : data.detail || 'Permintaan gagal');
      error.status = response.status; throw error;
    }
    return data;
  }
  async function listing() {
    rows = await api('/api/agent/sessions'); drawList();
  }
  function draw() {
    if (!session) return;
    $('create').hidden = true; $('session').hidden = false;
    $('title').textContent=session.source_title || rows.find(r=>r.id===session.id)?.brief || 'Video';
    $('menu').hidden=false; $('review-toggle').hidden=false;
    $('review-toggle').textContent=`Tinjau klip (${session.candidates.length})`;
    const preparing=!session.source_ready, running=active(), progress=session.progress||'';
    const area=$('chat-scroll'), follow=area.scrollHeight-area.scrollTop-area.clientHeight<80;
    $('progress').hidden=!running;
    $('chat').hidden=preparing;
    $('next').hidden=preparing || running || session.messages.some(m=>m.role==='user');
    $('progress-title').textContent=session.status==='cancelling'?'Membatalkan operasi':session.status==='queued'?'Menunggu giliran':preparing?'Menyiapkan videomu':'Agent sedang meninjau arahanmu';
    $('progress-detail').textContent=progress || (preparing?'Video akan disiapkan sebelum kamu mulai memberi arahan.':'Mencari bagian yang sesuai dan memeriksa konteksnya.');
    $('progress-hint').textContent=preparing?'Setelah siap, kamu bisa memberi arahan lewat chat. Video panjang bisa memerlukan beberapa menit. Kamu boleh menutup halaman dan kembali ke sesi ini.':'Tunggu jawaban Agent sebelum mengirim arahan berikutnya. Kandidat yang sudah dipertahankan tetap tersimpan.';
    const stage=session.status==='queued'?-1:!session.source_ready?(/transkrip/i.test(progress)?1:/preview/i.test(progress)?2:0):3;
    const steps=['Menyiapkan video','Membuat transkrip','Menyiapkan preview','Membaca isi dan merangkum sumber'];
    $('steps').hidden=!preparing && session.messages.some(m=>m.role==='user');
    $('progress-details').hidden=$('steps').hidden;
    $('progress-hint').hidden=!preparing;
    $('steps').innerHTML=steps.map((text,i)=>`<li data-stage="${i<stage?'done':i===stage?'current':'waiting'}"><span class="agent-step-dot">${i<stage?'✓':i+1}</span>${text}</li>`).join('');
    $('feedback').disabled=busy || active() || !session.source_ready;
    $('suggestions').hidden=!session.source_ready || active() || session.messages.some(m=>m.role==='user');
    if(observedSession!==session.id){observedSession=session.id;observedCandidates=new Set(session.candidates.map(c=>c.id));panels();}
    else if(!active() && session.candidates.some(c=>!observedCandidates.has(c.id))){panels(true);observedCandidates=new Set(session.candidates.map(c=>c.id));}
    if(!active())observedCandidates=new Set(session.candidates.map(c=>c.id));
    const row=rows.find(r=>r.id===session.id);if(row){row.status=session.status;if(session.source_title)row.brief=session.source_title;}drawList();
    $('state').textContent = `${label(session.status)} · ${session.progress || 'Menunggu worker'}`;
    $('model').textContent = `Model ${session.model}`;
    $('failure').hidden = !session.error; $('failure').textContent = session.error || '';
    $('cancel').hidden = !active(); $('cancel').disabled = busy || session.status === 'cancelling';
    $('retry').hidden = !['failed','cancelled'].includes(session.status); $('retry').disabled = busy;
    $('delete').disabled = busy || active(); $('send').disabled = busy || active() || !session.source_ready;
    const kept = session.candidates.filter(c=>c.decision==='kept');
    if(selectionSession!==session.id){selectionSession=session.id;renderSelection=new Set(kept.slice(0,20).map(c=>c.id));}
    renderSelection=new Set([...renderSelection].filter(id=>kept.some(c=>c.id===id)));
    function renderLink(){
      $('render').hidden = !renderSelection.size || active() || busy;
      $('render').href = `/agent/${session.id}/render?` + new URLSearchParams([...renderSelection].map(id=>['candidate_ids',id]));
      $('render').textContent = `Render ${renderSelection.size} pilihan`;
    }
    renderLink();
    const overview=session.overview||{}, editorial=session.editorial||{}, latestDirection=[...session.messages].reverse().find(m=>m.role==='user');
    const knowledgeHTML=`<h3>Isi sumber ${overview.partial?'· Ringkasan parsial':''}</h3><p>${esc(overview.summary||overview.warning||'Ringkasan dibuat setelah sumber siap.')}</p>${(overview.topics||[]).map(t=>`<p><button class="btn sm ghost" data-topic="${t.start}">${time(t.start)}–${time(t.end)}</button> <strong>${esc(t.title)}</strong> ${esc(t.summary)}</p>`).join('')}<h3>Pemahaman Agent terakhir</h3>${latestDirection?`<details><summary>Arahan pengguna terbaru</summary><p>${esc(latestDirection.text)}</p></details>`:''}${latestDirection&&['failed','cancelled'].includes(session.status)?'<p class="sub">Arahan terbaru belum selesai diproses; pemahaman di bawah berasal dari putaran terakhir yang selesai.</p>':''}<p>${esc(editorial.understanding||'Sampaikan momen atau pesan yang ingin ditonjolkan melalui chat.')}</p>${(editorial.rules||[]).map(r=>`<p>• ${esc(r.text)}</p>`).join('')}${['assumptions','unknowns'].map(k=>(editorial[k]||[]).length?`<p><strong>${k==='assumptions'?'Asumsi Agent':'Belum diketahui'}:</strong> ${editorial[k].map(esc).join('; ')}</p>`:'').join('')}`;
    if($('knowledge').dataset.version!==String(session.version)){const opened=[...$('knowledge').querySelectorAll('details')].map(d=>d.open);$('knowledge').innerHTML=knowledgeHTML;$('knowledge').querySelectorAll('details').forEach((d,i)=>d.open=!!opened[i]);$('knowledge').dataset.version=String(session.version);}
    $('knowledge').querySelectorAll('[data-topic]').forEach(b=>b.onclick=()=>{stopAt=null;$('video').currentTime=Number(b.dataset.topic);$('video').play().catch(fail);});
    const chat = session.messages.map(m=>`<article class="agent-message" data-role="${esc(m.role)}"><strong>${m.role==='user'?'Editor':'Agent'}</strong><p>${esc(m.text)}</p>${(m.recommendations||[]).map(r=>`<div class="agent-recommendation"><strong>${esc(r.title)}</strong><p>${esc(r.reason)}</p><small>${time(r.start)}–${time(r.end)} · Sudut untuk dieksplorasi, belum siap render</small><button class="btn sm ghost" data-angle="${esc(r.title)}">Cari klip dari sudut ini</button></div>`).join('')}</article>`).join('');
    if ($('messages').innerHTML !== chat) {const area=$('chat-scroll'), bottom=area.scrollHeight-area.scrollTop-area.clientHeight<80; const position=area.scrollTop; $('messages').innerHTML=chat;area.scrollTop=bottom?area.scrollHeight:position;}
    $('messages').querySelectorAll('[data-angle]').forEach(b=>{b.disabled=active()||busy;b.onclick=()=>{$('feedback').value=`Cari klip utuh tentang ${b.dataset.angle}`;resizeComposer();$('feedback').focus();};});
    $('renders').innerHTML = session.renders.map(r=>`<p>Render ${esc(r.job_id.slice(0,8))} · <a href="/process#${esc(r.job_id)}">Proses</a> · <a href="/results#${esc(r.job_id)}">Hasil</a></p>`).join('');
    const video = $('video'); video.hidden = !session.source_ready;
    const src = `/api/agent/sessions/${session.id}/source`;
    if (session.source_ready && video.getAttribute('src') !== src) { video.src=src; stopAt=null; }
    const nextCardsVersion=JSON.stringify([session.id,session.version,active(),busy]);
    if(cardsVersion!==nextCardsVersion) {
    cardsVersion=nextCardsVersion;
    const openDetails=[...$('candidates').querySelectorAll('details[open]')].map(d=>d.dataset.candidate);
    $('candidates').innerHTML = session.candidates.map((c,i)=>`<article class="agent-candidate" data-decision="${esc(c.decision)}"><h3>${i+1}. ${esc(c.title)}</h3>${c.decision==='kept'?`<label><input type="checkbox" data-render="${esc(c.id)}" ${renderSelection.has(c.id)?'checked':''} ${active()||busy?'disabled':''}> Sertakan pada render (maksimal 20)</label>`:''}<p>${time(c.start)}–${time(c.end)} · ${(c.end-c.start).toFixed(1)} dtk · ${esc(label(c.decision))}</p><p>${esc(c.reason)}</p><details data-candidate="${esc(c.id)}"><summary>Detail</summary>${c.opening_quote?`<p><strong>Pembuka:</strong> ${esc(c.opening_quote)}<br><strong>Penutup:</strong> ${esc(c.closing_quote)}</p>`:''}<blockquote>${esc(c.quote)}</blockquote>${c.concern?`<p><strong>Periksa:</strong> ${esc(c.concern)}</p>`:''}</details><div class="actions"><button class="btn sm ghost" data-play="${esc(c.id)}">Putar</button><button class="btn sm ghost" data-context="${esc(c.id)}">Putar konteks</button>${c.decision==='pending'?`<button class="btn sm ghost" data-revise="${i+1}">Revisi lewat chat</button>`:''}${[['kept','Pertahankan'],['rejected','Tolak'],['pending','Lepas pilihan']].map(([d,label])=>`<button class="btn sm ghost" data-id="${esc(c.id)}" data-decision="${d}" ${active()||busy||d===c.decision?'disabled':''}>${label}</button>`).join('')}</div></article>`).join('') || '<p class="sub">Sampaikan arahan melalui chat untuk mencari kandidat.</p>';
    $('candidates').querySelectorAll('details').forEach(d=>d.open=openDetails.includes(d.dataset.candidate));
    $('candidates').querySelectorAll('[data-play]').forEach(b=>b.onclick=()=>{
      const c=session.candidates.find(c=>c.id===b.dataset.play); stopAt=c.end;
      video.currentTime=c.start; video.play().catch(fail); $('playing').textContent=`${c.title} · ${time(c.start)}–${time(c.end)}`;
    });
    $('candidates').querySelectorAll('[data-context]').forEach(b=>b.onclick=()=>{
      const c=session.candidates.find(c=>c.id===b.dataset.context);stopAt=Math.min(session.source_duration||Infinity,c.end+15);
      video.currentTime=Math.max(0,c.start-15);video.play().catch(fail);$('playing').textContent=`Konteks sekitar ${c.title}`;
    });
    $('candidates').querySelectorAll('[data-revise]').forEach(b=>b.onclick=()=>{$('feedback').value=`Revisi kandidat ${b.dataset.revise}: `;resizeComposer();if(compact())panels();$('feedback').focus();});
    $('candidates').querySelectorAll('[data-render]').forEach(b=>b.onchange=()=>{
      if(b.checked&&renderSelection.size>=20){b.checked=false;fail(Error('Maksimal 20 pilihan per render.'));return;}
      if(b.checked)renderSelection.add(b.dataset.render);else renderSelection.delete(b.dataset.render);renderLink();
    });
    $('candidates').querySelectorAll('[data-decision][data-id]').forEach(b=>b.onclick=()=>mutate('decisions',{candidate_id:b.dataset.id,decision:b.dataset.decision}));
    }
    if(follow)area.scrollTop=area.scrollHeight;
    const m=session.metrics;
    $('metrics').textContent=`${m.model_requests||0} permintaan model · ${m.input_tokens||0} token masuk / ${m.output_tokens||0} keluar · ${Math.round(m.processing_seconds||0)} dtk proses · ${Math.round(m.editor_seconds||0)} dtk editor tercatat`;
  }
  async function load() {
    const id=location.hash.slice(1);
    if (!/^[a-f0-9-]{36}$/i.test(id)) {if(session)drafts.set(session.id,$('feedback').value);session=null;observedSession=null;panels();$('video').pause();stopAt=null;$('create').hidden=false;$('session').hidden=true;$('menu').hidden=true;$('review-toggle').hidden=true;$('title').textContent='Agent';$('state').textContent='Satu video, arahkan lewat chat';drawList();return;}
    const result=await api(`/api/agent/sessions/${id}`);
    if (location.hash.slice(1)!==id || busy || (session?.id===id && result.version<session.version)) return;
    if (session?.id!==id) {if(session)drafts.set(session.id,$('feedback').value);activeSeconds=0;pending.clear();$('feedback').value=drafts.get(id)||'';resizeComposer();$('video').pause();$('knowledge').dataset.version='';$('chat-scroll').scrollTop=0;}
    session=result; draw();resizeComposer();
  }
  async function mutate(action, extra={}) {
    if (busy || !session) return;
    const id=session.id, key=JSON.stringify([id,action,extra]);
    let payload=pending.get(key);
    if (!payload) {payload={request_id:crypto.randomUUID(),version:session.version,editor_seconds:activeSeconds,...extra};pending.set(key,payload);}
    busy=true; $('error').hidden=true; draw();
    try {
      const result=await api(`/api/agent/sessions/${id}/${action}`,'POST',payload);
      pending.delete(key); activeSeconds=Math.max(0,activeSeconds-payload.editor_seconds);
      if(session?.id===id) {session=result;if(action==='decisions'&&extra.decision==='kept'&&renderSelection.size<20)renderSelection.add(extra.candidate_id);if(action==='messages'){$('feedback').value='';drafts.delete(id);resizeComposer();}}
      await listing();
    } catch(e) {if(e.status && e.status<500)pending.delete(key);fail(e);await load().catch(fail);}
    finally {busy=false;draw();}
  }
  function tab(source){$('knowledge').hidden=!source;$('candidates').hidden=source;$('tab-source').setAttribute('aria-selected',String(source));$('tab-candidates').setAttribute('aria-selected',String(!source));}
  $('tab-source').onclick=()=>tab(true);$('tab-candidates').onclick=()=>tab(false);
  $('search').oninput=drawList;
  $('review-toggle').onclick=()=>panels(!reviewOpen);
  $('side-toggle').onclick=()=>panels(false,!sideOpen);
  $('review-close').onclick=$('side-close').onclick=$('overlay').onclick=()=>panels(false,false,true);
  window.addEventListener('resize',()=>{if(!matchMedia('(max-width:767px)').matches)sideOpen=false;panels(reviewOpen,sideOpen);});
  document.addEventListener('keydown',e=>{
    if(e.key==='Escape'){panels(false,false,true);$('menu').open=false;}
    const drawer=sideOpen?$('sidebar'):reviewOpen&&compact()?$('review'):null;
    if(e.key==='Tab' && drawer){const items=[...drawer.querySelectorAll('button:not(:disabled),a[href],input:not(:disabled),summary,video[controls]')].filter(el=>el.getClientRects().length);const first=items[0],last=items.at(-1);if(e.shiftKey&&document.activeElement===first){e.preventDefault();last?.focus();}else if(!e.shiftKey&&document.activeElement===last){e.preventDefault();first?.focus();}}
  });
  $('feedback').oninput=resizeComposer;
  $('feedback').onkeydown=e=>{if(e.key==='Enter'&&!e.shiftKey&&!e.isComposing&&e.keyCode!==229){e.preventDefault();if(!$('send').disabled)$('chat').requestSubmit();}};
  document.querySelectorAll('[data-prompt]').forEach(b=>b.onclick=()=>{$('feedback').value=b.dataset.prompt;resizeComposer();$('feedback').focus();});
  $('video').ontimeupdate=()=>{if(stopAt!==null&&$('video').currentTime>=stopAt){$('video').pause();stopAt=null;}};
  $('new').onclick=()=>{location.hash='';load().catch(fail);};
  $('kind').onchange=()=>{$('link-field').hidden=$('kind').value!=='link';$('file-field').hidden=$('kind').value!=='upload';};
  $('file').onchange=async()=>{
    upload=null;const file=$('file').files[0];if(!file)return;
    $('start').disabled=true;$('upload-status').textContent='Mengunggah…';
    try {const body=new FormData();body.append('berkas',file);const r=await fetch('/api/unggah',{method:'POST',body});const d=await r.json();if(!r.ok)throw Error(d.detail||'Unggahan gagal');upload=d.sumber;$('upload-status').textContent=`${file.name} siap.`;}
    catch(e){fail(e);$('upload-status').textContent='Unggahan gagal.';}finally{$('start').disabled=false;}
  };
  $('create').onsubmit=async e=>{
    e.preventDefault();if(busy)return;
    const data={url:$('kind').value==='upload'?upload:$('url').value.trim()};
    if(!data.url){fail(Error('Masukkan link atau unggah video terlebih dahulu.'));return;}
    const key=JSON.stringify(data);if(!pending.has(key))pending.set(key,{...data,request_id:crypto.randomUUID()});
    busy=true;$('start').disabled=true;$('error').hidden=true;
    try{const s=await api('/api/agent/sessions','POST',pending.get(key));pending.delete(key);location.hash=s.id;await listing();}
    catch(e){if(e.status&&e.status<500)pending.delete(key);fail(e);await listing().catch(fail);}
    finally{busy=false;$('start').disabled=false;}
  };
  $('chat').onsubmit=e=>{e.preventDefault();const text=$('feedback').value.trim();if(text && !$('send').disabled)mutate('messages',{text});};
  $('retry').onclick=()=>mutate('retry');
  $('cancel').onclick=async()=>{try{await api(`/api/agent/sessions/${session.id}/cancel`,'POST');await load();}catch(e){fail(e);}};
  $('delete').onclick=async()=>{if(!confirm('Hapus sesi, percakapan, dan sumber? Hasil render tetap tersedia.'))return;try{await api(`/api/agent/sessions/${session.id}`,'DELETE');location.hash='';await load();await listing();}catch(e){fail(e);}};
  ['pointerdown','keydown'].forEach(e=>document.addEventListener(e,()=>{lastActivity=Date.now();}));
  setInterval(()=>{if(session&&!document.hidden&&!active()&&Date.now()-lastActivity<60000)activeSeconds++;},1000);
  async function poll(){try{if(!busy&&!document.hidden)await load();}catch(e){fail(e);}finally{setTimeout(poll,2500);}}
  window.addEventListener('hashchange',()=>load().catch(fail));
  listing().catch(fail);poll();
})();
