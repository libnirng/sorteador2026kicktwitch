// Painel administrativo - cliente WebSocket
let ws;
const $ = (id) => document.getElementById(id);
const weightLabel=value=>Number(value).toLocaleString('pt-BR',{maximumFractionDigits:10});
let giveawayWeightsDirty=false;
const pendingRules=new Map();
let ruleSaveQueue=Promise.resolve();

// Status pill — usa o conn-twitch do header (null-safe)
const statusPill = $('conn-twitch');
function setStatus(connected) {
    if (!statusPill) return;
    statusPill.dataset.status = connected ? 'online' : 'offline';
    const dot = statusPill.querySelector('.dot');
    if (dot) {
        dot.style.background = connected ? 'var(--success)' : 'var(--text-faint)';
        dot.style.boxShadow = connected ? '0 0 6px var(--success)' : 'none';
    }
}
setStatus(false);

// Abas
const TAB_NAMES = {
    overview: 'Visão Geral', giveaway: 'Sorteio', participants: 'Participantes e Chances',
    messages: 'Mensagens', roleta: 'Roleta', antibot: 'Anti-bot', chats: 'Chats', connections: 'Conexões',
    history: 'Histórico', audit: 'Auditoria', appearance: 'Aparência', obs: 'OBS'
};
document.querySelectorAll('.tab').forEach(btn => {
    btn.addEventListener('click', () => {
        const tab = btn.dataset.tab;
        document.querySelectorAll('.tab').forEach(b => b.classList.remove('active'));
        document.querySelectorAll('.tab-panel').forEach(p => p.classList.remove('active'));
        btn.classList.add('active');
        document.querySelector(`[data-panel="${tab}"]`).classList.add('active');
        const bc = $('bc-title');
        if (bc && TAB_NAMES[tab]) bc.textContent = TAB_NAMES[tab];
        if (tab === 'history' && typeof renderHistory === 'function') renderHistory();
    });
});

$('btn-open-connections').addEventListener('click', () => {
    document.querySelector('.tab[data-tab="connections"]').click();
});

// Copiar link do overlay
window.copy = (id) => {
    const text = $(id).textContent;
    navigator.clipboard.writeText(text).then(() => {
        const orig = $(id).nextElementSibling.textContent;
        $(id).nextElementSibling.textContent = 'Copiado!';
        setTimeout(() => { $(id).nextElementSibling.textContent = orig; }, 1200);
    });
};

// Estado recebido
let state = null;
let timerInterval = null;

// Estado Kick
let kickState = {
    oauth: {
        authenticated: false,
        token_valid: false,
        username: '',
        user_id: '',
        channel_slug: '',
        broadcaster_user_id: '',
        granted_scopes: [],
        missing_scopes: [],
        expires_in_seconds: -1,
    },
    ngrok: {
        connected: false,
        url: '',
        webhook_port: 8766,
    },
    subscription: {
        has_subscription: false,
        subscription_id: '',
        subscription_name: '',
        subscription_status: '',
    },
    monitor: {
        last_webhook: null,
        last_participant: null,
        total_kick_participants: 0,
        total_messages: 0,
        last_error: null,
    },
};

function render() {
    if (!state) return;

    // Links do OBS
    const base = ['localhost','127.0.0.1'].includes(location.hostname) ? `${location.protocol}//127.0.0.1:${location.port || '8777'}` : location.origin;
    $('link-sorteio').textContent = `${base}/overlay/sorteio`;
    $('link-roleta').textContent = `${base}/overlay/roleta`;
    $('link-captcha').textContent = `${base}/overlay/captcha`;

    // Visão geral
    const ov = state.giveaway || {};
    $('ov-twitch').textContent = state.connections.twitch.connected ? 'conectado' : 'desconectado';
    $('ov-mode').textContent = state.connections.simulation_mode ? 'simulação' : 'real';
    $('ov-status').textContent = ov.is_running ? (ov.is_paused ? 'pausado' : 'aberto') : 'parado';
    $('ov-keyword').textContent = ov.keyword || '-';
    $('ov-count').textContent = ov.count || 0;
    if (ov.current_winner) {
        const w = ov.current_winner;
        $('ov-current-winner').innerHTML = `<div style="margin-top:8px;color:var(--primary)">🏆 <strong>${w.username}</strong> (${w.platform}, ${w.chance_pct.toFixed(2)}%)</div>`;
    } else {
        $('ov-current-winner').innerHTML = '';
    }
    $('overview-server').textContent = `v${state.server.version} — ok`;

    // Atualiza estado Kick
    updateKickState(state);

    // Aba Chats
    renderChats();
    renderKick();

    for (const platform of ['twitch','kick']) {
        if (!document.activeElement || document.activeElement.id !== 'bot-send-'+platform) $('bot-send-'+platform).checked=!!state.bots[platform+'_enabled'];
    }
    // Aba Sorteio
    renderGiveaway();
    window.renderMegaMu?.();
    $('giveaway-chat-status').textContent=['twitch','kick'].map(platform =>
        `${platform==='twitch'?'Twitch':'Kick'}: ${state.bots[platform+'_enabled'] && state.chat_events.giveaway_open ? 'anúncio de abertura habilitado' : 'anúncio de abertura desligado'}`
    ).join(' • ');

    // Aba Participantes
    renderParticipants();

    // Aba Anti-bot
    renderAntibot();

    // Aba Auditoria
    renderAudit();

    // Aba Roleta
    renderRoleta();
    window.renderLiveChats?.();
}

// Atualizar indicadores de conexão no header
function updateHeaderStatus() {
    if (!state) return;
    const tw = state.connections.twitch;
    const pillTwitch = $('conn-twitch');
    const pillKick = $('conn-kick');

    if (pillTwitch) {
        pillTwitch.dataset.status = tw.connected ? 'online' : 'offline';
        const dot = pillTwitch.querySelector('.dot');
        if (dot) {
            dot.style.background = tw.connected ? 'var(--success)' : 'var(--text-faint)';
            dot.style.boxShadow = tw.connected ? '0 0 6px var(--success)' : 'none';
        }
    }

    const ks = state.kick || {};
    const kickOk = !!ks.receive_connected;
    if (pillKick) {
        pillKick.dataset.status = kickOk ? 'online' : 'offline';
        const dot = pillKick.querySelector('.dot');
        if (dot) {
            dot.style.background = kickOk ? 'var(--success)' : 'var(--text-faint)';
            dot.style.boxShadow = kickOk ? '0 0 6px var(--success)' : 'none';
        }
    }
}

function renderChats() {
    const tw = state.connections.twitch;
    $('twitch-status').textContent = tw.connected ? 'conectado' : 'desconectado';
    $('cur-twitch-channel').textContent = tw.channel || '-';
    $('cur-twitch-status').textContent = tw.connected ? 'conectado' : 'offline';
    $('cur-mode').textContent = state.connections.simulation_mode ? 'simulação' : 'real';
    updateHeaderStatus();

    // Twitch Helix: status de credencial
    const helixOk = state.bots && state.bots.twitch_helix_configured;
    const helixStatus = $('twitch-helix-status');
    if (helixOk) {
        helixStatus.textContent = '✅ Credenciais salvas no servidor e no .env. Não precisa colar novamente.';
        helixStatus.className = 'chat-status conectado';
    } else {
        helixStatus.textContent = '⚠️ Sem credenciais (avatares não vão aparecer)';
        helixStatus.className = 'chat-status';
    }

    $('btn-twitch-disconnect').disabled = !tw.connected;

    // Kick state
    const ks = state.kick || {};
    $('kick-auto-send-state').textContent=state.bots.kick_enabled?'Anúncios automáticos da Kick habilitados; confira os eventos na aba Mensagens.':'Anúncios automáticos da Kick desligados. Para anunciar vencedor e prêmios, habilite os anúncios junto à conexão da Kick e configure os eventos na aba Mensagens.';
    const kickConnected = !!ks.receive_connected;
    $('kick-status').textContent = kickConnected ? 'operacional' : 'incompleto';
    $('kick-status').className = 'chat-status' + (kickConnected ? ' conectado' : '');

    $('btn-kick-disconnect').disabled = !ks.oauth_authenticated;
    const receiveChannel=$('kick-receive-channel');
    if (!receiveChannel.dataset.loaded) {
        receiveChannel.value=ks.receive_channel || '';
        $('kick-receive-mode').value=ks.receive_mode || 'direct';
        $('kick-receive-room').value=ks.chatroom_id || '';
        $('kick-receive-channel-id').value=ks.channel_id || '';
        receiveChannel.dataset.loaded='1';
    }
    $('kick-webhook-settings').hidden=$('kick-receive-mode').value!=='webhook';
    $('btn-kick-receive-disconnect').disabled=!ks.receive_connected;
    if (ks.receive_connected && !$('kick-receive-feedback').textContent) $('kick-receive-feedback').textContent='Chat conectado: novas mensagens devem aparecer na aba Chats.';
    if (ks.receive_error) $('kick-receive-feedback').textContent=ks.receive_error;
    else if (!ks.receive_connected && !$('kick-receive-feedback').textContent) $('kick-receive-feedback').textContent='Leitura desconectada. Autorizar a conta não conecta o chat. Clique em Conectar chat acima.';

    if (ks.twitch_channel && !$('twitch-channel').value) $('twitch-channel').value = ks.twitch_channel;

}

// Atualizar estado Kick do state
function updateKickState(wsState) {
    const ks = wsState.kick || {};

    // OAuth
    kickState.oauth = {
        authenticated: ks.oauth_authenticated || false,
        token_valid: ks.oauth_token_valid || false,
        username: ks.oauth_username || '',
        user_id: ks.oauth_user_id || '',
        channel_slug: ks.channel_slug || '',
        broadcaster_user_id: ks.broadcaster_user_id || '',
        granted_scopes: ks.granted_scopes || [],
        missing_scopes: ks.missing_scopes || [],
        expires_in_seconds: ks.expires_in_seconds || -1,
        message: ks.oauth_message || '',
    };

    // Ngrok
    kickState.ngrok = {
        connected: ks.ngrok_connected || false,
        url: ks.ngrok_url || '',
        webhook_port: ks.ngrok_webhook_port || 8766,
    };

    // Subscription
    kickState.subscription = {
        has_subscription: ks.subscription_registered || false,
        subscription_id: ks.subscription_id || '',
        subscription_name: ks.subscription_name || '',
        subscription_status: ks.subscription_status || '',
    };

    // Monitor
    kickState.monitor = {
        last_webhook: ks.last_webhook_ts || null,
        last_participant: ks.last_kick_participant || null,
        total_kick_participants: wsState.participants ? wsState.participants.filter(p => p.platform === 'kick').length : 0,
        total_messages: ks.total_messages || 0,
        last_error: ks.last_error || null,
    };
}

