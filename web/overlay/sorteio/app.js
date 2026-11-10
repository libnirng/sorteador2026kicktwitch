// ===========================================================================
// Overlay MEGAMU - Cliente
// Conecta no WebSocket, renderiza participantes/prêmios/vencedor
// ===========================================================================
const $ = (id) => document.getElementById(id);
const AVATAR_COLORS = ['color-pink', 'color-cyan', 'color-green', 'color-purple'];

// Estado local
let lastState = null;
let lastParticipants = new Map();   // para diff
let timerInterval = null;
const visualSignatures = {};
if (typeof DrawAnimations !== 'undefined') DrawAnimations.mount($('draw-animation-art'));
function isDrawPending(g) {
    return !!(g?.is_running && g.current_winner && Number(g.draw_reveal_until) > Date.now()/1000);
}
function unchanged(section, value) {
    const signature=JSON.stringify(value);
    if(visualSignatures[section]===signature)return true;
    visualSignatures[section]=signature;return false;
}

// ===========================================================================
// UTILITÁRIOS
// ===========================================================================
function initials(name) {
    if (!name) return '?';
    const s = name.replace(/[^a-zA-Z0-9]/g, '');
    return (s[0] || '?').toUpperCase();
}

function colorClass(name) {
    if (!name) return '';
    const h = [...name].reduce((a, c) => a + c.charCodeAt(0), 0);
    return AVATAR_COLORS[h % AVATAR_COLORS.length];
}

function escapeHtml(s) {
    return String(s || '').replace(/[&<>"']/g, c => ({
        '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
    }[c]));
}

function renderAvatar(element, url, name) {
    element.replaceChildren();
    if (!url || !/^https?:\/\//i.test(url)) {
        element.textContent = initials(name);
        return;
    }
    const img = document.createElement('img');
    img.alt = `Foto de ${name}`;
    img.src = url;
    img.onerror = () => { element.textContent = initials(name); };
    element.append(img);
}

// ===========================================================================
// RENDERIZAÇÃO
// ===========================================================================
function renderBanner(state) {
    const g = state.giveaway;
    const awaitingNick=!!g.winner_chat?.awaiting_nick;
    const claimSuccess=g.winner_chat?.nick_verification?.status==='success';
    const pending=isDrawPending(g);
    if(unchanged('banner',[!!g.current_winner,!!g.captcha,awaitingNick,claimSuccess,g.is_paused,g.is_running,pending]))return;
    const statusText = $('status-text');
    const statusRow = $('status-row');
    statusRow.className = 'banner-sub';

    if (claimSuccess) {
        statusRow.classList.add('status-open');
        statusText.textContent = 'PERSONAGEM VALIDADO';
    } else if (awaitingNick) {
        statusRow.classList.add('status-drawing');
        statusText.textContent = 'AGUARDANDO PERSONAGEM';
    } else if (g.current_winner && g.captcha) {
        statusRow.classList.add('status-drawing');
        statusText.textContent = 'VERIFICAÇÃO DO VENCEDOR';
    } else if (g.current_winner) {
        statusRow.classList.add('status-drawing');
        statusText.textContent = pending ? 'SORTEANDO...' : 'VENCEDOR SORTEADO';
    } else if (g.is_paused) {
        statusRow.classList.add('status-paused');
        statusText.textContent = 'COLETA PAUSADA';
    } else if (!g.is_running) {
        statusRow.classList.add('status-closed');
        statusText.textContent = 'AGUARDANDO';
    } else {
        statusRow.classList.add('status-open');
        statusText.textContent = 'COLETA ABERTA';
    }
}

