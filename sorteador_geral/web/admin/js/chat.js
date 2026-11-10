(() => {
    const defaults = {scope:'own',selected:[],alwaysMentions:true,twitchOnlyMentions:false,kickOnlyMentions:false,twitchSound:false,kickSound:false,twitchSoundMode:'all',kickSoundMode:'all',mentionNames:'',volume:35};
    let prefs={...defaults};
    try { prefs={...defaults,...JSON.parse(localStorage.getItem('sorteador.chat.preferences') || '{}')}; } catch {}
    const seen=new Set();let initialized=false;let audio=null;let lastBeep=0;
    const knownChannels=new Set();const feedSignatures={};
    const channelProfiles=new Map();let metadataOwner='',metadataAt=0,metadataBusy=false;
    const lower=value=>String(value || '').trim().replace(/^[@#]+/,'').toLowerCase();
    prefs.selected=Array.isArray(prefs.selected)?prefs.selected.map(value=>String(value).trim().replace(/^[@#]+/,'').toLowerCase()).filter(Boolean):[];
    if(!['own','all','selected'].includes(prefs.scope))prefs.scope='own';
    const save=()=>{try{localStorage.setItem('sorteador.chat.preferences',JSON.stringify(prefs));}catch{}};
    const own=()=>lower(state?.connections?.twitch?.channel || '');
    const nicknames=()=>new Set([own(),lower(state?.bots?.twitch_login),lower(state?.kick?.oauth_username),...String(prefs.mentionNames).split(/[\s,;]+/).map(lower)].filter(Boolean));
    function isMention(message) {
        const names=nicknames();
        if ((message.mentions || []).some(name=>names.has(lower(name)))) return true;
        const text=String(message.text || '').toLowerCase();
        return [...names].some(name=>new RegExp(`(^|[^a-z0-9_])@${name.replace(/[.*+?^${}()|[\]\\]/g,'\\$&')}(?![a-z0-9_])`,'i').test(text));
    }
    function isVisible(message) {
        const mention=isMention(message);
        if (prefs[message.platform+'OnlyMentions'] && !mention) return false;
        if (message.platform !== 'twitch') return true;
        const source=lower(message.source_channel || message.channel);
        const ownMessage=source === (own() || lower(message.channel));
        const channelAllowed=prefs.scope==='all' || (prefs.scope==='selected' ? prefs.selected.includes(source) : ownMessage);
        return channelAllowed || (prefs.alwaysMentions && mention);
    }
    async function unlockAudio() {
        const Audio=window.AudioContext || window.webkitAudioContext;
        if (!Audio) { $('chat-audio-status').textContent='Este navegador não oferece avisos sonoros.';return false; }
        audio ||= new Audio();
        if (audio.state==='suspended') await audio.resume();
        $('chat-audio-status').textContent=audio.state==='running'?'Áudio liberado neste navegador.':'Clique novamente para liberar o áudio.';
        return audio.state==='running';
    }
    function beep(force=false) {
        if (!audio || audio.state!=='running' || (!force && performance.now()-lastBeep<350)) return;
        lastBeep=performance.now();
        const oscillator=audio.createOscillator(), gain=audio.createGain(),now=audio.currentTime;
        oscillator.type='sine';oscillator.frequency.value=880;
        const volume=Math.max(0,Math.min(100,Number(prefs.volume)||0))/100*.12;
        gain.gain.setValueAtTime(0,now);gain.gain.linearRampToValueAtTime(volume,now+.012);gain.gain.linearRampToValueAtTime(0,now+.14);
        oscillator.connect(gain);gain.connect(audio.destination);oscillator.start(now);oscillator.stop(now+.16);
        oscillator.onended=()=>{oscillator.disconnect();gain.disconnect();};
    }
    function receive(messages) {
        for(const message of messages) {
            const id=message.platform+':'+message.id;
            if(seen.has(id)) continue;
            seen.add(id);
            if (message.platform==='twitch' && message.source_channel) knownChannels.add(lower(message.source_channel));
            if(initialized && prefs[message.platform+'Sound'] && isVisible(message)) {
                const ownUser=lower(message.platform==='twitch'?state?.bots?.twitch_login:state?.kick?.oauth_username);
                if(lower(message.username)!==ownUser && (prefs[message.platform+'SoundMode']==='all' || isMention(message))) beep();
            }
        }
        initialized=true;
        if(seen.size>900) { const values=[...seen];seen.clear();values.slice(-600).forEach(id=>seen.add(id)); }
    }
    function renderChannels() {
        if(own()) knownChannels.add(own());
        for(const name of prefs.selected) knownChannels.add(name);
        const channels=[...knownChannels].filter(Boolean).sort();
        $('twitch-channels-button').textContent=`Canais (${channels.length})`;
        const container=$('twitch-channel-options');
        const signature=JSON.stringify([channels,prefs.selected,prefs.scope,[...channelProfiles]]);
        if(container.dataset.signature===signature) return;
        container.dataset.signature=signature;container.replaceChildren();
        for(const channel of channels) {
            const label=document.createElement('label'),input=document.createElement('input');
            input.type='checkbox';input.value=channel;input.checked=prefs.scope==='all' || (prefs.scope==='own'?channel===own():prefs.selected.includes(channel));
            input.addEventListener('change',()=>{
                if(prefs.scope!=='selected')prefs.selected=[...knownChannels].filter(name=>prefs.scope==='all' || name===own());
                prefs.selected=input.checked?[...new Set([...prefs.selected,channel])]:prefs.selected.filter(name=>name!==channel);
                prefs.scope='selected';$('twitch-chat-scope').value='selected';save();renderLive();
            });
            const profile=channelProfiles.get(channel);
            label.append(input,document.createTextNode((profile?.display_name || channel)+(channel===own()?' · meu canal':'')));container.append(label);
        }
        if(!channels.length) container.textContent='Os canais aparecerão quando receberem mensagens, ou você pode adicionar um login.';
    }
    async function refreshChannels() {
        const active=document.querySelector('.tab[data-tab="chats"]')?.classList.contains('active');
        if(!active || document.hidden || !own() || state?.connections?.simulation_mode || metadataBusy || Date.now()-metadataAt<15000)return;
        const owner=own();metadataBusy=true;metadataAt=Date.now();
        try {
            const response=await fetch('/api/chat/twitch/channels',{cache:'no-store'});
            if(!response.ok)throw Error('metadata');
            const data=await response.json();if(owner!==own())return;
            for(const profile of [data.channel,...(data.participants || [])]) {
                const login=lower(profile?.login);if(!login)continue;
                knownChannels.add(login);channelProfiles.set(login,profile);
            }
            $('twitch-channels-status').textContent=data.warning || (data.session?'Colaboração detectada automaticamente. Escolha quais canais deseja exibir.':'Sem colaboração ativa. Os canais recebidos continuam disponíveis no histórico.');
            renderChannels();
        } catch (_) {$('twitch-channels-status').textContent='Metadados indisponíveis. Os filtros continuam usando os canais das mensagens recebidas.';}
        finally {metadataBusy=false;}
    }

    function renderFeed(platform) {
        const feed=$(platform+'-chat-feed');
        const all=(state?.chat_messages || []).filter(message=>message.platform===platform);
        const messages=all.filter(isVisible);
        const signature=messages.map(message=>message.id).join('|')+'#'+prefs.mentionNames+'#'+own();
        if(feedSignatures[platform]===signature) return;
        feedSignatures[platform]=signature;
        const atBottom=feed.scrollHeight-feed.scrollTop-feed.clientHeight<70;
        const scroll=feed.scrollTop;
        feed.innerHTML=messages.map(message=>{
            const mention=isMention(message),source=message.source_channel || message.channel || '';
            const time=new Date(message.ts*1000).toLocaleTimeString('pt-BR',{hour:'2-digit',minute:'2-digit',hour12:false});
            const color=/^#[a-f0-9]{6}$/i.test(message.color || '')?message.color:(platform==='twitch'?'#c49aff':'#71e36c');
            return `<div class="live-message ${mention?'mention':''}" data-message-id="${escapeHtml(message.id)}"><div class="message-origin">Canal: ${escapeHtml(source || 'conectado')}${message.shared?' · colab':''}</div><div class="message-line"><time>${time}</time> <strong style="color:${color}">${escapeHtml(message.display_name || message.username)}:</strong> <span>${escapeHtml(message.text)}</span></div></div>`;
        }).join('') || `<p class="live-chat-empty">${all.length?'Nenhuma mensagem corresponde aos filtros.':'Aguardando mensagens. Abra a aba Conexões para conectar a conta.'}</p>`;
        if(atBottom) feed.scrollTop=feed.scrollHeight;else feed.scrollTop=scroll;
    }
    function renderLive() {
        if(!state) return;
        if(metadataOwner!==own()) {metadataOwner=own();metadataAt=0;knownChannels.clear();channelProfiles.clear();}
        receive(state.chat_messages || []);renderChannels();refreshChannels();
        for(const platform of ['twitch','kick']) {
            const channel=platform==='twitch'?state.connections?.twitch?.channel:(state.kick?.receive_channel || state.kick?.channel_slug);
            $(platform+'-live-channel').textContent=channel?'@'+channel:'Nenhum canal conectado';
            $(platform+'-chat-target').textContent=channel?`Envio para @${channel}, mesmo com filtros da colab.`:'Envio para o canal conectado.';
            const canSend=platform==='twitch'?state.connections?.twitch?.connected:state.kick?.send_ready;
            $(platform+'-chat-send').disabled=!canSend || !!state.connections?.simulation_mode;
            renderFeed(platform);
        }
        // Recupera somente campos públicos; senhas e tokens nunca voltam ao formulário.
        for(const [id,value] of [['twitch-client-id',state.bots?.twitch_client_id],['twitch-channel',state.connections?.twitch?.channel],['kick-client-id',state.kick?.client_id],['kick-redirect-uri',state.kick?.redirect_uri]]) {
            const element=$(id);if(value && !element.value && document.activeElement!==element) element.value=value;
        }
    }
    window.renderLiveChats=renderLive;
    window.acceptChatMessage=message=>{
        if(!state) return;
        const messages=state.chat_messages ||= [];
        if(!messages.some(item=>item.platform===message.platform && item.id===message.id)) messages.push(message);
        state.chat_messages=messages.slice(-300);renderLive();
    };
    function bind(id,key,type='value') {
        const element=$(id);element[type]=prefs[key];
        element.addEventListener('change',()=>{
            prefs[key]=element[type];save();renderLive();
            if(key.endsWith('Sound') && prefs[key]) unlockAudio().catch(()=>{});
        });
    }
    bind('twitch-chat-scope','scope');bind('twitch-always-mentions','alwaysMentions','checked');
    for(const platform of ['twitch','kick']) {
        bind(platform+'-only-mentions',platform+'OnlyMentions','checked');
        bind(platform+'-chat-sound',platform+'Sound','checked');bind(platform+'-sound-mode',platform+'SoundMode');
        $(platform+'-sound-test').addEventListener('click',async()=>{if(await unlockAudio()) beep(true);});
        async function send() {
            const input=$(platform+'-chat-message'),button=$(platform+'-chat-send'),feedback=$(platform+'-chat-feedback');
            const text=input.value.trim();if(!text) return;
            button.disabled=true;feedback.textContent='Enviando...';
            try {
                const response=await fetch('/api/chat/send',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({platform,text})});
                const data=await response.json();if(!response.ok) throw Error(typeof data.detail==='string'?data.detail:'Não foi possível enviar.');
                input.value='';feedback.textContent='Mensagem enviada. Ela aparecerá quando recebida pelo chat.';
            } catch(error) { feedback.textContent=error.message; }
            finally { renderLive(); }
        }
        $(platform+'-chat-send').addEventListener('click',send);
        $(platform+'-chat-message').addEventListener('keydown',event=>{if(event.key==='Enter' && !$(platform+'-chat-send').disabled){event.preventDefault();send();}});
    }
    bind('chat-mention-names','mentionNames');bind('chat-sound-volume','volume');
    $('twitch-channels-button').onclick=()=>{$('twitch-channel-picker').hidden=!$('twitch-channel-picker').hidden;};
    $('twitch-add-channel-button').onclick=()=>{
        const name=lower($('twitch-add-channel').value);
        if(!/^[a-z0-9_]{1,25}$/.test(name)) {$('twitch-chat-feedback').textContent='Informe o login do canal da colab.';return;}
        knownChannels.add(name);prefs.selected=[...new Set([...prefs.selected,name])];prefs.scope='selected';$('twitch-chat-scope').value='selected';$('twitch-add-channel').value='';save();renderLive();
    };
    $('chat-reset-filters').onclick=()=>{
        prefs={...prefs,scope:'own',selected:[],alwaysMentions:true,twitchOnlyMentions:false,kickOnlyMentions:false};
        $('twitch-chat-scope').value='own';$('twitch-always-mentions').checked=true;
        $('twitch-only-mentions').checked=false;$('kick-only-mentions').checked=false;save();renderLive();
    };
    document.querySelector('.tab[data-tab="chats"]').addEventListener('click',()=>{renderLive();if(prefs.twitchSound || prefs.kickSound)unlockAudio().catch(()=>{});});
    // Preferências salvas de som precisam de um gesto para liberar o áudio no navegador.
    document.addEventListener('pointerdown',()=>{if(prefs.twitchSound || prefs.kickSound)unlockAudio().catch(()=>{});},{once:true});
    setInterval(refreshChannels,15000);
    renderLive();
})();