function renderKick() {
    const oa = kickState.oauth;
    const ng = kickState.ngrok;
    const sub = kickState.subscription;
    const mon = kickState.monitor;

    // OAuth info
    const authInfo = $('kick-auth-info');
    const authStatus = $('kick-auth-status');

    if (oa.authenticated) {
        authInfo.style.display = 'block';
        $('kick-username').textContent = oa.username || '-';
        $('kick-channel-slug').textContent = oa.channel_slug || '-';

        // Scopes badges
        const scopesEl = $('kick-scopes');
        const allScopes = ['user:read', 'channel:read', 'events:subscribe', 'chat:write'];
        scopesEl.innerHTML = allScopes.map(s => {
            const granted = oa.granted_scopes.includes(s);
            const missing = oa.missing_scopes.includes(s);
            const cls = missing ? 'missing' : (granted ? '' : 'missing');
            return `<span class="kick-scope-badge ${cls}">${s}${missing ? ' ❌' : ' ✓'}</span>`;
        }).join('');

        authStatus.textContent = oa.expires_in_seconds > 0
            ? `Token válido por ${formatTime(oa.expires_in_seconds)}`
            : 'Token válido';
        authStatus.className = 'kick-auth-status success';

        $('btn-kick-authorize').disabled = oa.missing_scopes.length===0 && oa.granted_scopes.includes('chat:write');
        $('btn-kick-disconnect').disabled = false;
    } else {
        authInfo.style.display = 'none';
        authStatus.textContent = oa.token_valid
            ? (oa.message || 'Token válido; conclua a autorização da conta.')
            : 'Não autenticado';
        authStatus.className = 'kick-auth-status' + (oa.token_valid ? ' warning' : ' error');

        $('btn-kick-authorize').disabled = false;
        $('btn-kick-disconnect').disabled = true;
    }

    // Ngrok status
    const ngIndicator = $('kick-ngrok-indicator');
    const ngText = $('kick-ngrok-text');

    if (ng.connected) {
        ngIndicator.className = 'kick-indicator online';
        ngText.textContent = 'ngrok conectado';

        // Show webhook URL
        const webhookUrl = `${ng.url}/api/webhooks/kick`;
        $('kick-webhook-full-url').textContent = webhookUrl;
        $('kick-webhook-url').style.display = 'block';

        $('btn-kick-ngrok-connect').disabled = true;
        $('btn-kick-ngrok-disconnect').disabled = false;
        $('kick-ngrok-hint').textContent = '';
    } else {
        ngIndicator.className = 'kick-indicator offline';
        ngText.textContent = 'ngrok desconectado';
        $('kick-webhook-url').style.display = 'none';

        $('btn-kick-ngrok-connect').disabled = false;
        $('btn-kick-ngrok-disconnect').disabled = true;
        $('kick-ngrok-hint').textContent = 'Configure ngrok primeiro no Windows. Sem ngrok, webhooks não funcionam.';
    }

    // Subscription status
    const subStatus = $('kick-sub-status');
    const subError = $('kick-sub-error');

    if (sub.has_subscription) {
        subStatus.className = 'kick-sub-status has-sub';
        subStatus.innerHTML = `<span class="kick-indicator online"></span> Assinatura <strong>${sub.subscription_name || 'chat.message.sent'}</strong> ativa (${sub.subscription_status})`;
        subError.textContent = '';

        $('btn-kick-subs-create').disabled = true;
    } else {
        subStatus.className = 'kick-sub-status';
        subStatus.textContent = oa.authenticated
            ? 'Nenhuma assinatura registrada. Crie uma para receber eventos.'
            : 'Autentique-se primeiro para gerenciar assinaturas.';

        $('btn-kick-subs-create').disabled = !oa.authenticated || !ng.connected;
    }

    // Monitoring indicators
    $('kick-mon-oauth').className = 'kick-indicator ' + (oa.authenticated ? 'online' : 'offline');
    $('kick-mon-channel').className = 'kick-indicator ' + (oa.channel_slug ? 'online' : 'offline');
    $('kick-mon-ngrok').className = 'kick-indicator ' + (ng.connected ? 'online' : 'offline');
    $('kick-mon-subscription').className = 'kick-indicator ' + (sub.has_subscription ? 'online' : 'offline');
    $('kick-mon-webhook').className = 'kick-indicator ' + (mon.last_webhook ? 'online' : 'offline');
    $('kick-mon-messages').className = 'kick-indicator ' + (mon.total_messages > 0 ? 'online' : 'offline');

    // Monitor details
    $('kick-last-webhook').textContent = mon.last_webhook
        ? new Date(mon.last_webhook * 1000).toLocaleTimeString()
        : '-';
    $('kick-last-participant').textContent = mon.last_participant || '-';
    $('kick-total-participants').textContent = mon.total_kick_participants;

    const errorEl = $('kick-error-display');
    if (mon.last_error) {
        errorEl.textContent = 'Erro: ' + mon.last_error;
        errorEl.style.display = 'block';
    } else {
        errorEl.style.display = 'none';
    }
}

function formatTime(seconds) {
    if (seconds < 0) return 'indefinido';
    if (seconds < 60) return `${seconds}s`;
    const mins = Math.floor(seconds / 60);
    const secs = seconds % 60;
    return `${mins}m ${secs}s`;
}

function connectAdmin() {
    ws = new WebSocket(`${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}/ws`);
ws.onopen = () => {};
ws.onclose = () => { setTimeout(connectAdmin, 2000); };
ws.onerror = () => ws.close();
ws.onmessage = (e) => {
    try {
        const msg = JSON.parse(e.data);
        if (msg.type === 'init' && msg.state) {
            state = msg.state;
            render();
        } else if (msg.type === 'chat_message' && msg.message) {
            window.acceptChatMessage?.(msg.message);
        } else if (msg.type === 'state' && msg.state) {
            state = msg.state;
            render();
        }
    } catch (err) {
        console.error('admin WS erro:', err);
    }
};

}
connectAdmin();

// ============================================================================
// AÇÕES DA ABA CHATS
// ============================================================================
function logChat(platform, msg, kind = 'info') {
    const el = $(`${platform}-log`);
    if (!el) return;
    const time = new Date().toLocaleTimeString();
    const css = kind === 'err' ? 'log-err' : kind === 'ok' ? 'log-ok' : '';
    el.innerHTML += `<div class="${css}">[${time}] ${msg}</div>`;
    el.scrollTop = el.scrollHeight;
    // limita a 50 linhas
    while (el.children.length > 50) el.removeChild(el.firstChild);
}

$('btn-twitch-connect').addEventListener('click', async () => {
    const channel = $('twitch-channel').value.trim();
    if (!channel) { logChat('twitch', 'informe o canal', 'err'); return; }
    logChat('twitch', `conectando em #${channel} via EventSub...`);
    try {
        if ($('twitch-helix-token').value.trim()) {
            await post('/api/twitch/helix/save',{client_id:$('twitch-client-id').value.trim(),oauth:$('twitch-helix-token').value.trim()});
            $('twitch-helix-token').value='';
        }
        const r = await fetch('/api/chat/twitch/connect', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ channel }),
        });
        const data = await r.json();
        if (!r.ok) throw new Error(data.detail || 'falhou');
        logChat('twitch', `conectado em #${data.channel} (EventSub)`, 'ok');
    } catch (e) {
        logChat('twitch', `erro: ${e.message}`, 'err');
    }
});

$('btn-twitch-disconnect').addEventListener('click', async () => {
    logChat('twitch', 'desconectando...');
    await fetch('/api/chat/twitch/disconnect', { method: 'POST' });
    logChat('twitch', 'desconectado', 'ok');
});

$('btn-twitch-helix-save').addEventListener('click', async () => {
    const client_id = $('twitch-client-id').value.trim();
    const oauth = $('twitch-helix-token').value.trim();
    const channel = $('twitch-channel').value.trim();
    if (!channel && !client_id && !oauth) { logChat('twitch-helix', 'informe um canal ou credencial', 'err'); return; }
    logChat('twitch-helix', 'salvando Twitch no .env...');
    try {
        const r = await fetch('/api/twitch/helix/save', {
            method: 'POST', headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({client_id, oauth, channel}),
        });
        const data = await r.json();
        if (!r.ok) throw new Error(data.detail || 'falhou');
        logChat('twitch-helix', data.reconnect_required ? '✅ Dados gravados no .env. Clique em Conectar para usar a nova configuração.' : '✅ Twitch gravada no .env. Conecte quando estiver pronto.', 'ok');
        // limpa o input do token por segurança (não volta mais pro state)
        $('twitch-helix-token').value = '';
        // força refresh do state pra mostrar "configurado"
        const sr = await fetch('/api/state');
        state = await sr.json();
        render();
        window.refreshEnvStatus?.();
    } catch (e) {
        logChat('twitch-helix', 'erro: ' + e.message, 'err');
    }
});

$('btn-twitch-token-inspect').addEventListener('click', async () => {
    const oauth=$('twitch-helix-token').value.trim();
    if(!oauth) {$('twitch-token-feedback').textContent='Cole o Access token no campo acima.';return;}
    $('twitch-token-feedback').textContent='Consultando a Twitch...';
    try {
        const response=await fetch('/api/twitch/token/inspect',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({oauth})});
        const data=await response.json();
        if(!response.ok) throw Error(data.detail || 'Não foi possível conferir o token.');
        $('twitch-client-id').value=data.client_id;
        $('twitch-token-feedback').textContent=`Conta: ${data.login}. Client ID preenchido. Leitura: ${data.has_read_chat?'sim':'falta user:read:chat'}. Envio: ${data.has_write_chat?'sim':'falta user:write:chat'}. Clique em Salvar credenciais e depois Conectar.`;
    } catch(e) {$('twitch-token-feedback').textContent=e.message;}
});

$('btn-twitch-helix-test').addEventListener('click', async () => {
    logChat('twitch-helix', 'testando...');
    try {
        const r = await fetch('/api/twitch/helix/test', {method: 'POST'});
        const data = await r.json();
        if (!r.ok) throw new Error(data.detail || 'falhou');
        logChat('twitch-helix', `✅ Token válido · leitura: ${data.has_read_chat ? 'sim' : 'não'} · envio: ${data.has_write_chat ? 'sim' : 'não'}`, 'ok');
    } catch (e) {
        logChat('twitch-helix', '❌ ' + e.message, 'err');
    }
});

// ============================================================================
// AÇÕES DO KICK
// ============================================================================

$('btn-kick-test-send').addEventListener('click', async () => {
    const btn=$('btn-kick-test-send');btn.disabled=true;
    $('kick-test-send-feedback').textContent='Enviando mensagem de teste...';
    try {
        const response=await fetch('/api/chat/send',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({platform:'kick',text:'Teste do Sorteador Geral: envio da Kick funcionando.'})});
        const data=await response.json();
        if(!response.ok) throw Error(data.detail || 'A Kick não confirmou o envio.');
        $('kick-test-send-feedback').textContent='A Kick confirmou o envio da mensagem de teste.';
    } catch(e) {$('kick-test-send-feedback').textContent=e.message;}
    finally {btn.disabled=false;}
});