function renderParticipants(state) {
    // lista de participantes (no state.state.participants, virá na etapa 4)
    // por enquanto usa state.participants se vier, ou array vazio
    const list = state.participants || [];
    const pending=isDrawPending(state.giveaway);
    const secret=state.giveaway?.current_winner;
    $('count').textContent = list.length || (state.giveaway.count || 0);

    const values=list.map(p=>[p.platform,p.username,p.is_sub,p.is_vip,p.is_mod,
        p.is_winner && !(pending && secret?.platform===p.platform && secret?.username?.toLowerCase()===p.username.toLowerCase()),
        p.active,p.avatar_url || p.avatar]);
    if(unchanged('participants',values))return;
    const grid=$('grid');
    if(!list.length) {
        grid.innerHTML='<div class="prize-empty" style="grid-column:1/-1">Nenhum participante ainda</div>';
        lastParticipants.clear();return;
    }
    if(!lastParticipants.size)grid.replaceChildren();
    const activeKeys=new Set();
    list.forEach((p,index)=>{
        const key=p.platform+':'+p.username.toLowerCase();activeKeys.add(key);
        const signature=JSON.stringify(values[index]);
        let record=lastParticipants.get(key);
        if(!record){record={element:document.createElement('div'),signature:null};lastParticipants.set(key,record);}
        const card=record.element;
        if(record.signature!==signature) {
            const shownAsWinner=values[index][5];
            record.signature=signature;card.className='p-card'+(shownAsWinner?' already-drawn':'')+(p.active===false?' participant-inactive':'');
            const tags=[];
            if(p.is_sub)tags.push('<span class="p-tag sub">SUB</span>');
            if(p.is_vip)tags.push('<span class="p-tag vip">VIP</span>');
            if(p.is_mod)tags.push('<span class="p-tag mod">MOD</span>');
            if(shownAsWinner)tags.push('<span class="p-tag drawn">SORTEADO</span>');
            if(p.active===false)tags.push('<span class="p-tag inactive">INATIVO</span>');
            tags.push(`<span class="p-tag ${p.platform==='kick'?'kick':'twitch'}">${escapeHtml(p.platform.toUpperCase())}</span>`);
            card.innerHTML=`<div class="p-avatar ${colorClass(p.username)}"></div><div class="p-name" title="${escapeHtml(p.username)}">${escapeHtml(p.username)}</div><div class="p-tags">${tags.join('')}</div>`;
            renderAvatar(card.querySelector('.p-avatar'),p.avatar_url || p.avatar,p.username);
        }
        if(grid.children[index]!==card)grid.insertBefore(card,grid.children[index] || null);
    });
    for(const [key,record] of lastParticipants)if(!activeKeys.has(key)){record.element.remove();lastParticipants.delete(key);}

}

function renderPrizes(state) {
    // No OBS, todas as origens exibem apenas o nome do prêmio.
    const items = state.giveaway?.prizes || [];
    if(unchanged('prizes',items.map(p=>[p.name,p.icon])))return;
    const cont = $('prizes');
    if (!items.length) {
        cont.innerHTML = '<div class="prize-empty">Nenhum prêmio cadastrado</div>';
        return;
    }
    cont.innerHTML = items.map(p => `
        <div class="prize-item">
            <div class="prize-icon">${escapeHtml(p.icon || '🎁')}</div>
            <div class="prize-name">${escapeHtml(p.name)}</div>
        </div>`).join('');
}

