(() => {
    let signature='';
    let selecting=false;
    window.renderGiveawayPrizes=()=> {
        const prizes=state?.giveaway.prizes || [];
        const selected=state?.giveaway.selected_prize;
        const key=JSON.stringify([prizes,selected?.id]);
        $('giveaway-selected-prize').textContent=selected?`Próximo sorteio: ${selected.name}`:'Nenhum prêmio selecionado.';
        if(key===signature)return;
        signature=key;
        const elements=prizes.map(prize=> {
            const item=document.createElement('div');item.className='giveaway-prize-item';
            const button=document.createElement('button');button.type='button';button.className='giveaway-prize-select';
            button.dataset.prizeId=prize.id;button.setAttribute('aria-pressed',String(selected?.id===prize.id));
            const name=document.createElement('span');name.className='giveaway-prize-name';name.textContent=prize.name;
            const source=document.createElement('small');source.textContent=prize.source==='megamu'?'MegaMu':'Personalizado';
            button.append(name,source);
            button.onclick=async()=> {
                if(selecting)return;
                selecting=true;button.disabled=true;
                $('giveaway-prize-feedback').textContent='Selecionando e anunciando...';
                try {
                    const result=await post('/api/giveaway/prize/select',{id:prize.id});
                    $('giveaway-prize-feedback').textContent=Object.entries(result.announcements || {}).map(([platform,result])=>
                        `${platform==='twitch'?'Twitch':'Kick'}: ${result.sent?'próximo sorteio anunciado':result.reason}`).join(' • ');
                } catch(error){$('giveaway-prize-feedback').textContent=error.message;}
                finally {selecting=false;button.disabled=false;}
            };
            item.append(button);
            if(prize.source==='custom') {
                const remove=document.createElement('button');remove.type='button';remove.className='giveaway-prize-remove';
                remove.textContent='×';remove.setAttribute('aria-label','Remover prêmio '+prize.name);remove.title='Remover prêmio personalizado';
                remove.onclick=async()=> {
                    remove.disabled=true;
                    try {
                        const response=await fetch('/api/giveaway/prizes/'+encodeURIComponent(prize.id),{method:'DELETE'});
                        if(!response.ok)throw Error('Não foi possível remover o prêmio.');
                        $('giveaway-prize-feedback').textContent='Prêmio removido.';
                    } catch(error){$('giveaway-prize-feedback').textContent=error.message;remove.disabled=false;}
                };
                item.append(remove);
            }
            return item;
        });
        if(!elements.length) {
            const empty=document.createElement('p');empty.className='hint';empty.textContent='Nenhum prêmio disponível. Adicione um prêmio ou configure a MegaMu em Conexões.';elements.push(empty);
        }
        $('giveaway-prize-list').replaceChildren(...elements);
    };
    $('btn-giveaway-prize-add').onclick=()=> {$('giveaway-prize-form').hidden=false;$('giveaway-prize-name').focus();};
    $('btn-giveaway-prize-cancel').onclick=()=> {$('giveaway-prize-form').hidden=true;$('giveaway-prize-form').reset();};
    $('giveaway-prize-form').onsubmit=async event=> {
        event.preventDefault();
        const name=$('giveaway-prize-name').value.trim();
        if(!name)return;
        try {
            await post('/api/giveaway/prizes',{name});
            $('giveaway-prize-form').reset();$('giveaway-prize-form').hidden=true;
            $('giveaway-prize-feedback').textContent='Prêmio adicionado à lista e ao overlay.';
        } catch(error){$('giveaway-prize-feedback').textContent=error.message;}
    };
    for(const platform of ['twitch','kick'])for(const group of ['sub','vip','mod']) {
        $('weight-'+platform+'-'+group).addEventListener('input',()=>{giveawayWeightsDirty=true;});
    }
    $('btn-giveaway-weights-save').onclick=async()=> {
        const button=$('btn-giveaway-weights-save');button.disabled=true;
        try {
            const body=Object.fromEntries(['twitch','kick'].map(platform=>[platform,Object.fromEntries(['sub','vip','mod'].map(group=>[group,$('weight-'+platform+'-'+group).value.trim()]))]));
            await applyRules();
            const response=await fetch('/api/giveaway/weights',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
            const data=await response.json();
            if(!response.ok)throw Error(typeof data.detail==='string'?data.detail:'Informe chances válidas a partir de 1, como 1,5 ou 2,5.');
            giveawayWeightsDirty=false;$('giveaway-weights-feedback').textContent='Chances salvas. Lista atual e novas entradas atualizadas.';
            state=await (await fetch('/api/state')).json();render();
        } catch(error){$('giveaway-weights-feedback').textContent=error.message;}
        finally {button.disabled=false;}
    };
    if(state)window.renderGiveawayPrizes();
})();
