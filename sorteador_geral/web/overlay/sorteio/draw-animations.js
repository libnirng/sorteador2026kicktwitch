/* As dez cenas exibem os próprios participantes. O resultado é definido no
   servidor; o movimento é apenas a apresentação visual do sorteio. */
window.DrawAnimations = Object.freeze({
  styles: ['roulette','slots','countdown','cards','dice','radar','chest','particles','portal','spotlights'],
  mount(target) {
    if (!target) return;
    target.innerHTML = `
      <div class="draw-art draw-art--roulette"><div class="draw-wheel"><div class="draw-wheel-labels"></div><b>★</b></div><i class="draw-pointer">▼</i></div>
      <div class="draw-art draw-art--slots"><span class="draw-slot-name"></span><span class="draw-slot-name"></span><span class="draw-slot-name"></span></div>
      <div class="draw-art draw-art--countdown"><b class="draw-number">3</b><i></i><div class="draw-count-names"><span></span><span></span><span></span></div></div>
      <div class="draw-art draw-art--cards"><span class="draw-card-name"></span><span class="draw-card-name"></span><span class="draw-card-name"></span></div>
      <div class="draw-art draw-art--dice"><span><strong>⚄</strong><small class="draw-dice-name"></small></span><span><strong>⚂</strong><small class="draw-dice-name"></small></span></div>
      <div class="draw-art draw-art--radar"><div class="draw-radar"><b>✦</b><div class="draw-radar-names"><span></span><span></span><span></span><span></span><span></span></div></div></div>
      <div class="draw-art draw-art--chest"><span>🎁</span><i></i><div class="draw-chest-names"><span></span><span></span><span></span></div></div>
      <div class="draw-art draw-art--particles"><b>✦</b>${Array.from({length:9},(_,i)=>`<i style="--i:${i}">✧</i>`).join('')}<div class="draw-particle-names">${Array.from({length:8},()=>'<span></span>').join('')}</div></div>
      <div class="draw-art draw-art--portal"><i></i><i></i><span>✧</span><div class="draw-portal-names"><span></span><span></span><span></span><span></span></div></div>
      <div class="draw-art draw-art--spotlights"><i></i><i></i><i></i><b>★</b><div class="draw-spotlight-names"><span></span><span></span><span></span></div></div>`;
  },
  // Páginas de até dez nomes mantêm as fatias legíveis quando há muitos inscritos.
  // Os demais efeitos percorrem os mesmos nomes em intervalos curtos.
  frames(names,step=0) {
    const pool=(Array.isArray(names)?names:[]).map(n=>String(n??'').trim()).filter(Boolean).slice(0,5000);
    if(!pool.length)pool.push('AGUARDANDO');
    const tick=Math.max(0,Math.floor(Number(step)||0));
    const select=(count,start=tick)=>Array.from({length:Math.min(count,pool.length)},(_,i)=>pool[(start+i)%pool.length]);
    const count=Math.min(10,pool.length);
    return {wheel:select(count,Math.floor(tick/3)*count),slots:select(3),countdown:select(3),
      cards:select(3,tick+1),dice:select(2),radar:select(5),chest:select(3,tick+1),
      particles:select(8),portal:select(4),spotlights:select(3),total:pool.length};
  },
  renderNames(target,names,elapsed=0,total=4,winnerName='') {
    if(!target)return;
    const seconds=Math.max(.1,Number(total)||4);
    const progress=Math.min(1,Math.max(0,elapsed)/seconds);
    const step=Math.floor(Math.max(0,elapsed)*2.5);
    const frame=this.frames(names,step);
    const finalWheel=this.frames(names,Math.floor(seconds*.4*2.5)).wheel;
    const wheelNames=progress>=.4 ? [...finalWheel] : [...frame.wheel];
    // O nome sorteado permanece entre as fatias, inclusive com mais de 10 inscritos.
    const selected=String(winnerName||'').trim();
    const selectedLabel=(Array.isArray(names)?names:[]).find(n=>String(n)===selected||String(n).startsWith(selected+' ('))||selected;
    if(selectedLabel&&!wheelNames.includes(selectedLabel))wheelNames[wheelNames.length-1]=selectedLabel;
    const wheel=target.querySelector?.('.draw-wheel');
    const zone=target.querySelector?.('.draw-wheel-labels');
    if(wheel&&zone) {
      const signature=JSON.stringify(wheelNames);
      if(zone.dataset?.names!==signature) {
        const count=wheelNames.length;
        const labels=wheelNames.map((name,i)=>{
          const chip=document.createElement('span');
          chip.className='draw-wheel-name';chip.textContent=name;chip.title=name;
          chip.style?.setProperty?.('--angle',`${((i+.5)*360/count).toFixed(2)}deg`);
          return chip;
        });
        zone.replaceChildren(...labels);
        if(zone.dataset)zone.dataset.names=signature;
        const colors=['#7546ad','#214e65','#358a72','#8e5b2d','#875190','#287a82','#906439','#547e48','#5562a0','#9b497c'];
        const arcs=wheelNames.map((_,i)=>`${colors[i%colors.length]} ${(360*i/count).toFixed(2)}deg ${(360*(i+1)/count).toFixed(2)}deg`);
        wheel.style.background=`conic-gradient(${arcs.join(',')})`;
      }
      if(wheel.clientWidth>0)wheel.style?.setProperty?.('--wheel-label-radius',`${Math.round(wheel.clientWidth*.31)}px`);
      // A desaceleração converge para a fatia do resultado decidido no servidor.
      const winnerIndex=wheelNames.findIndex(n=>n===selectedLabel);
      const landing=winnerIndex>=0 ? (winnerIndex+.5)*360/wheelNames.length : 0;
      const turns=4*360 + (360-landing);
      wheel.style.transform=`rotate(${(turns*(1-Math.pow(1-progress,3))).toFixed(2)}deg)`;
    }
    const selectors={'.draw-slot-name':frame.slots,'.draw-count-names span':frame.countdown,
      '.draw-card-name':frame.cards,'.draw-dice-name':frame.dice,'.draw-radar-names span':frame.radar,
      '.draw-chest-names span':frame.chest,'.draw-particle-names span':frame.particles,
      '.draw-portal-names span':frame.portal,'.draw-spotlight-names span':frame.spotlights};
    for(const [selector,values] of Object.entries(selectors)) {
      const elements=target.querySelectorAll?.(selector)||[];
      Array.from(elements).forEach((el,i)=>{
        const name=values[i%values.length]||'';
        if(el.textContent!==name){el.textContent=name;el.title=name;}
      });
    }
  },
  countdown(target,remaining,total) {
    const value=target?.querySelector?.('.draw-number');
    if(value) value.textContent=String(Math.min(3,Math.max(1,Math.ceil(remaining/(Math.max(.01,total)/3)))));
  }
});