function renderWinner(state) {
    const g = state.giveaway || {};
    const pending=isDrawPending(g);
    const awaitingNick = !!(g.winner_chat?.awaiting_nick && !g.current_winner);
    const nickFeedback=g.winner_chat?.nick_verification;
    const claimSuccess=!!(!g.current_winner && nickFeedback?.status==='success');
    const claimActive=awaitingNick || claimSuccess;
    const animationOption=state.appearance?.winner_animation || 'classic';
    // A fase de !nick não tem mais vencedor "ativo" no sorteador, mas deve
    // manter o MESMO destaque visual principal até a consulta do personagem.
    const w = g.current_winner || (claimActive ? g.winner_chat.winner : null);
    const captchaActive = !!g.captcha;
    const participantAvatar=(state.participants || []).find(p=>p.platform===w?.platform && p.username.toLowerCase()===w?.username.toLowerCase())?.avatar_url;
    if(unchanged('winner',[w,g.winner_deadline,participantAvatar,captchaActive,awaitingNick,claimSuccess,pending,
        nickFeedback,g.winner_chat?.captcha_confirmed,g.winner_chat?.nick_command,animationOption]))return;
    const stage = $('winner-stage');
    const nickCard=$('winner-nick-result');
    if (!w || captchaActive || pending) {
        stage.classList.remove('active');
        nickCard.hidden=true;
        if (timerInterval) { clearInterval(timerInterval); timerInterval = null; }
        return;
    }
    stage.classList.add('active');
    stage.classList.toggle('awaiting-nick', claimActive);
    const drawKey=`${w.platform}:${w.username}:${w.drawn_at}`;
    if(claimActive) {
        // O vencedor já foi revelado: manter a tela principal estável.
        stage.classList.remove('winner-animate');
    } else if(stage.dataset.drawKey!==drawKey || stage.dataset.animationOption!==animationOption) {
        const variants=['classic','spotlight','rise','flip','burst'];
        stage.dataset.animation=animationOption==='random'
            ? variants[Math.floor(Math.random()*variants.length)]
            : variants.includes(animationOption)?animationOption:'classic';
        stage.dataset.drawKey=drawKey;
        stage.dataset.animationOption=animationOption;
        stage.classList.remove('winner-animate');
        void stage.offsetWidth;
        stage.classList.add('winner-animate');
    }
    $('winner-label').textContent = claimSuccess ? '🏆 PRÊMIO CONFIRMADO 🏆' : awaitingNick ? '🏆 VENCEDOR CONFIRMADO 🏆' : '🏆 VENCEDOR 🏆';
    $('w-avatar').className = 'winner-avatar ' + colorClass(w.username);
    const participant = (state.participants || []).find(p => p.platform === w.platform && p.username.toLowerCase() === w.username.toLowerCase());
    renderAvatar($('w-avatar'), w.avatar_url || participant?.avatar_url, w.username);
    $('w-name').textContent = w.username;
    $('w-platform').textContent = (w.platform || '').toUpperCase();
    $('w-chance').textContent = `${Number(w.chance_pct || 0).toFixed(2)}% de chance`;

    const progress=$('winner-progress');
    progress.hidden=!claimActive;
    if(claimSuccess) {
        progress.textContent='✅ PERSONAGEM VERIFICADO · PRÊMIO CONFIRMADO';
    } else if(awaitingNick) {
        const command=g.winner_chat.nick_command || '!nick';
        progress.textContent = `${g.winner_chat.captcha_confirmed?'✅ CAPTCHA CORRETO':'✅ RESPOSTA CONFIRMADA'} · ENVIE ${command} NomeDoPersonagem OU !NomeDoPersonagem`;
    }
    nickCard.hidden=!claimActive || !nickFeedback;
    if(!nickCard.hidden) {
        const status=nickFeedback.status||'checking';
        nickCard.dataset.status=status;
        const titles={checking:'🔎 CONSULTANDO MEGAMU...',waiting:'⏳ AGUARDE UM INSTANTE',
            error:'❌ PERSONAGEM NÃO CONFIRMADO',success:'✅ PERSONAGEM ENCONTRADO'};
        $('winner-nick-result-title').textContent=titles[status]||titles.checking;
        $('winner-nick-result-name').textContent=nickFeedback.nick||'';
        $('winner-nick-result-text').textContent=nickFeedback.result||'';
    }

    // Timer
    if (timerInterval) {clearInterval(timerInterval);timerInterval=null;}
    const deadline = g.winner_deadline || 0;
    function tick() {
        const remaining = Math.max(0, Math.round(deadline - Date.now() / 1000));
        const el = $('w-timer');
        el.textContent = remaining;
        el.classList.toggle('urgent', remaining <= 10 && remaining > 0);
        el.hidden = !deadline;
    }
    tick();
    if(deadline)timerInterval = setInterval(tick, 500);
}