$('kick-receive-channel').addEventListener('input', () => {$('kick-receive-room').value='';$('kick-receive-channel-id').value='';});
$('kick-receive-mode').addEventListener('change', () => {
    $('kick-webhook-settings').hidden=$('kick-receive-mode').value!=='webhook';
});
$('btn-kick-receive-connect').addEventListener('click', async () => {
    const btn=$('btn-kick-receive-connect');btn.disabled=true;
    $('kick-receive-feedback').textContent='Conectando ao chat...';
    try {
        const payload={channel:$('kick-receive-channel').value.trim(),mode:$('kick-receive-mode').value,simulation:false,
            chatroom_id:$('kick-receive-room').value ? Number($('kick-receive-room').value) : null,
            channel_id:$('kick-receive-channel-id').value ? Number($('kick-receive-channel-id').value) : null};
        async function connectRequest() {
            const response=await fetch('/api/chat/kick/connect',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
            return {response,data:await response.json()};
        }
        let {response,data}=await connectRequest();
        if (!response.ok && payload.mode==='direct' && !payload.chatroom_id && /HTTP (403|429)/.test(String(data.detail))) {
            $('kick-receive-feedback').textContent='Tentando identificar a sala pelo navegador...';
            try {
                const channel=payload.channel.replace(/^@/,'').toLowerCase();
                const lookup=await fetch('https://kick.com/api/v1/channels/'+encodeURIComponent(channel),{credentials:'omit'});
                if(!lookup.ok) throw Error('HTTP '+lookup.status);
                const metadata=await lookup.json();
                const room=Number(metadata.chatroom?.id);
                if(!Number.isSafeInteger(room) || room<=0) throw Error('ID da sala ausente');
                payload.chatroom_id=room;$('kick-receive-room').value=String(room);
                const channelId=Number(metadata.id);
                if(Number.isSafeInteger(channelId) && channelId>0) {
                    payload.channel_id=channelId;$('kick-receive-channel-id').value=String(channelId);
                }
                ({response,data}=await connectRequest());
            } catch(error) {
                throw Error('Não foi possível conectar pelo navegador. Em Opções avançadas, informe chatroom.id e id do canal e tente novamente. Detalhe: '+error.message);
            }
        }
        if(!response.ok) throw Error(typeof data.detail==='string'?data.detail:'Confira o canal e o ID da sala.');
        $('kick-receive-feedback').textContent=`Chat de @${data.channel} conectado (${data.mode==='direct'?'sem ngrok':'webhooks'}).`;
        state=await (await fetch('/api/state')).json();render();
    } catch(e) {$('kick-receive-feedback').textContent='Não foi possível conectar: '+e.message;}
    finally {btn.disabled=false;}
});
$('btn-kick-receive-disconnect').addEventListener('click', async () => {
    const response=await fetch('/api/chat/kick/disconnect',{method:'POST'});
    $('kick-receive-feedback').textContent=response.ok?'Leitura do chat desconectada. A autorização para envio foi mantida.':'Não foi possível desconectar.';
    state=await (await fetch('/api/state')).json();render();
});

// Kick OAuth - Autorizar
// Kick OAuth - Autorizar
$('btn-kick-authorize').addEventListener('click', async () => {
    const clientId = $('kick-client-id').value.trim();
    const clientSecret = $('kick-client-secret').value.trim();

    if (!clientId) {
        $('kick-oauth-feedback').textContent = 'Preencha o Client ID do aplicativo, não o nick do canal.';
        logChat('kick', 'Client ID é obrigatório', 'err');
        return;
    }

    if (!clientSecret && !state?.kick.has_secret) {
        $('kick-oauth-feedback').textContent = 'Preencha o Client Secret do mesmo aplicativo da Kick.';
        return;
    }
    const authWindow = window.open('about:blank', 'kick_auth', 'width=600,height=700');
    if (!authWindow) {
        $('kick-oauth-feedback').textContent = 'Permita pop-ups para este painel e clique em Autorizar novamente.';
        return;
    }
    $('kick-oauth-feedback').textContent = 'Preparando autorização...';
    logChat('kick', 'Configurando OAuth...');
    try {
        // Primeiro configura OAuth
        const configRes = await fetch('/api/oauth/kick/config', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ client_id: clientId, client_secret: clientSecret, redirect_uri: $('kick-redirect-uri').value.trim() }),
        });
        const configData = await configRes.json();
        
        if (!configRes.ok) {
            throw new Error(configData.detail || 'Falhou ao configurar OAuth');
        }
        
        logChat('kick', 'OAuth configurado. Iniciando autorização...');
        
        // Depois, obter URL de autorização
        const r = await fetch('/api/oauth/kick/start', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ include_chat: true }),
        });
        const data = await r.json();
        
        if (!r.ok) {
            throw new Error(data.detail || data.message || 'Falhou ao obter URL de autorização');
        }
        
        logChat('kick', 'Abrindo navegador para autorização...', 'ok');
        
        // Abrir URL em nova janela
        if (data.authorization_url) {
            authWindow.location.replace(data.authorization_url);
            $('kick-oauth-feedback').textContent = 'Conclua a autorização na janela da Kick. Se aparecer erro 400, confira Client ID e Redirect URI no aplicativo.';

            let authTimeout;
            // Escutar callback via polling
            const checkAuth = setInterval(async () => {
                try {
                    const statusRes = await fetch('/api/oauth/kick/status');
                    const status = await statusRes.json();

                    if (status.authenticated) {
                        clearInterval(checkAuth);
                        clearTimeout(authTimeout);
                        if (authWindow) authWindow.close();
                        $('kick-oauth-feedback').textContent = `Autenticado como ${status.username || 'usuário'}.`;
                        logChat('kick', `✅ Autenticado como ${status.username || 'usuário'}`, 'ok');
                        // Refresh state
                        const sr = await fetch('/api/state');
                        state = await sr.json();
                        updateKickState(state);
                        renderKick();
                        renderChats();
                    }
                } catch (e) {
                    // Ignora erros de polling
                }
            }, 2000);

            // Timeout de 10 minutos para autorização
            authTimeout = setTimeout(() => {
                clearInterval(checkAuth);
                $('kick-oauth-feedback').textContent = 'A autorização expirou. Confira as credenciais e tente novamente.';
                logChat('kick', 'Timeout de autorização. Tente novamente.', 'err');
            }, 600000);
        }
    } catch (e) {
        authWindow.close();
        $('kick-oauth-feedback').textContent = e.message;
        logChat('kick', '❌ ' + e.message, 'err');
    }
});
$('btn-kick-disconnect').addEventListener('click', async () => {
    if (!confirm('Desconectar conta Kick? Isso removerá os tokens salvos.')) return;

    logChat('kick', 'Desconectando...');
    try {
        const r = await fetch('/api/oauth/kick/logout', { method: 'POST' });
        if (!r.ok) throw new Error('Falhou');
        logChat('kick', '✅ Desconectado', 'ok');

        // Refresh state
        const sr = await fetch('/api/state');
        state = await sr.json();
        updateKickState(state);
        renderKick();
        renderChats();
    } catch (e) {
        logChat('kick', '❌ ' + e.message, 'err');
    }
});

// ngrok - Conectar
$('btn-kick-ngrok-connect').addEventListener('click', async () => {
    logChat('kick', 'Iniciando ngrok...');
    $('btn-kick-ngrok-connect').disabled = true;

    try {
        const r = await fetch('/api/ngrok/connect', { method: 'POST' });
        const data = await r.json();

        if (!r.ok) {
            throw new Error(data.detail || data.message || 'Falhou ao conectar ngrok');
        }

        logChat('kick', `✅ ngrok conectado: ${data.url}`, 'ok');

        // Refresh state
        const sr = await fetch('/api/state');
        state = await sr.json();
        updateKickState(state);
        renderKick();
    } catch (e) {
        logChat('kick', '❌ ngrok: ' + e.message, 'err');
        $('btn-kick-ngrok-connect').disabled = false;
    }
});

// ngrok - Desconectar
$('btn-kick-ngrok-disconnect').addEventListener('click', async () => {
    logChat('kick', 'Encerrando ngrok...');
    $('btn-kick-ngrok-disconnect').disabled = true;

    try {
        await fetch('/api/ngrok/disconnect', { method: 'POST' });
        logChat('kick', '✅ ngrok encerrado', 'ok');

        // Refresh state
        const sr = await fetch('/api/state');
        state = await sr.json();
        updateKickState(state);
        renderKick();
    } catch (e) {
        logChat('kick', '❌ ' + e.message, 'err');
        $('btn-kick-ngrok-disconnect').disabled = false;
    }
});

// Assinaturas - Listar
$('btn-kick-subs-list').addEventListener('click', async () => {
    logChat('kick', 'Consultando assinaturas...');

    try {
        const r = await fetch('/api/kick/subscriptions');
        const data = await r.json();

        if (!r.ok) {
            $('kick-sub-error').textContent = data.detail || data.message || 'Erro ao consultar';
            throw new Error(data.detail || 'Falhou');
        }

        const subsList = $('kick-subs-list');
        const subscriptions = data.subscriptions || [];

        if (subscriptions.length === 0) {
            subsList.innerHTML = '<div class="hint" style="padding:8px">Nenhuma assinatura encontrada</div>';
        } else {
            subsList.innerHTML = subscriptions.map(s => `
                <div class="kick-sub-item">
                    <span class="sub-name">${s.name} v${s.version}</span>
                    <span class="sub-status ${s.status === 'enabled' ? 'active' : 'inactive'}">${s.status}</span>
                    <button class="btn danger" onclick="deleteKickSub('${s.id}')">✕</button>
                </div>
            `).join('');
        }

        logChat('kick', `✅ ${subscriptions.length} assinatura(s) encontrada(s)`, 'ok');
    } catch (e) {
        if (e.message !== 'Falhou') {
            logChat('kick', '❌ ' + e.message, 'err');
        }
    }
});

// Assinaturas - Criar
$('btn-kick-subs-create').addEventListener('click', async () => {
    if (!confirm('Criar assinatura chat.message.sent v1 para este webhook?')) return;

    logChat('kick', 'Criando assinatura...');
    $('btn-kick-subs-create').disabled = true;

    try {
        const r = await fetch('/api/kick/subscriptions/create', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
        });
        const data = await r.json();

        if (!r.ok) {
            $('kick-sub-error').textContent = data.detail || data.message || 'Erro ao criar';
            throw new Error(data.detail || data.message || 'Falhou');
        }

        logChat('kick', `✅ Assinatura criada (${data.subscription?.name || 'chat.message.sent'})`, 'ok');
        $('kick-sub-error').textContent = '';

        // Atualizar lista
        $('btn-kick-subs-list').click();

        // Refresh state
        const sr = await fetch('/api/state');
        state = await sr.json();
        updateKickState(state);
        renderKick();
    } catch (e) {
        logChat('kick', '❌ ' + e.message, 'err');
        $('btn-kick-subs-create').disabled = false;
    }
});

