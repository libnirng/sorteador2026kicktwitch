(() => {
    const defaults = {primary_color:'#79e8a4',accent_color:'#c060ff',bg_color:'#0b0e18',wheel_gold:'#d4af63',wheel_dark:'#1b242c',wheel_size:760,winner_font_size:48,winner_animation:'classic',draw_animation:'roulette',draw_animation_seconds:4,overlay_font:'Georgia',show_prize_list:true,show_chances_overlay:false};
const labels = {giveaway_open:'Abertura',giveaway_paused:'Pausa',giveaway_resumed:'Retomada',giveaway_closed:'Encerramento',winner_announced:'Anunciar vencedor do sorteio',winner_claim_instructions:'Vencedor respondeu: instruções para receber prêmio (!nick)',winner_declined:'Vencedor desistiu pelo chat',winner_skip_limit:'Limite de desistências atingido',nick_lookup:'Resposta ao comando de nick MEGAMU',nick_lookup_error:'Erro ao consultar nick MEGAMU',rank_lookup:'Consulta ao histórico (!rank)',prize_won:'Anunciar nick e prêmio da roleta',entry_accepted:'Inscrição confirmada e peso em x',entry_repeat:'Já está participando',captcha_challenge:'Pedir captcha ao vencedor marcado',captcha_success:'Captcha correto',captcha_retry:'Captcha incorreto: nova tentativa',captcha_fail:'Captcha incorreto: tentativas esgotadas',winner_no_response:'Prazo encerrado',next_prize:'Próximo sorteio: prêmio selecionado'};
    let initialized = false;
    const obsPreviewFrame=$('appearance-obs-iframe');
    const obsPreviewContainer=$('appearance-obs-frame');
    function resizeObsPreview() {
        const width=obsPreviewContainer.clientWidth;
        if(width>0)obsPreviewFrame.style.transform=`scale(${width/1920})`;
    }
    function sendObsPreview(a) {
        if(!obsPreviewFrame.contentWindow)return;
        obsPreviewFrame.contentWindow.postMessage({source:'sorteador-appearance-preview',
            mode:$('appearance-preview-mode').value,appearance:a||readAppearance()},location.origin);
    }
    obsPreviewFrame.addEventListener('load',()=>{resizeObsPreview();sendObsPreview();});
    $('appearance-preview-mode').addEventListener('change',()=>{
        sendObsPreview();
        $('appearance-preview-hint').textContent='Prévia atualizada. Para aplicar na transmissão, clique em Salvar aparência.';
    });
    $('btn-appearance-preview-play').addEventListener('click',()=>{
        resizeObsPreview();sendObsPreview();
        $('appearance-preview-hint').textContent='▶ Cenário reproduzido no quadro acima. Nenhum sorteio real foi realizado.';
    });
    if(typeof ResizeObserver!=='undefined')new ResizeObserver(resizeObsPreview).observe(obsPreviewContainer);
    window.addEventListener('resize',resizeObsPreview);
    document.querySelector('[data-tab="appearance"]').addEventListener('click',()=>{
        requestAnimationFrame(()=>{resizeObsPreview();sendObsPreview();});
    });
    for (const platform of ['twitch','kick']) {
        $('bot-send-'+platform).addEventListener('change', async event => {
            const input=event.target;input.disabled=true;
            const feedback=$(platform+'-announcements-feedback');
            try {
                const response=await fetch('/api/bots/'+platform+'/announcements', {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({enabled:input.checked})});
                if(!response.ok) throw Error('Não foi possível salvar.');
                feedback.textContent=input.checked?'Anúncios ativados e salvos.':'Chat silenciado; coleta de participantes continua ativa.';
            } catch(error) {input.checked=!input.checked;feedback.textContent=error.message;}
            finally {input.disabled=false;}
        });
    }
    function theme(a) {
        const style = document.documentElement.style;
        style.setProperty('--primary', a.primary_color);
        style.setProperty('--primary-soft', a.primary_color+'20');
        style.setProperty('--primary-hover', `color-mix(in srgb, ${a.primary_color} 82%, white)`);
        style.setProperty('--primary-press', `color-mix(in srgb, ${a.primary_color} 84%, black)`);
        style.setProperty('--bg', a.bg_color);
        style.setProperty('--accent', a.accent_color);
        $('appearance-sample').style.setProperty('--gold', a.wheel_gold);
        $('appearance-sample').style.setProperty('--graphite', a.wheel_dark);
        sendObsPreview(a);
    }
    function readAppearance() {
        return Object.fromEntries(Object.entries(defaults).map(([k,v]) => {
            const el=$('ap-'+k); return [k, typeof v === 'boolean' ? el.checked : typeof v === 'number' ? Number(el.value) : el.value];
        }));
    }
    function fillAppearance(a) {
        Object.keys(defaults).forEach(k=> { const el=$('ap-'+k); if (el.type==='checkbox') el.checked=!!a[k]; else el.value=a[k]; });
        theme(a);
        replayWinnerAnimation();
        replayDrawAnimation();
    }
    function replayWinnerAnimation() {
        const preview=$('winner-animation-preview');
        const selected=$('ap-winner_animation').value || 'classic';
        const choices=['classic','spotlight','rise','flip','burst'];
        const animation=selected==='random'?choices[Math.floor(Math.random()*choices.length)]:selected;
        preview.classList.remove('playing');
        preview.dataset.animation=animation;
        void preview.offsetWidth; // reinicia a prévia, sem afetar o sorteio real
        preview.classList.add('playing');
    }
    $('ap-winner_animation').addEventListener('change',replayWinnerAnimation);
    $('btn-winner-animation-preview').addEventListener('click',replayWinnerAnimation);
    DrawAnimations.mount($('draw-animation-preview-art'));
    // Os nomes são fictícios na prévia; no OBS são lidos dos inscritos reais.
    const drawPreviewNames=['Biaabs','Santaronirj','Idronesa','DarcheMan',
        'LAVIE90','GamerPro','Kyrestoner','LunaGG','NikoTV','Mago77',
        'StarLight','FenixBR'];
    let drawPreviewInterval=null;
    let lastPreviewDrawStyle='';
    const drawLabels={roulette:'roleta',slots:'caça-níquel',countdown:'contagem',cards:'cartas',dice:'dados',radar:'radar',chest:'baú',particles:'estrelas',portal:'portal',spotlights:'holofotes'};
    function replayDrawAnimation() {
        if(drawPreviewInterval)clearInterval(drawPreviewInterval);
        const preview=$('draw-animation-preview');
        const option=$('ap-draw_animation').value;
        const variants=DrawAnimations.styles;
        const selected=option==='random'
            ? variants.filter(style=>style!==lastPreviewDrawStyle)[Math.floor(Math.random()*(variants.length-1))]
            : option;
        if(variants.includes(selected))lastPreviewDrawStyle=selected;
        const seconds=Math.max(2,Math.min(10,Number($('ap-draw_animation_seconds').value)||4));
        preview.dataset.animation=selected;
        preview.classList.remove('draw-preview-finished');
        preview.classList.remove('draw-replaying');
        void preview.offsetWidth;
        preview.classList.add('draw-replaying');
        if(option==='none') {
            $('draw-preview-caption').textContent='VENCEDOR REVELADO IMEDIATAMENTE';
            $('draw-preview-bar').style.width='100%';
            return;
        }
        $('draw-preview-caption').textContent=option==='random'
            ? `PRÉVIA ALEATÓRIA: ${(drawLabels[selected]||selected).toUpperCase()}` : 'QUEM SERÁ?';
        const started=Date.now();
        const tick=()=> {
            const remaining=Math.max(0,seconds-(Date.now()-started)/1000);
            $('draw-preview-bar').style.width=`${Math.min(100,(1-remaining/seconds)*100)}%`;
            DrawAnimations.countdown($('draw-animation-preview-art'),remaining,seconds);
            DrawAnimations.renderNames($('draw-animation-preview-art'),drawPreviewNames,
                (Date.now()-started)/1000,seconds,'Biaabs');
            if(remaining===0) {
                clearInterval(drawPreviewInterval);
                drawPreviewInterval=null;
                $('draw-preview-caption').textContent='🏆 HORA DE REVELAR!';
                preview.classList.add('draw-preview-finished');
            }
        };
        tick();
        drawPreviewInterval=setInterval(tick,100);
    }
    $('ap-draw_animation').addEventListener('change',replayDrawAnimation);
    $('ap-draw_animation_seconds').addEventListener('change',replayDrawAnimation);
    $('btn-draw-animation-preview').addEventListener('click',replayDrawAnimation);
    async function save(url,body,status) {
        try {
            const response=await fetch(url,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
            const data=await response.json();
            if(!response.ok) throw Error(typeof data.detail==='string'?data.detail:'Confira os valores dos campos.');
            $(status).textContent='Configurações salvas.';
        } catch(e) { $(status).textContent='Não foi possível salvar: '+e.message; }
    }
    $('btn-appearance-save').onclick=()=>save('/api/appearance',readAppearance(),'appearance-status');
    $('btn-appearance-reset').onclick=()=>{fillAppearance(defaults);$('appearance-status').textContent='Prévia restaurada. Clique em Salvar para aplicar.';};
    document.querySelector('[data-panel="appearance"]').addEventListener('input',()=>theme(readAppearance()));
    $('btn-chat-settings-save').onclick=()=> {
        const events={}, templates={}, destinations={};
        Object.keys(labels).forEach(event=> {
            events[event]=$('event-'+event).checked;
            templates[event]={twitch:$('tpl-'+event+'-twitch').value,kick:$('tpl-'+event+'-kick').value};
            destinations[event]={twitch:$('dest-'+event+'-twitch').checked,kick:$('dest-'+event+'-kick').checked};
        });
        save('/api/bots/settings',{twitch_enabled:$('bot-send-twitch').checked,kick_enabled:$('bot-send-kick').checked,events,templates,destinations},'chat-settings-status');
    };
    $('btn-viewer-commands-save').onclick=async()=> {
        const feedback=$('viewer-commands-feedback');
        const button=$('btn-viewer-commands-save');
        button.disabled=true;feedback.textContent='Salvando comandos…';
        try {
            const config={skip_enabled:$('viewer-skip-enabled').checked,
                skip_command:$('viewer-skip-command').value.trim().toLowerCase(),
                skip_limit:Number($('viewer-skip-limit').value),
                nick_enabled:$('viewer-nick-enabled').checked,
                nick_command:$('viewer-nick-command').value.trim().toLowerCase(),
                rank_enabled:$('viewer-rank-enabled').checked,
                rank_command:$('viewer-rank-command').value.trim().toLowerCase()};
            const response=await fetch('/api/chat/commands/config',{
                method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(config)});
            const data=await response.json();
            if(!response.ok)throw Error(typeof data.detail==='string'?data.detail:'Verifique o comando e o limite informado.');
            if(state)state.viewer_commands=data;
            feedback.textContent='Comandos salvos. Válidos para Twitch e Kick.';
        } catch(error){feedback.textContent='Não foi possível salvar: '+error.message;}
        finally {button.disabled=false;}
    };
    function init() {
        if(!state || initialized) return;
        initialized=true;
        fillAppearance({...defaults,...state.appearance});
        const commands=state.viewer_commands || {};
        $('viewer-skip-enabled').checked=commands.skip_enabled!==false;
        $('viewer-skip-command').value=commands.skip_command || '!pular';
        $('viewer-skip-limit').value=commands.skip_limit || 3;
        $('viewer-nick-enabled').checked=commands.nick_enabled!==false;
        $('viewer-nick-command').value=commands.nick_command || '!nick';
        $('viewer-rank-enabled').checked=commands.rank_enabled!==false;
        $('viewer-rank-command').value=commands.rank_command || '!rank';
        $('bot-send-twitch').checked=state.bots.twitch_enabled;
        $('bot-send-kick').checked=state.bots.kick_enabled;
        for(const [event,label] of Object.entries(labels)) {
            const section=document.createElement('details');
            const summary=document.createElement('summary'); summary.textContent=label;
            section.append(summary);
            if (event === 'winner_announced' || event === 'winner_claim_instructions' || event === 'prize_won') section.open=true;
            const row=document.createElement('label'); row.className='check'; row.textContent='Anunciar este evento ';
            const check=document.createElement('input');check.type='checkbox';check.id='event-'+event;check.checked=!!state.chat_events[event];row.append(check);section.append(row);
            if (event === 'prize_won') check.addEventListener('change', () => {
                $('roleta-announce-chat').checked=check.checked;
                window.markRoletaConfigDirty?.();
            });
            const platforms=document.createElement('div');platforms.className='message-platforms';
            for(const platform of ['twitch','kick']) {
                const wrapper=document.createElement('div');wrapper.className='message-platform';
                const destination=document.createElement('label');destination.className='check';
                const dest=document.createElement('input');dest.type='checkbox';dest.id='dest-'+event+'-'+platform;dest.checked=state.chat_event_platforms?.[event]?.[platform]!==false;
                destination.append(dest,document.createTextNode(platform==='twitch'?'Enviar na Twitch':'Enviar na Kick'));
                const labelEl=document.createElement('label');labelEl.textContent='Texto da mensagem';
                const input=document.createElement('input');input.type='text';input.maxLength=400;input.id='tpl-'+event+'-'+platform;input.value=state.message_templates[event]?.[platform] || '';labelEl.append(input);
                wrapper.append(destination,labelEl);platforms.append(wrapper);
            }
            section.append(platforms);
            const hint=document.createElement('p');hint.className='hint';hint.textContent=event==='rank_lookup'
                ? 'Campos do !rank: {nick}, {total}, {respondeu}, {mamou}, {desistiu}, {pulou}, {pendente}. O histórico considera a plataforma em que o comando foi enviado.'
: 'Campos: {nome}, {plataforma}, {premio}, {comando_nick}, {keyword}, {tempo}, {desafio}, {resposta}, {tentativa}, {restantes}, {peso}, {chance}, {participantes}, {proximo}, {comando}, {usos}, {limite}, {nick}, {resultado}, {motivo}. Peso: fator em x (ex.: {peso}x).';section.append(hint);
            $('chat-event-fields').append(section);
        }
    }
    setInterval(init,300);

    setInterval(()=>{
        const config=state?.viewer_commands;
        const label=$('viewer-skip-usage');
        if(config && label)label.textContent=`Desistências nesta coleta: ${config.skip_uses} de ${config.skip_limit}`;
    },1000);

    window.renderMegaMu=()=> {
        const data=state?.megamu;if(!data)return;
        if(!$('megamu-dv').dataset.loaded) {
            $('megamu-dv').value=data.dv || '';$('megamu-enabled').checked=!!data.enabled;
            $('megamu-dv').dataset.loaded='1';
        }
        $('megamu-config-status').textContent=data.error || (data.has_key?'Chave salva no .env. '+(data.updated_at?'Última consulta: '+new Date(data.updated_at*1000).toLocaleTimeString(): 'Aguardando consulta.'):'Cadastre DV e chave para consultar os prêmios.');
        $('megamu-awards').replaceChildren(...(data.awards || []).map(award=>{
            const item=document.createElement('li');item.textContent=award.name;return item;
        }));
    };
    $('btn-megamu-save').onclick=async()=> {
        try {
            await post('/api/megamu/config',{dv:$('megamu-dv').value.trim(),key:$('megamu-key').value.trim(),enabled:$('megamu-enabled').checked});
            $('megamu-key').value='';$('megamu-feedback').textContent='Conexão salva. O catálogo é consultado automaticamente; confira o estado da conexão.';
            window.refreshEnvStatus?.();
        } catch(error){$('megamu-feedback').textContent=error.message;}
    };
    $('btn-megamu-test').onclick=async()=> {
        $('megamu-feedback').textContent='Consultando prêmios...';
        try {
            const response=await fetch('/api/megamu/awards');const data=await response.json();
            if(!response.ok)throw Error(data.detail || 'Falha na consulta.');
            state=await (await fetch('/api/state')).json();render();window.renderMegaMu();$('megamu-enabled').checked=!!data.enabled;
            $('megamu-feedback').textContent=`Consulta confirmada: ${data.awards.length} prêmios disponíveis.`;
            window.refreshEnvStatus?.();
        } catch(error){$('megamu-feedback').textContent=error.message;}
    };

})();