function renderWinnerChat(state) {
    const data=state.giveaway?.winner_chat;
    const card=$('winner-chat-card');
    // Um só nome/avatar/plataforma: ficam no destaque principal. Este bloco
    // apresenta apenas a última mensagem do vencedor, sem repetir identidade.
    card.hidden=!data || !state.giveaway.is_running || isDrawPending(state.giveaway) ||
        (!state.giveaway.current_winner && !data.awaiting_nick) || !!state.giveaway.captcha;
    if(card.hidden) {visualSignatures.winnerChat=null;return;}
    const messages=data.messages || [];
    const last=messages[messages.length-1];
    if(unchanged('winnerChat',[data.drawn_at,last?.id,last?.text]))return;
    const feed=$('winner-chat-messages');
    feed.replaceChildren();
    if(last) {
        const line=document.createElement('div');line.className='winner-chat-line';
        line.textContent=last.text;feed.append(line);
    } else {
        const empty=document.createElement('p');empty.className='winner-chat-wait';
        empty.textContent='Aguardando a primeira mensagem…';feed.append(empty);
    }
}

// Alimenta os efeitos com participantes elegíveis. O vencedor recém-escolhido
// pode constar com chance zero no snapshot: ele continua na roleta até revelar.
function drawParticipantNames(state) {
    const g=state.giveaway||{};
    const winner=g.current_winner;
    const list=(state.participants||[]).filter(p=>p?.username);
    const sameWinner=p=>winner && p.platform===winner.platform &&
        p.username.toLowerCase()===winner.username.toLowerCase();
    const active=list.filter(p=>p.active!==false || sameWinner(p));
    const hasChances=active.some(p=>p.chance_pct!==undefined&&p.chance_pct!==null);
    const eligible=hasChances?active.filter(p=>Number(p.chance_pct)>0||sameWinner(p)):active;
    const pool=eligible.length?eligible:active;
    const names=new Map();
    pool.forEach(p=>{const key=p.username.toLowerCase();names.set(key,(names.get(key)||0)+1);});
    const result=pool.map(p=>names.get(p.username.toLowerCase())>1
        ? `${p.username} (${p.platform==='kick'?'KICK':'TWITCH'})`:p.username);
    if(winner&&!pool.some(sameWinner))result.push(winner.username);
    return result;
}

// Suspense anterior à revelação: compartilha aparência com a prévia do painel.
function renderDrawSuspense(state) {
    const g=state.giveaway||{};
    const stage=$('draw-suspense-stage');
    if(!stage)return;
    const pending=isDrawPending(g);
    document.body.classList.toggle('drawing-solo',pending);
    stage.hidden=!pending;
    if(!pending)return;
    const options=typeof DrawAnimations !== 'undefined' ? DrawAnimations.styles : ['roulette'];
    // O backend resolve "random" uma vez por vencedor. Todos os OBS exibem
    // exatamente o mesmo efeito, mesmo após reconectar o WebSocket.
    const requested=g.draw_animation_active||state.appearance?.draw_animation||'roulette';
    const selected=options.includes(requested)?requested:'roulette';
    const styleLabels={roulette:'ROULETA GIRATÓRIA',slots:'CAÇA-NÍQUEL',countdown:'CONTAGEM REGRESSIVA',
        cards:'CARTAS EMBARALHADAS',dice:'DADOS ROLANDO',radar:'RADAR',chest:'BAÚ MISTERIOSO',
        particles:'CHUVA DE ESTRELAS',portal:'PORTAL MÁGICO',spotlights:'HOLOFOTES'};
    const key=`${g.current_winner.platform}:${g.current_winner.username}:${g.current_winner.drawn_at}`;
    if(stage.dataset.drawKey!==key || stage.dataset.animation!==selected) {
        stage.dataset.drawKey=key;
        stage.dataset.animation=selected;
    }
    $('draw-suspense-style').textContent=styleLabels[selected]||'SORTEANDO';
    const total=Math.max(.1,Number(state.appearance?.draw_animation_seconds)||4);
    const remaining=Math.max(0,Number(g.draw_reveal_until)-Date.now()/1000);
    $('draw-suspense-subtitle').textContent=`Revelação em ${Math.ceil(remaining)}s`;
    $('draw-suspense-progress-bar').style.width=`${Math.max(0,Math.min(100,(1-remaining/total)*100))}%`;
    if(typeof DrawAnimations !== 'undefined') {
        DrawAnimations.countdown($('draw-animation-art'),remaining,total);
        DrawAnimations.renderNames($('draw-animation-art'),drawParticipantNames(state),total-remaining,
            total,g.current_winner.username);
    }
}