// Função global para deletar assinatura (chamada do botão inline)
window.deleteKickSub = async function(subscriptionId) {
    if (!confirm('Cancelar esta assinatura?')) return;

    logChat('kick', 'Cancelando assinatura...');

    try {
        const r = await fetch('/api/kick/subscriptions/delete', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ subscription_id: subscriptionId }),
        });
        const data = await r.json();

        if (!r.ok) {
            $('kick-sub-error').textContent = data.detail || data.message || 'Erro ao cancelar';
            throw new Error(data.detail || 'Falhou');
        }

        logChat('kick', '✅ Assinatura cancelada', 'ok');
        $('kick-sub-error').textContent = '';

        // Atualizar lista
        $('btn-kick-subs-list').click();

        // Refresh state
        const sr = await fetch('/api/state');
        state = await sr.json();
        updateKickState(state);
        renderKick();
    } catch (e) {
        if (e.message !== 'Falhou') {
            logChat('kick', '❌ ' + e.message, 'err');
        }
    }
};

// ============================================================================
// ABA SORTEIO
// ============================================================================
function renderGiveaway() {
    const g = state.giveaway || {};
    const running = g.is_running;
    const paused = g.is_paused;
    const hasWinner = !!g.current_winner;

    // Status
    let stateText = 'parado';
    if (running && !paused) stateText = 'aberto';
    else if (running && paused) stateText = '⏸ pausado';
    $('giveaway-state').textContent = stateText;
    $('giveaway-status-badge').classList.toggle('open', !!running && !paused);
    for(const platform of ['twitch','kick']) {
        const active=!!running && !paused && !!g['entry_open_'+platform];
        const light=$('giveaway-'+platform+'-light');light.classList.toggle('active',active);
        light.setAttribute('aria-label',`Coleta ${platform==='twitch'?'Twitch':'Kick'} ${active?'aberta':'desligada'}`);
    }
    window.renderGiveawayPrizes?.();
    if(!giveawayWeightsDirty)for(const platform of ['twitch','kick'])for(const group of ['sub','vip','mod']) {
        $('weight-'+platform+'-'+group).value=weightLabel(1+Number(state.permissions.multipliers?.[platform]?.[group] || 0));
    }
    $('giveaway-entry').classList.toggle('success', !!running && !paused);
    if(!$('giveaway-keyword').dataset.loaded) {
        $('giveaway-keyword').value=g.keyword || '';
        $('giveaway-keyword').dataset.loaded='1';
    }
    $('giveaway-cur-keyword').textContent = g.keyword || '-';
    $('giveaway-count').textContent = g.count || 0;
    $('giveaway-status').textContent = g.status || '-';

    if (running && !paused && (g.entry_open_twitch || g.entry_open_kick)) {
        $('giveaway-entry').textContent =
            [g.entry_open_twitch ? 'Twitch' : '', g.entry_open_kick ? 'Kick' : ''].filter(Boolean).join(' + ') || 'fechada';
    } else {
        $('giveaway-entry').textContent = 'fechada';
    }

    // Vencedor atual
    const wDisp = $('giveaway-current-winner');
    const tDisp = $('giveaway-timer-display');
    if (hasWinner) {
        const w = g.current_winner;
        wDisp.classList.add('show');
        wDisp.innerHTML = `
            <div class="winner-name">🏆 ${w.username}</div>
            <div class="winner-meta">
                ${w.platform.toUpperCase()} • peso ${weightLabel(w.weight)}x •
                chance ${w.chance_pct.toFixed(2)}% • ${w.award}
            </div>`;
        if (g.winner_deadline > 0) {
            tDisp.classList.add('show');
            updateTimerDisplay();
        } else {
            tDisp.classList.remove('show');
        }
    } else {
        wDisp.classList.remove('show');
        tDisp.classList.remove('show');
    }

    const altWinner = $('giveaway-current-winner-alt');
    altWinner.innerHTML = hasWinner ? wDisp.innerHTML : '';
    altWinner.classList.toggle('show', hasWinner);
    $('giveaway-no-winner').style.display = hasWinner ? 'none' : '';

    // Botões
    $('btn-giveaway-start').disabled = running;
    $('btn-giveaway-pause').disabled = !running || paused;
    $('btn-giveaway-resume').disabled = !running || !paused;
    $('btn-giveaway-stop').disabled = !running;
    $('btn-giveaway-reset').disabled = !running && (g.count || 0) === 0;
    $('btn-giveaway-draw').disabled = !running || (g.eligible_count ?? g.count ?? 0)===0;
    $('btn-giveaway-draw').textContent=(g.draw_count || hasWinner)?'Sortear próximo':'Sortear vencedor';
    $('btn-giveaway-skip').disabled = !hasWinner;
    $('giveaway-auto-advance').checked=!!g.auto_advance_timeout;
    const suspenseLeft=Math.max(0,Math.ceil((g.draw_reveal_until||0)-Date.now()/1000));
    const drawStyles={roulette:'Roleta',slots:'Caça-níquel',countdown:'Contagem regressiva',cards:'Cartas',
        dice:'Dados',radar:'Radar',chest:'Baú',particles:'Estrelas',portal:'Portal',spotlights:'Holofotes'};
    $('giveaway-draw-animation-status').textContent=suspenseLeft
        ? `🎰 Animação no OBS: ${drawStyles[g.draw_animation_active]||g.draw_animation_active} · revelação em ${suspenseLeft}s. O cronômetro começa após isso.`
        : '';
    const nickFeedback=g.winner_chat?.nick_verification;
    const nickBox=$('giveaway-nick-feedback');
    nickBox.hidden=!nickFeedback;
    if(nickFeedback) {
        nickBox.dataset.status=nickFeedback.status||'checking';
        const titles={checking:'🔎 Consultando MEGAMU',waiting:'⏳ Aguarde para consultar novamente',
            error:'❌ Consulta não confirmada',success:'✅ Personagem confirmado'};
        $('giveaway-nick-feedback-title').textContent=(titles[nickFeedback.status]||titles.checking)+
            (nickFeedback.nick?` — ${nickFeedback.nick}`:'');
        $('giveaway-nick-feedback-result').textContent=nickFeedback.result||'';
        $('giveaway-nick-feedback-chat').textContent=nickFeedback.chat_sent===true
            ? '✓ Resultado enviado ao chat.'
            : nickFeedback.chat_sent===false
                ? 'Não enviado ao chat: '+(nickFeedback.chat_reason||'verifique Conexões → Mensagens automáticas.')
                : 'Consultando / aguardando resposta do bot...';
    }
    const feedback=g.captcha_feedback;
    $('giveaway-captcha-feedback').textContent=feedback ? `${feedback.username}: ${feedback.status==='correct'?'código correto e prêmio confirmado.':feedback.status==='wrong'?(feedback.exhausted?`tentativas esgotadas (correto: ${feedback.expected || '—'}). Aguarde decisão do organizador.`:`tentativa ${feedback.attempts}/${feedback.max_attempts || '∞'} incorreta. Pode tentar novamente.`):'prazo encerrado.'}` : '';

    // Enquanto salva, preservar o valor clicado contra atualizações de estado antigas.
    const perms=state.permissions || {};
    const values={
        'rule-viewers':perms.allow_viewers!==false,'rule-subs':perms.allow_subs!==false,
        'rule-vips':perms.allow_vips!==false,
        'rule-mods-twitch':perms.platform_mods?.twitch ?? !!perms.allow_mods,
        'rule-mods-kick':perms.platform_mods?.kick ?? !!perms.allow_mods,
        'rule-entry-twitch':g.accept_entries_twitch ?? g.entry_open_twitch,
        'rule-entry-kick':g.accept_entries_kick ?? g.entry_open_kick,
        'rule-repeat':!!g.block_repeat_winner,
    };
    for(const [id,value] of Object.entries(values)) {
        $(id).checked=pendingRules.has(id)?pendingRules.get(id).value:!!value;
        $(id).disabled=pendingRules.has(id);
    }
    $('giveaway-antibot').textContent = state.antibot.enabled ? 'Ativo' : 'Inativo';

    // Timer input
    if (!running && $('giveaway-timer').value !== String(g.timer || 60)) {
        $('giveaway-timer').value = g.timer || 60;
    }

    renderInlineParticipants();
    // Tabela de vencedores (do histórico local)
    refreshWinnersTable();
}

function updateTimerDisplay() {
    const g = state.giveaway || {};
    const tDisp = $('giveaway-timer-display');
    if (!g.winner_deadline || !g.current_winner) {
        tDisp.classList.remove('show');
        return;
    }
    const remaining = Math.max(0, Math.ceil(g.winner_deadline - Date.now() / 1000));
    tDisp.textContent = `⏱ ${remaining}s`;
    tDisp.classList.toggle('ok', g.current_winner.answered);
}

async function refreshWinnersTable() {
    try {
        const r = await fetch('/api/giveaway/winners');
        const data = await r.json();
        const winners = data.winners || [];
        const tbody = $('winners-tbody');
        if (winners.length === 0) {
            tbody.innerHTML = '<tr><td colspan="7" class="hint">Nenhum vencedor ainda.</td></tr>';
            return;
        }
        tbody.innerHTML = winners.map((w, i) => `
            <tr>
                <td>${i + 1}</td>
                <td>${w.platform}</td>
                <td><strong>${w.username}</strong></td>
                <td>${weightLabel(w.weight)}x</td>
                <td>${w.chance_pct.toFixed(2)}%</td>
                <td>${w.award || '-'}</td>
                <td>${w.answered ? '✅' : '⏳'}</td>
            </tr>
        `).join('');
    } catch (e) {
        console.error('Erro ao carregar vencedores:', e);
    }
}

// ============================================================================
// ABA PARTICIPANTES
// ============================================================================
let participantsData = [];
function renderParticipants() {
    participantsData = state.participants || [];
    applyParticipantFilters();
}

