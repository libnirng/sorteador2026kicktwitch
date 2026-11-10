// Painel visual do arquivo .env: nunca recupera valores de tokens ou senhas.
(() => {
  const el = id => document.getElementById(id);
  const heading = document.querySelector('[data-panel="connections"] .page-head');
  if (!heading) return;
  heading.querySelector('p').textContent = 'Preencha nesta página, salve no .env e conecte depois, quando quiser.';
  heading.insertAdjacentHTML('afterend', `
    <section class="card env-dashboard" aria-label="Resumo da configuração local">
      <div class="env-dashboard-head"><div><h2>Configuração visual <code>.env</code></h2><p class="hint">Os dados ficam no seu servidor local. O resumo não exibe senhas nem tokens.</p></div><span class="env-file-badge" id="env-file-status">Verificando…</span></div>
      <div class="env-summary-grid">
        <div class="env-summary"><span>Twitch</span><strong id="env-twitch-status">Verificando…</strong><small id="env-twitch-detail">—</small></div>
        <div class="env-summary"><span>Kick</span><strong id="env-kick-status">Verificando…</strong><small id="env-kick-detail">—</small></div>
        <div class="env-summary"><span>MegaMu</span><strong id="env-megamu-status">Verificando…</strong><small id="env-megamu-detail">—</small></div>
      </div>
      <div class="env-mode-row"><label class="check"><input id="env-real-mode" type="checkbox">Utilizar conexões reais (desativar simulação)</label><button id="btn-env-mode-save" class="btn sm">Salvar modo no .env</button><button id="btn-env-refresh" class="btn sm">Atualizar resumo</button></div>
      <p class="hint" id="env-mode-feedback" role="status">Salvar configurações e conectar os chats são ações separadas.</p>
    </section>`);
  el('btn-twitch-helix-save').textContent = 'Salvar Twitch no .env';
  el('btn-megamu-save').textContent = 'Salvar MegaMu no .env';
  const kickActions = el('btn-kick-receive-connect').parentElement;
  kickActions.insertAdjacentHTML('beforebegin', '<label class="check env-autostart"><input id="kick-receive-autostart" type="checkbox">Reconectar a Kick ao iniciar o servidor</label>');
  kickActions.insertAdjacentHTML('afterbegin', '<button class="btn primary" id="btn-kick-receive-save" type="button">Salvar recepção no .env</button>');
  kickActions.insertAdjacentHTML('afterend', '<p class="hint" id="kick-receive-save-feedback" role="status"></p>');
  el('kick-client-secret').closest('label').insertAdjacentHTML('afterend', '<div class="actions" style="margin-top:10px"><button class="btn" id="btn-kick-oauth-save" type="button">Salvar aplicativo no .env</button></div><p class="hint" id="kick-oauth-save-feedback" role="status">Salvar não inicia autorização.</p>');

  const show = (platform, ready, title, detail) => {
    el(`env-${platform}-status`).textContent = title;
    el(`env-${platform}-status`).dataset.ready = ready ? 'true' : 'false';
    el(`env-${platform}-detail`).textContent = detail;
  };
  async function refreshEnvStatus() {
    try {
      const response = await fetch('/api/config/env/status', {cache:'no-store'});
      const data = await response.json();
      if (!response.ok) throw Error(data.detail || 'Erro de leitura do .env.');
      const f=data.fields, s=data.secrets_configured;
      const twitch=!!(f.TWITCH_CHANNEL && f.TWITCH_CLIENT_ID && s.TWITCH_ACCESS_TOKEN);
      const kick=!!f.KICK_CHANNEL;
      const megamu=!!(f.MEGAMU_DV && s.MEGAMU_KEY && f.MEGAMU_ENABLED==='true');
      show('twitch',twitch,twitch?'Credenciais cadastradas':'Configuração incompleta',`Canal: ${f.TWITCH_CHANNEL||'não informado'} · Token: ${s.TWITCH_ACCESS_TOKEN?'salvo':'pendente'}`);
      show('kick',kick,kick?'Canal cadastrado':'Informe o canal',`Leitura: ${f.KICK_RECEIVE_MODE||'direct'} · App para enviar: ${f.KICK_CLIENT_ID && s.KICK_CLIENT_SECRET?'configurado':'opcional'}`);
      show('megamu',megamu,megamu?'Catálogo habilitado':'Pendente ou desativado',`DV: ${f.MEGAMU_DV||'não informado'} · Chave: ${s.MEGAMU_KEY?'salva':'pendente'}`);
      el('env-file-status').textContent = data.file_exists?'● Arquivo .env encontrado':'○ Será criado ao salvar';
      el('env-file-status').dataset.exists = data.file_exists?'true':'false';
      el('env-real-mode').checked = f.SIMULATION_MODE==='false';
      el('kick-receive-autostart').checked = f.KICK_RECEIVE_ENABLED==='true';
      for (const [id,key] of [['twitch-channel','TWITCH_CHANNEL'],['twitch-client-id','TWITCH_CLIENT_ID'],['kick-receive-channel','KICK_CHANNEL'],['kick-client-id','KICK_CLIENT_ID'],['kick-redirect-uri','KICK_REDIRECT_URI']]) {
        if (!el(id).value) el(id).value=f[key]||'';
      }
      if (!el('kick-redirect-uri').value) el('kick-redirect-uri').value='http://localhost:8777/api/oauth/kick/callback';
    } catch(error) {
      el('env-file-status').textContent='Não foi possível verificar o .env';
      el('env-mode-feedback').textContent=error.message;
    }
  }
  window.refreshEnvStatus=refreshEnvStatus;
  const post = async (url, body) => {
    const r=await fetch(url,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
    const result=await r.json();
    if(!r.ok) throw Error(result.detail||'Falha ao salvar.');
    return result;
  };
  const positiveOrNull=id=>{
    const raw=el(id).value.trim(); if(!raw)return null;
    const num=Number(raw);if(!Number.isSafeInteger(num)||num<1)throw Error('Os IDs devem ser números positivos.');
    return num;
  };
  el('btn-env-refresh').addEventListener('click',refreshEnvStatus);
  el('btn-env-mode-save').addEventListener('click',async()=>{
    const message=el('env-mode-feedback');
    try{await post('/api/config/env/mode',{simulation_mode:!el('env-real-mode').checked});message.textContent='✅ Modo salvo no .env.';await refreshEnvStatus();}
    catch(e){message.textContent='❌ '+e.message;}
  });
  el('btn-kick-receive-save').addEventListener('click',async()=>{
    const message=el('kick-receive-save-feedback');message.textContent='Salvando…';
    try{
      await post('/api/chat/kick/save',{
        channel:el('kick-receive-channel').value.trim(),mode:el('kick-receive-mode').value,
        chatroom_id:positiveOrNull('kick-receive-room'),channel_id:positiveOrNull('kick-receive-channel-id'),
        reconnect_at_start:el('kick-receive-autostart').checked,
      });
      message.textContent='✅ Configuração da Kick salva no .env. Clique em Conectar chat para iniciar agora.';
      await refreshEnvStatus();
    }catch(e){message.textContent='❌ '+e.message;}
  });
  el('btn-kick-oauth-save').addEventListener('click',async()=>{
    const message=el('kick-oauth-save-feedback'), id=el('kick-client-id').value.trim();
    if(!id){message.textContent='Informe o Client ID da Kick.';return;}
    message.textContent='Salvando…';
    try{
      await post('/api/oauth/kick/config',{client_id:id,redirect_uri:el('kick-redirect-uri').value.trim(),client_secret:el('kick-client-secret').value.trim()});
      el('kick-client-secret').value='';
      if (typeof render === 'function') {
        state = await (await fetch('/api/state')).json();
        render();
      }
      message.textContent='✅ Aplicativo salvo no .env. Clique em Autorizar para gerar os tokens.';
      await refreshEnvStatus();
    }catch(e){message.textContent='❌ '+e.message;}
  });
  document.querySelector('.tab[data-tab="connections"]').addEventListener('click',refreshEnvStatus);
  refreshEnvStatus();
})();