// CAPTCHA e sorteio usam o mesmo overlay do OBS. O servidor continua sendo a
// fonte única de verdade: pergunta, vencedor, resultado e prazo vêm de /api/state.
let lastCaptchaWinner = null;
let captchaResult = null;

function renderCaptcha(state) {
    const g = state.giveaway || {};
    const c = g.captcha;
    const winner = g.current_winner;
    const active = !!(g.is_running && c && winner);
    const layer = $('captcha-layer');
    const card = $('captcha-card');

    if (active) {
        lastCaptchaWinner = {username: winner.username, platform: winner.platform};
        captchaResult = null;
        layer.hidden = false;
        layer.setAttribute('aria-hidden', 'false');
        card.dataset.result = 'challenge';
        $('captcha-seal').textContent = '🛡️';
        $('captcha-eyebrow').textContent = 'VERIFICAÇÃO DO VENCEDOR';
        $('captcha-title').textContent = 'CONFIRME SUA VITÓRIA';
        $('captcha-username').textContent = winner.username;
        $('captcha-platform').textContent = winner.platform || '';
        $('captcha-question-wrap').hidden = false;
        $('captcha-countdown-wrap').hidden = !c.deadline;
        $('captcha-question').textContent = c.question || 'Aguardando desafio…';

        const tries=Number(c.attempts)||0;
        const limit=Number(c.max_attempts)||0;
        $('captcha-feedback').classList.toggle('wrong',tries>0);
        $('captcha-feedback').textContent=tries
            ? `❌ Resposta incorreta · tentativa ${tries}/${limit||'∞'}. ${limit?`Restam ${Math.max(0,limit-tries)} tentativa(s).`:'Tentativas ilimitadas.'} Tente novamente!`
            : `Presença confirmada! Digite a resposta no chat. ${limit?`Você tem ${limit} tentativa(s).`:'Tentativas ilimitadas.'}`;

        const deadline = Number(c.deadline || g.winner_deadline || 0);
        const seconds = Math.max(0, Math.ceil(deadline - Date.now() / 1000));
        $('captcha-countdown').textContent =
            `${String(Math.floor(seconds / 60)).padStart(2, '0')}:${String(seconds % 60).padStart(2, '0')}`;
        $('captcha-countdown-wrap').classList.toggle('urgent', seconds <= 10);
        return;
    }

    // Uma resposta errada encerra a verificação; a pessoa não precisa esperar
    // o relógio esgotar. Exibimos o código correto até o operador decidir.
    const feedback = g.captcha_feedback;
    if (g.is_running && winner && winner.captcha_failed && feedback?.status === 'wrong') {
        lastCaptchaWinner = null;
        captchaResult = null;
        layer.hidden = false;
        layer.setAttribute('aria-hidden', 'false');
        card.dataset.result = 'wrong';
        $('captcha-seal').textContent = '❌';
        $('captcha-eyebrow').textContent = 'VERIFICAÇÃO FINALIZADA';
        $('captcha-title').textContent = 'RESPOSTA INCORRETA';
        $('captcha-username').textContent = winner.username;
        $('captcha-platform').textContent = winner.platform || '';
        $('captcha-question-wrap').hidden = false;
        $('captcha-question').textContent = `A resposta correta era: ${feedback.expected || 'consulte o organizador'}`;
        $('captcha-countdown-wrap').hidden = true;
        $('captcha-feedback').classList.add('wrong');
        $('captcha-feedback').textContent = 'Limite de tentativas atingido. Aguarde a decisão do organizador.';
        return;
    }

    // CAPTCHA acertado: a confirmação já está no painel principal do
    // vencedor. Não trocar para uma tela isolada de "vitória confirmada".
    if (g.is_running && g.winner_chat &&
        (g.winner_chat.awaiting_nick || g.winner_chat.nick_verification?.status==='success') &&
        feedback?.status === 'correct') {
        lastCaptchaWinner = null;
        captchaResult = null;
        layer.hidden = true;
        layer.setAttribute('aria-hidden', 'true');
        return;
    }

    // Exibe brevemente o resultado quando o challenge desaparece, sem exigir
    // que o OBS troque de cena ou controle a visibilidade de duas páginas.
    if (lastCaptchaWinner) {
        const feedback = g.captcha_feedback;
        if (feedback && feedback.username === lastCaptchaWinner.username &&
            feedback.platform === lastCaptchaWinner.platform &&
            (feedback.status === 'correct' || feedback.status === 'expired')) {
            captchaResult = {
                status: feedback.status,
                username: lastCaptchaWinner.username,
                platform: lastCaptchaWinner.platform,
                until: Date.now() + 2400,
            };
        }
        lastCaptchaWinner = null;
    }

    if (g.is_running && captchaResult && Date.now() < captchaResult.until && !winner) {
        const correct = captchaResult.status === 'correct';
        layer.hidden = false;
        layer.setAttribute('aria-hidden', 'false');
        card.dataset.result = captchaResult.status;
        $('captcha-seal').textContent = correct ? '✅' : '⏳';
        $('captcha-eyebrow').textContent = 'VERIFICAÇÃO FINALIZADA';
        $('captcha-title').textContent = correct ? 'VITÓRIA CONFIRMADA!' : 'TEMPO ESGOTADO';
        $('captcha-username').textContent = captchaResult.username;
        $('captcha-platform').textContent = captchaResult.platform;
        $('captcha-question-wrap').hidden = true;
        $('captcha-countdown-wrap').hidden = true;
        $('captcha-feedback').classList.remove('wrong');
        $('captcha-feedback').textContent = correct
            ? 'Resposta correta! Voltando ao sorteador…'
            : 'O prazo terminou. Retornando ao sorteador…';
        return;
    }

    captchaResult = null;
    layer.hidden = true;
    layer.setAttribute('aria-hidden', 'true');
}