function applyParticipantFilters() {
    const search = $('part-search').value.toLowerCase().trim();
    const platform = $('part-platform').value;
    const type = $('part-type').value;
    const status = $('part-status').value;

    let filtered = participantsData.filter(p => {
        if (search && !p.username.toLowerCase().includes(search)) return false;
        if (platform && p.platform !== platform) return false;
        if (type === 'viewer' && (p.is_sub || p.is_vip || p.is_mod)) return false;
        if (type === 'sub' && !p.is_sub) return false;
        if (type === 'vip' && !p.is_vip) return false;
        if (type === 'mod' && !p.is_mod) return false;
        if (status === 'active' && p.active === false) return false;
        if (status === 'inactive' && p.active !== false) return false;
        return true;
    });

    const activeCount = participantsData.filter(p => p.active !== false).length;
    $('part-count').textContent = `${filtered.length} exibidos • ${activeCount} ativos • ${participantsData.length - activeCount} inativos`;

    const tbody = $('participants-tbody');
    if (filtered.length === 0) {
        tbody.innerHTML = '<tr><td colspan="8" class="hint">Nenhum participante encontrado.</td></tr>';
        return;
    }
    tbody.innerHTML = filtered.map(p => {
        const badges = [];
        if (p.is_sub) badges.push('<span class="badge sub">SUB</span>');
        if (p.is_vip) badges.push('<span class="badge vip">VIP</span>');
        if (p.is_mod) badges.push('<span class="badge mod">MOD</span>');
        if (p.is_owner) badges.push('<span class="badge mod">OWNER</span>');
        const firstSeen = new Date(p.first_seen * 1000).toLocaleTimeString();
        const active = p.active !== false;
        const chance = Math.max(0, Math.min(100, Number(p.chance_pct) || 0));
        const current = state.giveaway?.current_winner;
        const locked = current && current.platform === p.platform && current.username.toLowerCase() === p.username.toLowerCase();
        const attributes = `data-platform="${escapeHtml(p.platform)}" data-username="${escapeHtml(p.username)}"`;
        const statusLabel = active ? '✅ ATIVO' : '⛔ INATIVO';
        const changed = p.active_changed_at
            ? `<small class="participant-changed">${active ? 'Reativado' : 'Desativado'} às ${new Date(p.active_changed_at * 1000).toLocaleTimeString('pt-BR', {hour:'2-digit',minute:'2-digit'})}</small>`
            : '';
        const initial = p.username[0] ? p.username[0].toUpperCase() : '?';
        const avatarCell = p.avatar_url
            ? `<img class="avatar" src="${escapeHtml(p.avatar_url)}" alt="" onerror="this.outerHTML='<div class=avatar-fallback>${escapeHtml(initial)}</div>'">`
            : `<div class="avatar-fallback">${escapeHtml(initial)}</div>`;
        return `
            <tr class="${p.is_winner ? 'winner' : ''} ${active ? '' : 'participant-inactive'}">
                <td class="platform-cell ${p.platform}">${p.platform}</td>
                <td><button type="button" class="participant-name-toggle participant-toggle" ${attributes} ${locked ? 'disabled title="Vencedor atual: finalize antes de alterar"' : `title="Clique para ${active ? 'desativar' : 'reativar'}"`} aria-label="${active ? 'Desativar' : 'Reativar'} ${escapeHtml(p.username)}">${avatarCell}<strong>${escapeHtml(p.username)}</strong></button></td>
                <td>${badges.join(' ') || 'viewer'}</td>
                <td>${weightLabel(p.weight)}x</td>
                <td><div class="participant-chance"><strong>${chance.toFixed(2).replace('.',',')}%</strong><span class="participant-chance-track"><span style="width:${chance}%"></span></span></div></td>
                <td><button type="button" class="participant-status-toggle participant-toggle ${active ? 'is-active' : 'is-inactive'}" ${attributes} ${locked ? 'disabled title="Vencedor atual: finalize antes de alterar"' : ''} aria-pressed="${!active}">${statusLabel}</button>${changed}</td>
                <td>${p.is_winner ? '🏆' : '-'}</td>
                <td>${firstSeen}</td>
            </tr>
        `;
    }).join('');
}

$('part-search').addEventListener('input', applyParticipantFilters);
$('part-platform').addEventListener('change', applyParticipantFilters);
$('part-type').addEventListener('change', applyParticipantFilters);
$('part-status').addEventListener('change', applyParticipantFilters);
$('participants-tbody').addEventListener('click', async event => {
    const button = event.target.closest('.participant-toggle');
    if (!button || button.disabled) return;
    const {platform, username} = button.dataset;
    button.disabled = true;
    $('part-feedback').textContent = `Atualizando a participação de ${username}...`;
    try {
        const result = await post('/api/giveaway/participants/toggle', {platform, username});
        const refreshed = await fetch('/api/state');
        if (refreshed.ok) state = await refreshed.json();
        renderParticipants();
        renderInlineParticipants();
        $('part-feedback').textContent = result.active
            ? `✅ ${result.username} reativado: voltou a concorrer, se ainda for elegível.`
            : `⛔ ${result.username} desativado: não pode ser sorteado. Clique novamente para reativar.`;
    } catch (error) {
        $('part-feedback').textContent = `❌ Não foi possível alterar ${username}: ${error.message}`;
        button.disabled = false;
    }
});

// ============================================================================
// HANDLERS DOS BOTÕES DE SORTEIO
// ============================================================================
$('btn-giveaway-messages').onclick=()=> {
    document.querySelector('.tab[data-tab="messages"]').click();
};
async function post(url, body) {
    const r = await fetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body || {}),
    });
    const data = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(data.detail || data.message || 'falhou');
    return data;
}

$('btn-giveaway-start').addEventListener('click', async () => {
    const keyword = $('giveaway-keyword').value.trim();
    if (!keyword) { alert('Informe a palavra-chave.'); return; }
    const timer = parseInt($('giveaway-timer').value, 10) || 60;
    // Não iniciar com regras que o servidor não conseguiu salvar.
    try {await applyRules();await post('/api/giveaway/timer',{seconds:timer});}
    catch(error){alert('Não foi possível salvar as regras: '+error.message);return;}
    try {
        const r = await fetch('/api/giveaway/start', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ keyword }),
        });
        const data = await r.json();
        if (!r.ok) throw new Error(data.detail || 'falhou');
        $('giveaway-announcement-result').textContent=Object.entries(data.announcements || {}).map(([platform,result])=>
            `${platform==='twitch'?'Twitch':'Kick'}: ${result.sent?'abertura anunciada no chat':result.reason}`
        ).join(' • ');
        // Atualiza timer
        await fetch('/api/state');  // força refresh
        if (timer !== (state.giveaway.timer || 60)) {
            STATE_TIMER_LOCAL = timer;  // atualização local
        }
    } catch (e) {
        alert('Erro ao iniciar: ' + e.message);
    }
});
let STATE_TIMER_LOCAL = null;

$('btn-giveaway-pause').addEventListener('click', async () => {
    try { await post('/api/giveaway/pause'); } catch (e) { alert(e.message); }
});
$('btn-giveaway-resume').addEventListener('click', async () => {
    try { await post('/api/giveaway/resume'); } catch (e) { alert(e.message); }
});
$('btn-giveaway-stop').addEventListener('click', async () => {
    if (!confirm('Encerrar o sorteio atual? A lista de participantes será mantida.')) return;
    try { await post('/api/giveaway/stop'); } catch (e) { alert(e.message); }
});
$('btn-giveaway-reset').addEventListener('click', async () => {
    if (!confirm('Resetar TUDO (participantes, vencedor, status)?')) return;
    try { await post('/api/giveaway/reset'); } catch (e) { alert(e.message); }
});
$('btn-giveaway-draw').addEventListener('click', async () => {
    if(state?.giveaway.current_winner && !confirm('Substituir o vencedor atual e sortear o próximo da mesma lista?'))return;
    try { await post('/api/giveaway/next', {}); } catch (e) { alert(e.message); }
});
$('giveaway-auto-advance').addEventListener('change', async () => {
    try {await post('/api/giveaway/auto-advance',{enabled:$('giveaway-auto-advance').checked});} catch(error){alert(error.message);}
});
$('giveaway-timer').addEventListener('change', async () => {
    if (!$('giveaway-timer').reportValidity()) return;
    try {await post('/api/giveaway/timer',{seconds:Number($('giveaway-timer').value)});} catch(error){alert(error.message);}
});
$('btn-giveaway-skip').addEventListener('click', async () => {
    if (!confirm('Pular este vencedor e re-sortear?')) return;
    try { await post('/api/giveaway/skip'); } catch (e) { alert(e.message); }
});

async function applyRules() {
    await ruleSaveQueue;
    const rules = {
        allow_viewers: $('rule-viewers').checked,
        allow_subs: $('rule-subs').checked,
        allow_vips: $('rule-vips').checked,
        platform_mods: Object.fromEntries(['twitch','kick'].map(platform=>[platform,$('rule-mods-'+platform).checked])),
        entry_open_twitch: $('rule-entry-twitch').checked,
        entry_open_kick: $('rule-entry-kick').checked,
        block_repeat_winner: $('rule-repeat').checked,
    };
    await post('/api/permissions',rules);
}

const ruleFields={'rule-viewers':'allow_viewers','rule-subs':'allow_subs','rule-vips':'allow_vips',
    'rule-entry-twitch':'entry_open_twitch','rule-entry-kick':'entry_open_kick','rule-repeat':'block_repeat_winner',
    'rule-mods-twitch':'platform_mods','rule-mods-kick':'platform_mods'};
for(const [id,field] of Object.entries(ruleFields)) {
    $(id).addEventListener('change',()=>{
        const value=$(id).checked;
        const marker={value};pendingRules.set(id,marker);$(id).disabled=true;
        const payload=field==='platform_mods'?{platform_mods:{[id.endsWith('twitch')?'twitch':'kick']:value}}:{[field]:value};
        $('giveaway-rules-feedback').textContent='Salvando regras…';
        ruleSaveQueue=ruleSaveQueue.then(async()=>{
            try {
                await post('/api/permissions',payload);
                $('giveaway-rules-feedback').textContent='Regras salvas e aplicadas.';
            } catch(error) {
                $('giveaway-rules-feedback').textContent='Não foi possível salvar: '+error.message;
            } finally {
                try {
                    const response=await fetch('/api/state',{cache:'no-store'});
                    if(response.ok)state=await response.json();
                } catch(_){}
                if(pendingRules.get(id)===marker)pendingRules.delete(id);
                $(id).disabled=false;
                render();
            }
        }).catch(error=>{
            pendingRules.delete(id);$(id).disabled=false;
            $('giveaway-rules-feedback').textContent='Não foi possível salvar: '+error.message;
        });
    });
}

// Tick do timer (atualiza display a cada 1s)
setInterval(() => {
    const captcha = state?.giveaway?.captcha;
    if (captcha) $('antibot-timer-display').textContent = `⏱ ${Math.max(0, Math.ceil(captcha.deadline - Date.now()/1000))}s`;
    if (state && state.giveaway && state.giveaway.current_winner && state.giveaway.winner_deadline > 0) {
        updateTimerDisplay();
    }
}, 1000);

// Polling de segurança (caso o WebSocket caia)
setInterval(async () => {
    try {
        const r = await fetch('/api/state');
        state = await r.json();
        render();
    } catch (e) {}
}, 5000);