// ===========================================================================
// MODO DEMO (gera participantes falsos pra testar o visual)
// ===========================================================================
function buildDemoState() {
    const names = [
        'LAVIE90', 'LEGEND7TV', 'KYRESTONER', 'MAMASHENI119', 'CBBTO',
        'DIAZFERNEY', 'SANTARONIRJ', 'CHIEN01021999', 'IMURIHIKI',
        'T3NT4S0RT3', 'BLAMINGKYIN', 'PLAYER123', 'GAMER_PRO', 'NIKOTIN',
        'FURIOUS_1', 'CHIBIKKO', 'DEUS_VULT', 'MAGO_SUPREMO', 'DARK_KNIGHT',
        'STAR_LIGHT', 'FIRE_BIRD', 'IRON_FIST', 'STORM_RIDER', 'GHOST_77',
        'SHADOW_99', 'BLADE_RUNNER', 'PHOENIX_X', 'WOLF_PACK', 'NEON_PUNK',
    ];
    const list = names.map(n => ({
        platform: Math.random() > 0.5 ? 'twitch' : 'kick',
        username: n,
        is_sub: Math.random() > 0.7,
        is_vip: Math.random() > 0.85,
        is_mod: false,
        weight: 1.0,
        avatar: '',
    }));
    const prizes = [
        { name: '5x Talisma of C. Assembly', icon: '🎁' },
        { name: 'Seed Level 1', icon: '🎁' },
        { name: '500 Ruuds', icon: '🎁' },
        { name: '700 Ruuds', icon: '🎁' },
        { name: '1000 Ruuds', icon: '🎁' },
        { name: 'Steel of Heaven', icon: '🎁' },
        { name: '10000 MPoints', icon: '🎁' },
    ];
    return {
        server: { version: '0.1.0', simulation_mode: true },
        giveaway: {
            is_running: true, is_paused: false, keyword: '!sorteio',
            timer: 60, count: list.length, status: 'Aberto',
            current_winner: null, winner_deadline: 0, captcha: null,
            entry_open_twitch: true, entry_open_kick: true,
        },
        participants: list,
        roleta: {
            items: prizes.map((p, i) => ({ id: i + 1, ...p, weight: 1, active: true })),
        },
    };
}