// ============================================================================
// ABA ANTI-BOT / CAPTCHÁ
// ============================================================================
let antibotFormDirty = false;
document.querySelector('[data-panel="antibot"]').addEventListener('input', e => {
    if (e.target.id.startsWith('antibot-') && !e.target.id.startsWith('antibot-marked-') && e.target.id !== 'antibot-answer') {
        antibotFormDirty = true;
        $('antibot-save-status').textContent = 'Alterações não salvas';
    }
});
function renderAntibot() {
    const a = state.antibot || {};
    // carrega valores nos inputs (só se a aba não tiver sido editada)
    const setIfUnset = (id, val) => {
        const el = $(id);
        if (!el) return;
        if (!antibotFormDirty && document.activeElement !== el) {
            if (el.type === 'checkbox') el.checked = !!val;
            else el.value = val;
        }
    };
    setIfUnset('antibot-enabled', a.enabled);
    setIfUnset('antibot-waive', a.waive_subs_vips);
    const types = a.types || {};
    setIfUnset('antibot-type-math', types.math);
    setIfUnset('antibot-type-word', types.word);
    setIfUnset('antibot-type-code', types.code);
    $('antibot-timer').value=state.giveaway.timer;
    setIfUnset('antibot-chance', a.random_chance);
    setIfUnset('antibot-max-attempts', a.max_attempts ?? 3);
    setIfUnset('antibot-send-chat', a.send_to_chat);

    $('ab-kpi-enabled').textContent = a.enabled ? 'Ativada' : 'Desativada';
    $('ab-kpi-enabled').classList.toggle('success', !!a.enabled);
    $('ab-kpi-chance').textContent = `${a.random_chance ?? 50}%`;
    $('ab-kpi-marked').textContent = (a.marked || []).length;
    $('ab-selection-badge').textContent = a.enabled ? 'Ativa · na inscrição' : 'Desativada';
    renderMarkedParticipants();
    // Captcha atual
    const c = (state.giveaway || {}).captcha;
    const card = $('antibot-current-card');
    if (c) {
        card.style.display = '';
        $('antibot-current-display').innerHTML = `
            <div class="winner-name">${escapeHtml(c.username || "Vencedor")} · ${escapeHtml(c.question)}</div>
            <div class="winner-meta">
                Tipo: ${c.type.toUpperCase()} • presença confirmada · cronômetro encerrado • Plataforma: ${c.platform}
                • Tentativa ${Number(c.attempts||0)} de ${Number(c.max_attempts)||'∞'}
                <span class="hint" id="antibot-hint" style="margin-left:8px"></span>
            </div>`;
        $('antibot-timer-display').classList.toggle('show', !!c.deadline);
        if (c.deadline) $('antibot-timer-display').textContent = `⏱ ${Math.max(0, Math.ceil(c.remaining || 0))}s`;
        $('btn-antibot-answer').disabled = false;
        $('btn-antibot-confirm').hidden = true;
        // busca resposta esperada (admin only) e mostra discreto
        fetch('/api/giveaway/captcha/full').then(r => r.json()).then(full => {
            const hint = $('antibot-hint');
            if (hint && full && full.expected) {
                hint.textContent = `· esperado: ${escapeHtml(full.expected)}`;
            }
        });
    } else if (state.giveaway?.current_winner?.captcha_failed) {
        card.style.display = '';
        const feedback = state.giveaway.captcha_feedback || {};
        $('antibot-current-display').innerHTML = `<div class="winner-name">❌ Resposta incorreta de ${escapeHtml(feedback.username || 'vencedor')}</div><div class="winner-meta">A correta era: <strong>${escapeHtml(feedback.expected || '—')}</strong>. Aguarde a decisão do organizador.</div>`;
        $('antibot-timer-display').classList.remove('show');
        $('btn-antibot-answer').disabled = true;
        $('btn-antibot-confirm').hidden = false;
    } else {
        card.style.display = 'none';
        $('btn-antibot-confirm').hidden = true;
    }
}

$('btn-antibot-save').addEventListener('click', async () => {
    if (!$('antibot-chance').reportValidity() || !$('antibot-timer').reportValidity() || !$('antibot-max-attempts').reportValidity()) return;
    const body = {
        enabled: $('antibot-enabled').checked,
        waive_subs_vips: $('antibot-waive').checked,
        types: {
            math: $('antibot-type-math').checked,
            word: $('antibot-type-word').checked,
            code: $('antibot-type-code').checked,
        },
        timer: parseInt($('antibot-timer').value) || 30,
        random_chance: Number($('antibot-chance').value),
        max_attempts: Number($('antibot-max-attempts').value),
        send_to_chat: $('antibot-send-chat').checked,
    };
    try {
        const r = await fetch('/api/antibot/config', {
            method: 'POST', headers: {'Content-Type': 'application/json'},
            body: JSON.stringify(body),
        });
        if (r.ok) {
            antibotFormDirty = false;
            $('antibot-save-status').textContent = '✅ Salvo · limite vale para os próximos desafios';
            setTimeout(() => { if (!antibotFormDirty) $('antibot-save-status').textContent = ''; }, 4000);
        } else {
            const data = await r.json();
            $('antibot-save-status').textContent = typeof data.detail === 'string' ? data.detail : 'Confira os valores e os tipos de desafio.';
        }
    } catch (e) {
        $('antibot-save-status').textContent = '❌ Erro: ' + e;
    }
});

$('btn-antibot-answer').addEventListener('click', async () => {
    const ans = $('antibot-answer').value.trim();
    if (!ans) {
        $('antibot-status').textContent = 'Digite a resposta.';
        return;
    }
    try {
        const r = await fetch('/api/giveaway/captcha/answer', {
            method: 'POST', headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({answer: ans}),
        });
        const data = await r.json();
        if (data.ok) {
            $('antibot-status').textContent = '✅ Correto! Vencedor confirmado.';
            $('antibot-answer').value = '';
        } else {
            $('antibot-status').textContent = '❌ ' + (data.detail || data.status);
            if (data.status === 'wrong' || data.status === 'expired') {
                $('antibot-answer').value = '';
            }
        }
    } catch (e) {
        $('antibot-status').textContent = '❌ Erro: ' + e;
    }
});

$('btn-antibot-reissue').addEventListener('click', async () => {
    try {
        const r = await fetch('/api/giveaway/captcha/reissue', {method: 'POST'});
        const data = await r.json();
        if (data.ok) {
            $('antibot-status').textContent = '🔄 Novo código gerado (o relógio de presença permanece parado).';
        } else {
            $('antibot-status').textContent = '❌ ' + (data.detail || 'erro');
        }
    } catch (e) {
        $('antibot-status').textContent = '❌ Erro: ' + e;
    }
});

$('btn-antibot-confirm').addEventListener('click', async () => {
    if (!confirm('O código foi digitado incorretamente. Confirmar o prêmio mesmo assim, por decisão manual?')) return;
    try {
        const r = await fetch('/api/giveaway/answer', {method: 'POST'});
        const data = await r.json();
        $('antibot-status').textContent = r.ok ? '✅ Prêmio confirmado manualmente.' : '❌ ' + (data.detail || 'Falha ao confirmar.');
    } catch (e) {
        $('antibot-status').textContent = '❌ Erro: ' + e;
    }
});

$('btn-antibot-skip').addEventListener('click', async () => {
    if (!confirm('Pular o vencedor atual e re-sortear?')) return;
    try {
        const r = await fetch('/api/giveaway/skip', {method: 'POST'});
        if (r.ok) {
            $('antibot-status').textContent = '⏭ Vencedor pulado.';
            $('antibot-answer').value = '';
        }
    } catch (e) {
        $('antibot-status').textContent = '❌ Erro: ' + e;
    }
});

function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, m => ({
        '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
    }[m]));
}


// ============================================================================
// ABA AUDITORIA / FAIRNESS / EXPORT
// ============================================================================
let auditFilter = '';
let fairnessCache = null;

async function renderAudit() {
    // fairness
    try {
        const r = await fetch('/api/fairness/report');
        const fr = await r.json();
        fairnessCache = fr;
        $('fr-total').textContent = fr.total_winners;
        $('fr-unique').textContent = fr.unique_winner_usernames;
        $('fr-unique-pct').textContent = `${fr.unique_winner_pct}% únicos`;
        $('fr-multi').textContent = fr.multi_winners;
        $('fr-part').textContent = fr.current_participants;
        $('fr-never').textContent = `${fr.never_won} nunca ganharam`;

        const platDiv = $('fr-platform');
        platDiv.innerHTML = Object.keys(fr.wins_by_platform).length
            ? Object.entries(fr.wins_by_platform).map(([k, v]) =>
                `<div><code>${escapeHtml(k)}</code></div><div>${v}</div>`).join('')
            : '<div class="hint">nenhum vencedor</div>';

        const tWins = $('fr-type-wins');
        tWins.innerHTML = Object.keys(fr.wins_by_type).length
            ? Object.entries(fr.wins_by_type).map(([k, v]) =>
                `<div><code>${escapeHtml(k)}</code></div><div>${v}</div>`).join('')
            : '<div class="hint">-</div>';

        const tParts = $('fr-type-parts');
        tParts.innerHTML = Object.keys(fr.participants_by_type).length
            ? Object.entries(fr.participants_by_type).map(([k, v]) =>
                `<div><code>${escapeHtml(k)}</code></div><div>${v}</div>`).join('')
            : '<div class="hint">pool vazia</div>';

        const top = $('fr-top');
        if (fr.top_winners.length) {
            top.innerHTML = fr.top_winners.map(w =>
                `<li><strong>${escapeHtml(w.username)}</strong> — ${w.wins}x</li>`).join('');
        } else {
            top.innerHTML = '<li class="hint">nenhum vencedor ainda</li>';
        }
    } catch (e) {
        console.error('fairness', e);
    }

    // audit
    try {
        const url = new URL('/api/audit/list', location.origin);
        url.searchParams.set('limit', '300');
        if (auditFilter) url.searchParams.set('action', auditFilter);
        const r = await fetch(url);
        const data = await r.json();
        const events = data.events || [];
        const tbody = $('audit-tbody');
        if (events.length === 0) {
            tbody.innerHTML = '<tr><td colspan="4" class="hint">Nenhum evento.</td></tr>';
            return;
        }
        tbody.innerHTML = events.map(ev => {
            const payload = JSON.stringify(ev.payload || {});
            return `<tr>
                <td>${escapeHtml(ev.ts_human || '-')}</td>
                <td>${escapeHtml(ev.actor || '-')}</td>
                <td><code>${escapeHtml(ev.action || '-')}</code></td>
                <td><code>${escapeHtml(payload.length > 100 ? payload.slice(0, 100) + '…' : payload)}</code></td>
            </tr>`;
        }).join('');
    } catch (e) {
        console.error('audit', e);
    }
}

let auditFilterTimer = null;
$('audit-filter').addEventListener('input', (e) => {
    clearTimeout(auditFilterTimer);
    auditFilterTimer = setTimeout(() => {
        auditFilter = e.target.value.trim();
        renderAudit();
    }, 300);
});

// Export CSV (abre direto, Content-Disposition attachment força download)
$('btn-export-participants').addEventListener('click', () => {
    location.href = '/api/export/participants.csv';
});
$('btn-export-winners').addEventListener('click', () => {
    location.href = '/api/export/winners.csv';
});
$('btn-export-audit').addEventListener('click', () => {
    location.href = '/api/export/audit.csv';
});


// ============================================================================
// ABA ROLETA
// ============================================================================
// Rascunho de edição: id → {name, icon, weight, active}
// Preservado entre atualizações do WebSocket.
let roletaDraft = {};
let roletaServerItems = []; // ids dos últimos itens do servidor
let roletaSaving = false;
let roletaConfigDirty = false;
let roletaSpinSubmitting = false;

function _toFloat(v) {
    // Aceita vírgula e ponto como separador decimal (pt-BR)
    if (v === null || v === undefined || v === '') return NaN;
    const s = String(v).trim().replace(',', '.');
    return parseFloat(s);
}

function _applyDraft(item) {
    const d = roletaDraft[item.id];
    if (!d) return item;
    return {
        id: item.id,
        name: d.name !== undefined ? d.name : item.name,
        icon: d.icon !== undefined ? d.icon : item.icon,
        weight: d.weight !== undefined ? d.weight : item.weight,
        active: d.active !== undefined ? d.active : item.active,
    };
}

function _renderRoletaItems(items) {
    const list = $('roleta-items-list');
    if (items.length === 0) {
        list.innerHTML = '<p class="hint">Nenhum item. Adicione um abaixo.</p>';
        return;
    }

    // Soma dos pesos ativos (usando valores do rascunho quando disponíveis)
    const activeItems = items.map(_applyDraft).filter(i => i.active);
    const totalW = activeItems.reduce((s, i) => s + (_toFloat(i.weight) || 0), 0);

    list.innerHTML = items.map((it) => {
        const draft = roletaDraft[it.id] || {};
        const name = draft.name !== undefined ? draft.name : it.name;
        const icon = draft.icon !== undefined ? draft.icon : it.icon;
        const weight = draft.weight !== undefined ? draft.weight : it.weight;
        const active = draft.active !== undefined ? draft.active : it.active;
        const pct = active ? (totalW > 0 ? ((_toFloat(weight) || 0) / totalW * 100) : 100 / activeItems.length) : 0;
        const isDirty = !!roletaDraft[it.id];

        return `
        <div class="roleta-item ${isDirty ? 'dirty' : ''}" data-id="${it.id}">
            <label class="ri-field">Nome do prêmio<input type="text" class="ri-name" value="${escapeHtml(name)}"
                   placeholder="Nome do prêmio" data-field="name"></label>
            <label class="ri-field">Ícone<input type="text" class="ri-icon" value="${escapeHtml(icon)}"
                   maxlength="12" data-field="icon"></label>
            <label class="ri-field">Peso relativo<input type="number" class="ri-weight" value="${escapeHtml(weight)}"
                   min="0" step="any"
                   title="Valor salvo sem alteração; a chance real usa a soma dos pesos ativos" data-field="weight"></label>
            <span class="roleta-pct"><span>Chance real</span><strong>${pct.toFixed(1)}%</strong></span>
            <label class="check ri-enabled" style="margin:0">
                <input type="checkbox" class="ri-active" ${active ? 'checked' : ''}
                       data-field="active"> ativo
            </label>
            <button class="btn danger del" data-id="${it.id}" title="Excluir prêmio" aria-label="Excluir prêmio ${escapeHtml(name)}">Excluir</button>
        </div>`;
    }).join('');

    // Delegação de eventos — um listener no container, não em cada campo
    list.querySelectorAll('.roleta-item').forEach(row => {
        const id = parseInt(row.dataset.id);

        // Input de texto/número
        row.querySelectorAll('input[data-field]').forEach(inp => {
            inp.addEventListener('input', () => {
                const field = inp.dataset.field;
                let val = inp.type === 'checkbox' ? inp.checked : inp.value;
                // Converte vírgula decimal em ponto (pt-BR) e atualiza o campo
                if (field === 'weight' && typeof val === 'string') {
                    const converted = val.replace(',', '.');
                    if (converted !== val) {
                        inp.value = converted;
                        val = converted;
                    }
                }
                _setDraft(id, field, val);
            });
        });
    });

    // Botão excluir
    list.querySelectorAll('.btn.del').forEach(b => {
        b.addEventListener('click', async () => {
            if (!confirm('Excluir este item?')) return;
            try {
                await fetch('/api/roleta/items/' + b.dataset.id, {method: 'DELETE'});
            } catch (e) {
                $('roleta-status').textContent = '❌ ' + e;
            }
        });
    });

    _updateSaveHint();
}

function _setDraft(id, field, value) {
    if (!roletaDraft[id]) roletaDraft[id] = {};
    roletaDraft[id][field] = value;
    _updateSaveHint();
    _updateRowDirty(id);
    refreshDraftChances();
}

function _updateRowDirty(id) {
    const row = document.querySelector(`.roleta-item[data-id="${id}"]`);
    if (!row) return;
    if (roletaDraft[id]) {
        row.classList.add('dirty');
    } else {
        row.classList.remove('dirty');
    }
}

function _updateSaveHint() {
    const dirty = Object.keys(roletaDraft).length > 0 || roletaConfigDirty;
    const hint = $('roleta-save-hint');
    const btn = $('btn-roleta-save-all');
    if (hint) {
        hint.style.display = dirty ? '' : 'none';
        if (dirty) hint.textContent = 'Alterações não salvas';
    }
    if (btn) btn.style.display = '';
}

function _clearDraft() {
    roletaDraft = {};
    roletaConfigDirty = false;
    _updateSaveHint();
}

async function renderRoleta() {
    const r = (state.roleta || {});
    const items = r.items || [];

    // Detecta se a lista de ids mudou (item adicionado/removido)
    const newIds = items.map(i => i.id).sort().join(',');
    const oldIds = roletaServerItems.sort().join(',');

    if (newIds !== oldIds) {
        // Novos/removidos: descarta rascunho dos itens que sumiram
        const newIdSet = new Set(items.map(i => i.id));
        for (const id of Object.keys(roletaDraft)) {
            if (!newIdSet.has(parseInt(id))) delete roletaDraft[id];
        }
        roletaServerItems = items.map(i => i.id);
    }

    // Sempre reconstrói — mas usa valores do rascunho quando existir
    if (!roletaSaving && !document.activeElement?.closest('.roleta-item')) _renderRoletaItems(items);

    // Carrega config de duração/voltas (não bloqueia se já tiver valor digitado)
    const durEl = $('roleta-duration');
    const spinsEl = $('roleta-spins');
    if (durEl && !durEl.dataset.loaded && r.duration_seconds !== undefined) {
        durEl.value = r.duration_seconds; durEl.dataset.loaded = '1';
        $('roleta-auto-hide').checked = r.auto_hide;
        $('roleta-equal-slices').checked = !!r.equal_slices;
        $('roleta-result-seconds').value = r.result_seconds;
    }
    if (spinsEl && !spinsEl.dataset.loaded && r.extra_spins !== undefined) {
        spinsEl.value = r.extra_spins; spinsEl.dataset.loaded = '1';
    }

    if (!roletaConfigDirty) $('roleta-announce-chat').checked = !!state.chat_events.prize_won;
    const targets = ['twitch','kick'].filter(p => state.bots[p+'_enabled']).map(p => p === 'twitch' ? 'Twitch' : 'Kick');
    $('roleta-chat-destinations').textContent = targets.length
        ? 'Destinos habilitados: '+targets.join(' e ')+'. Exige conta conectada com permissão de escrita.'
        : 'Envio desligado: habilite Twitch ou Kick em Conexões, junto à plataforma.';
    $('btn-roleta-spin').disabled = roletaSpinSubmitting || roletaSaving || r.spinning || r.remaining > 0;
    $('btn-roleta-spin').textContent = r.spinning ? `Prêmio ${r.current || 1} de ${r.total || 1} · girando` : (r.remaining ? `Aguardando próximo giro · ${r.remaining}` : 'Girar agora');
    // Resultado atual
    if (r.result) {
        $('roleta-result').style.display = '';
        $('roleta-result-name').textContent = r.result;
        const winnerLine = $('roleta-result-winner');
        if (r.nick) {
            winnerLine.textContent = '👤 ' + r.nick;
        } else if (r.winner) {
            winnerLine.textContent = '🏆 ' + r.winner;
        } else {
            winnerLine.textContent = '🎲 Giro de teste';
        }
    } else {
        $('roleta-result').style.display = 'none';
    }

    // Histórico
    try {
        const hr = await fetch('/api/roleta/history?limit=20');
        const hd = await hr.json();
        const tbody = $('roleta-history-tbody');
        if (!hd.history || !hd.history.length) {
            tbody.innerHTML = '<tr><td colspan="4" class="hint">Nenhum giro.</td></tr>';
        } else {
            tbody.innerHTML = hd.history.map(h => {
                const ts = h.ts ? new Date(h.ts * 1000).toLocaleString() : '-';
                const nick = h.nick
                    ? escapeHtml(h.nick)
                    : '<span style="color:var(--text-faint)">—</span>';
                const winner = h.winner
                    ? escapeHtml(h.winner)
                    : '<span style="color:var(--text-faint)">—</span>';
                return `<tr>
                    <td>${escapeHtml(ts)}</td>
                    <td>${escapeHtml(h.prize || '-')}</td>
                    <td>${nick}</td>
                    <td>${winner}</td>
                </tr>`;
            }).join('');
        }
    } catch (e) {
        console.error('roleta history', e);
    }
}

$('btn-roleta-add').addEventListener('click', async () => {
    const body = {name: 'Novo prêmio', weight: 1.0, active: true, icon: '🎁'};
    try {
        await fetch('/api/roleta/items', {
            method: 'POST', headers: {'Content-Type': 'application/json'},
            body: JSON.stringify(body),
        });
    } catch (e) {
        $('roleta-status').textContent = '❌ ' + e;
    }
});

async function saveRoletaSettings() {
    if (roletaSaving) return false;
    roletaSaving = true;
    const btn = $('btn-roleta-save-all');
    const hint = $('roleta-save-hint');
    const locked = [...document.querySelectorAll('[data-panel="roleta"] input, [data-panel="roleta"] button, #event-prize_won')].map(el => [el, el.disabled]);
    locked.forEach(([el]) => {el.disabled = true;});
    hint.textContent = 'Salvando...';
    hint.style.display = '';
    $('roleta-status').textContent = '';

    const r = (state.roleta || {});
    const items = r.items || [];

    // Mescla servidor + rascunho
    const payload = items.map(it => {
        const draft = roletaDraft[it.id] || {};
        return {
            id: it.id,
            name: draft.name !== undefined ? draft.name.trim() : it.name,
            icon: draft.icon !== undefined ? draft.icon : it.icon,
            weight: draft.weight !== undefined ? _toFloat(draft.weight) : it.weight,
            active: draft.active !== undefined ? draft.active : it.active,
        };
    });

    try {
        const res = await fetch('/api/roleta/settings', {
            method: 'POST', headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({items: payload, duration_seconds: _toFloat($('roleta-duration').value), extra_spins: Number($('roleta-spins').value), auto_hide: $('roleta-auto-hide').checked, equal_slices: $('roleta-equal-slices').checked, result_seconds: Number($('roleta-result-seconds').value), announce_chat: $('roleta-announce-chat').checked}),
        });
        const data = await res.json();
        if (!res.ok) {
            $('roleta-status').textContent = '❌ ' + (typeof data.detail === 'string' ? data.detail : 'Confira os campos da roleta.');
            hint.textContent = $('roleta-status').textContent;
            return false;
        }
        state.roleta.items = data.items;
        if ($('event-prize_won')) $('event-prize_won').checked = $('roleta-announce-chat').checked;
        _clearDraft();
        $('roleta-status').textContent = '✅ Prêmios, animação e anúncio no chat salvos.';
        hint.textContent = 'Prêmios, animação e anúncio no chat salvos.';
        hint.style.display = '';
        return true;
    } catch (e) {
        $('roleta-status').textContent = '❌ Erro de conexão: ' + e.message;
        hint.textContent = 'Conexão falhou';
        return false;
    } finally {
        roletaSaving = false;
        locked.forEach(([el, wasDisabled]) => {el.disabled = wasDisabled;});
        btn.disabled = false;
        if (!Object.keys(roletaDraft).length) _renderRoletaItems(state.roleta?.items || []);
    }
}
$('btn-roleta-save-all').addEventListener('click', saveRoletaSettings);