// ===========================================================================
// WEBSOCKET
// ===========================================================================
let useDemo = false;
let demoState = null;
let lastSocketUpdate = 0;
const standalonePreview=typeof URLSearchParams!=='undefined' &&
    new URLSearchParams(location.search||'').get('preview')==='1';
let previewRevelationTimer=null;
let previewLastDrawStyle='';

function applyState(state) {
    if (!state) return;
    const a = state.appearance || {};
    document.documentElement.style.setProperty('--gold', a.primary_color || '#79e8a4');
    document.documentElement.style.setProperty('--gold-bright', a.accent_color || '#c060ff');
    $('w-name').style.fontSize = `${a.winner_font_size || 48}px`;
    $('w-name').style.fontFamily = a.overlay_font || 'Georgia';
    document.body.style.visibility = state.giveaway.is_running ? 'visible' : 'hidden';
    // Durante o suspense, nenhuma outra parte da cena aparece: só a animação
    // fica centralizada, em tela cheia, até a revelação do vencedor.
    document.body.classList.toggle('drawing-solo',isDrawPending(state.giveaway));
    lastState = state;
    renderBanner(state);
    renderParticipants(state);
    renderPrizes(state);
    renderDrawSuspense(state);
    renderWinner(state);
    renderWinnerChat(state);
    renderCaptcha(state);
}

function startDemo() {
    useDemo = true;
    demoState = buildDemoState();
    applyState(demoState);

    // a cada 8s simula um vencedor pra mostrar a animação
    if (!window.__demoWinnerTimer) {
        window.__demoWinnerTimer = setInterval(() => {
            if (!lastState || !lastState.participants || !lastState.participants.length) return;
            const p = lastState.participants[Math.floor(Math.random() * lastState.participants.length)];
            const winners = ['KAZUMA77', 'FIRE_BIRD_2024', 'NIKOTIN_X', 'SHADOW_KNIGHT', 'MEGAMU_PLAYER'];
            const w = winners[Math.floor(Math.random() * winners.length)];
            applyState({
                ...lastState,
                giveaway: {
                    ...lastState.giveaway,
                    current_winner: {
                        username: w,
                        platform: p.platform,
                        weight: p.weight,
                        chance_pct: 100 / lastState.participants.length,
                        award: '',
                        drawn_at: Date.now() / 1000,
                    },
                    winner_deadline: Date.now() / 1000 + 60,
                },
            });
            // depois de 8s limpa o vencedor
            setTimeout(() => {
                if (lastState) {
                    applyState({
                        ...lastState,
                        giveaway: { ...lastState.giveaway, current_winner: null, winner_deadline: 0 },
                    });
                }
            }, 8000);
        }, 12000);
    }
}