window.markRoletaConfigDirty = () => { roletaConfigDirty = true; _updateSaveHint(); };
for (const id of ['roleta-duration','roleta-spins','roleta-auto-hide','roleta-equal-slices','roleta-result-seconds','roleta-announce-chat']) {
    $(id).addEventListener('input', window.markRoletaConfigDirty);
}
$('btn-roleta-chat-settings').addEventListener('click', () => {
    document.querySelector('.tab[data-tab="messages"]').click();
});

$('btn-roleta-spin').addEventListener('click', async () => {
    if (roletaSpinSubmitting || state.roleta?.spinning || state.roleta?.remaining) return;
    if (roletaSaving) {
        $('roleta-status').textContent = '⏳ Salvamento em andamento. Aguarde.';
        return;
    }

    const testMode = $('roleta-mode-teste').checked;
    const nick = $('roleta-nick').value.trim();

    if (!testMode && !nick) {
        $('roleta-status').textContent = '⚠ Informe o nick da pessoa ou marque "Giro de teste".';
        return;
    }

    roletaSpinSubmitting = true;
    $('btn-roleta-spin').disabled = true;
    try {
        if (Object.keys(roletaDraft).length > 0 || roletaConfigDirty) {
            $('roleta-status').textContent = 'Salvando alterações antes de girar...';
            if (!await saveRoletaSettings()) return;
        }
        $('roleta-status').textContent = '🎰 Enviando comando...';
        const res = await fetch('/api/roleta/spin', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({nick: nick || '', test_mode: testMode, attempts: Number($('roleta-attempts').value)}),
        });
        const data = await res.json();
        if (!res.ok) {
            $('roleta-status').textContent = '❌ ' + (typeof data.detail === 'string' ? data.detail : 'Confira o nick e a quantidade de prêmios.');
            return;
        }
        // Mostra resultado com nick
        $('roleta-result').style.display = '';
        $('roleta-result-name').textContent = data.item.name;
        const winnerLine = $('roleta-result-winner');
        if (data.nick) {
            winnerLine.textContent = '👤 ' + data.nick;
        } else {
            winnerLine.textContent = '🎲 Giro de teste';
        }
        $('roleta-status').textContent = '⏳ Aguardando overlay...';
        // Aguarda até 3s pela confirmação do overlay
        const startWait = Date.now();
        const waitForAck = setInterval(() => {
            const r = (state.roleta || {});
            if (r.overlay_acknowledged) {
                clearInterval(waitForAck);
                $('roleta-status').textContent = '🎰 Overlay girando';
            } else if (Date.now() - startWait > 3000) {
                clearInterval(waitForAck);
                $('roleta-status').textContent = '⚠ Overlay não respondeu. Verifique o browser source no OBS.';
            }
        }, 150);
    } catch (e) {
        $('roleta-status').textContent = '❌ ' + e.message;
    } finally {
        roletaSpinSubmitting = false;
        $('btn-roleta-spin').disabled = !!(state.roleta?.spinning || state.roleta?.remaining);
    }
});

$('btn-roleta-show').addEventListener('click', async () => {
    await fetch('/api/roleta/visible', {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({visible: true}),
    });
});
$('btn-roleta-hide').addEventListener('click', async () => {
    await fetch('/api/roleta/visible', {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({visible: false}),
    });
});


// ============================================================================
// ABA HISTÓRICO
// ============================================================================
let histSection = 'winners';
let histUsername = '';
let histSince = 0;

const HIST_COLS = {
    winners: ['Quando', 'Plataforma', 'Usuário', 'Peso', 'Chance%', 'Prêmio', 'Captcha', 'Entregue'],
    roleta:  ['Quando', 'Vencedor', 'Prêmio', 'Index'],
    audit:   ['Quando', 'Ator', 'Ação', 'Payload'],
};

function escapeHtml(s) {
    if (s === null || s === undefined) return '';
    return String(s).replace(/[&<>"']/g, c => ({
        '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'
    }[c]));
}

function histSinceTs() {
    if (!histSince) return 0;
    // date input dá 'YYYY-MM-DD' — converte pra timestamp do início do dia
    return Math.floor(new Date(histSince + 'T00:00:00').getTime() / 1000);
}

async function renderHistory() {
    $('hist-thead').innerHTML =
        '<tr>' + HIST_COLS[histSection].map(c => `<th>${c}</th>`).join('') + '</tr>';

    const url = new URL('/api/history', location.origin);
    url.searchParams.set('section', histSection);
    url.searchParams.set('limit', '200');
    if (histUsername) url.searchParams.set('username', histUsername);
    if (histSince) url.searchParams.set('since', String(histSinceTs()));

    $('hist-status').textContent = 'Carregando...';
    try {
        const r = await fetch(url);
        const data = await r.json();
        const rows = data.rows || [];
        const tbody = $('hist-tbody');
        if (!rows.length) {
            tbody.innerHTML = '<tr><td colspan="' + HIST_COLS[histSection].length +
                '" class="hint">Nenhum registro.</td></tr>';
        } else if (histSection === 'winners') {
            tbody.innerHTML = rows.map(w => {
                const ts = w.drawn_at ? new Date(w.drawn_at * 1000).toLocaleString() : '-';
                const cap = w.captcha_passed ? '✅' : (w.answered ? '❌' : '—');
                return `<tr>
                    <td>${escapeHtml(ts)}</td>
                    <td>${escapeHtml(w.platform)}</td>
                    <td><strong>${escapeHtml(w.username)}</strong></td>
                    <td>${(w.weight || 0).toFixed(1)}</td>
                    <td>${(w.chance_pct || 0).toFixed(1)}%</td>
                    <td>${escapeHtml(w.award || '-')}</td>
                    <td>${cap}</td>
                    <td>${w.delivered ? '✅' : '—'}</td>
                </tr>`;
            }).join('');
        } else if (histSection === 'roleta') {
            tbody.innerHTML = rows.map(h => {
                const ts = h.ts ? new Date(h.ts * 1000).toLocaleString() : '-';
                return `<tr>
                    <td>${escapeHtml(ts)}</td>
                    <td>${escapeHtml(h.winner || '-')}</td>
                    <td>${escapeHtml(h.prize || '-')}</td>
                    <td>${h.spin_index ?? '-'}</td>
                </tr>`;
            }).join('');
        } else if (histSection === 'audit') {
            tbody.innerHTML = rows.map(ev => {
                const payload = JSON.stringify(ev.payload || {});
                return `<tr>
                    <td>${escapeHtml(ev.ts_human || '-')}</td>
                    <td>${escapeHtml(ev.actor || '-')}</td>
                    <td><code>${escapeHtml(ev.action || '-')}</code></td>
                    <td><code>${escapeHtml(payload.length > 120 ? payload.slice(0, 120) + '…' : payload)}</code></td>
                </tr>`;
            }).join('');
        }
        $('hist-status').textContent = `${data.count} registro(s)`;
    } catch (e) {
        $('hist-status').textContent = '❌ ' + e;
    }
}

document.querySelectorAll('#hist-section-control .seg-btn').forEach(btn => {
    btn.addEventListener('click', () => {
        document.querySelectorAll('#hist-section-control .seg-btn').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        histSection = btn.dataset.section;
        renderHistory();
    });
});

$('btn-hist-filter').addEventListener('click', () => {
    histUsername = $('hist-username').value.trim();
    histSince = $('hist-since').value;
    renderHistory();
});

$('btn-hist-export').addEventListener('click', () => {
    const map = {winners: 'winners', roleta: 'roleta', audit: 'audit'};
    location.href = '/api/export/' + map[histSection] + '.csv';
});

function renderInlineParticipants() {
    if (!state) return;
    const search=$('inline-search').value.toLocaleLowerCase();
    const platform=$('inline-platform').value;
    const list=(state.participants || []).filter(p=>(!platform || p.platform===platform) && p.username.toLocaleLowerCase().includes(search));
    $('inline-participants').innerHTML=list.map(p=>`<tr class="${p.active===false?'inline-participant-inactive':''}"><td>${escapeHtml(p.username)}</td><td><span class="platform-badge ${p.platform==='kick'?'kick':'twitch'}">${escapeHtml(p.platform)}</span></td><td>${p.is_mod?'Mod':p.is_vip?'VIP':p.is_sub?'Sub':'Viewer'}</td><td>${weightLabel(p.weight)}x${p.active===false?'<small class="already-drawn">⛔ Desativado manualmente</small>':''}${p.is_winner?'<small class="already-drawn">Já sorteado · fora dos próximos</small>':''}</td></tr>`).join('') || '<tr><td colspan="4" class="hint">Nenhum participante encontrado.</td></tr>';
}
$('inline-search').addEventListener('input',renderInlineParticipants);
$('inline-platform').addEventListener('change',renderInlineParticipants);

const kickCallback = new URL('/api/oauth/kick/callback', location.origin);
if (kickCallback.hostname === '127.0.0.1') kickCallback.hostname = 'localhost';
$('kick-redirect-uri').value = kickCallback.href;

function refreshDraftChances() {
    const items = (state?.roleta?.items || []).map(_applyDraft);
    const active = items.filter(item => item.active);
    const total = active.reduce((sum,item) => sum + Math.max(0, _toFloat(item.weight) || 0), 0);
    for (const item of items) {
        const element = document.querySelector(`.roleta-item[data-id="${item.id}"] .roleta-pct strong`);
        if (element) element.textContent = `${(item.active ? (total > 0 ? Math.max(0, _toFloat(item.weight) || 0)/total*100 : 100/active.length) : 0).toFixed(1)}%`;
    }
}
function renderMarkedParticipants() {
    if (!state) return;
    const marked = state.antibot?.marked || [];
    const search = $('antibot-marked-search').value.trim().toLocaleLowerCase();
    const platform = $('antibot-marked-platform').value;
    const labels = {marked:'Aguardando sorteio',challenged:'Captcha em andamento',passed:'Captcha respondido',confirmed:'Confirmado pelo painel',failed:'Desafio não confirmado',expired:'Prazo esgotado',skipped:'Vencedor pulado'};
    const filtered = marked.filter(p => (!platform || p.platform === platform) && p.username.toLocaleLowerCase().includes(search));
    $('ab-marked-count').textContent = marked.length;
    $('antibot-marked-summary').textContent = `${filtered.length} de ${marked.length} marcados · ${state.antibot.total_decided || 0} inscrições no sorteio`;
    $('antibot-marked-tbody').innerHTML = filtered.map(p => `<tr><td><strong>${escapeHtml(p.username)}</strong><span class="ab-platform">${escapeHtml(p.platform.toUpperCase())}</span></td><td>${p.chance_at_entry}%</td><td><span class="ab-person-status ${p.status === 'challenged' ? 'active' : ''}">${escapeHtml(labels[p.status] || p.status)}</span></td></tr>`).join('') || '<tr><td colspan="3" class="hint ab-empty">Nenhuma pessoa marcada com estes filtros.</td></tr>';
}
$('antibot-marked-search').addEventListener('input', renderMarkedParticipants);
$('antibot-marked-platform').addEventListener('change', renderMarkedParticipants);