// A prévia incorporada em Identidade Visual executa a MESMA cena de OBS,
// com dados fictícios e sem conexão com a coleta ou o chat verdadeiro.
function renderAppearancePreview(payload={}) {
    if(previewRevelationTimer)clearTimeout(previewRevelationTimer);
    const mode=payload.mode||'collection';
    const scene=buildDemoState();
    scene.giveaway.prizes=[{name:'Talisman of Chaos',icon:'🎁'},
                           {name:'Selo do Cavalo Fantasma',icon:'🎁'}];
    scene.appearance=payload.appearance||{};
    const person=scene.participants[0];
    const winner={username:'EXEMPLO_PLAYER',platform:person.platform,
        chance_pct:12.5,weight:1,drawn_at:Date.now()/1000,avatar_url:''};
    const g=scene.giveaway;
    if(mode==='drawing'||mode==='winner'||mode==='nick') {
        g.current_winner=winner;
        g.winner_deadline=Date.now()/1000+60;
    }
    if(mode==='drawing') {
        const styles=DrawAnimations.styles;
        const requested=scene.appearance.draw_animation||'roulette';
        let animation=requested;
        if(requested==='random') {
            const options=styles.filter(x=>x!==previewLastDrawStyle);
            animation=options[Math.floor(Math.random()*options.length)];
        }
        if(!styles.includes(animation))animation='roulette';
        previewLastDrawStyle=animation;
        g.draw_animation_active=animation;
        const seconds=Math.max(2,Math.min(10,Number(scene.appearance.draw_animation_seconds)||4));
        g.draw_reveal_until=Date.now()/1000+seconds;
        g.winner_deadline=0;
        previewRevelationTimer=setTimeout(()=> {
            if(!lastState || lastState.giveaway.current_winner!==winner)return;
            g.draw_reveal_until=0;
            g.winner_deadline=Date.now()/1000+60;
            applyState(scene);
        },seconds*1000);
    } else if(mode==='nick') {
        g.current_winner=null;
        g.winner_deadline=0;
        g.winner_chat={winner,awaiting_nick:false,nick_command:'!nick',
            captcha_confirmed:true,messages:[{id:'demo',text:'!EXEMPLO_PLAYER'}],
            nick_verification:{status:'success',nick:'EXEMPLO_PLAYER',
                result:'✅ EXEMPLO_PLAYER existe no MEGAMU! ⚔️ Nível 400 | 🔄 25 RR | 🎯 Hunt 10'}};
    }
    applyState(scene);
}

function connectWS() {
    const proto = location.protocol === 'https:' ? 'wss' : 'ws';
    const ws = new WebSocket(`${proto}://${location.host}/ws`);

    ws.onopen = () => console.log('overlay-sorteio WS conectado');

    ws.onmessage = (e) => {
        try {
            const msg = JSON.parse(e.data);
            if (msg.state) lastSocketUpdate = Date.now();
            if (msg.type === 'init' && msg.state) {
                applyState(msg.state);
            } else if (msg.state) {
                applyState(msg.state);
            }
        } catch (err) { console.error(err); }
    };

    ws.onclose = () => {
        console.log('overlay-sorteio WS fechado, tentando reconectar...');
        setTimeout(connectWS, 2000);
    };

    ws.onerror = () => ws.close();
}

// A fonte do OBS também recupera o estado por HTTP se o socket estiver indisponível.
let refreshingState = false;
async function refreshState() {
    if (refreshingState) return;
    refreshingState = true;
    const started = Date.now();
    try {
        const response = await fetch('/api/state', {cache:'no-store'});
        if (response.ok) {
            const data = await response.json();
            if (lastSocketUpdate <= started) applyState(data);
        }
    } catch (_) {} finally { refreshingState = false; }
}
if(standalonePreview) {
    document.body.classList.add('appearance-preview-mode');
    renderAppearancePreview({mode:'collection'});
    if(typeof window!=='undefined'&&window.addEventListener)window.addEventListener('message',event=> {
        if(event.origin!==location.origin || event.data?.source!=='sorteador-appearance-preview')return;
        renderAppearancePreview(event.data);
    });
} else {
    refreshState();
    setInterval(refreshState, 2000);
    connectWS();
}
// Relógios locais também funcionam na prévia, sem WebSocket nem bot.
setInterval(() => { if (lastState) {
    renderDrawSuspense(lastState);
    renderCaptcha(lastState);
    if(lastState.giveaway?.draw_reveal_until) {
        renderBanner(lastState);
        renderParticipants(lastState);
        renderWinner(lastState);
        renderWinnerChat(lastState);
    }
} }, 250);
