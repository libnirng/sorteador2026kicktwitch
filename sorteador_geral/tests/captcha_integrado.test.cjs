/* Testa a lógica visual sem precisar iniciar um navegador ou servidor. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const root = path.join(__dirname, '..');
const html = fs.readFileSync(path.join(root, 'web/overlay/sorteio/index.html'), 'utf8');
const css = fs.readFileSync(path.join(root, 'web/overlay/sorteio/style.css'), 'utf8');
const js = fs.readFileSync(path.join(root, 'web/overlay/sorteio/app.js'), 'utf8');
const legacy = fs.readFileSync(path.join(root, 'web/overlay/captcha/index.html'), 'utf8');
const adminHtml = fs.readFileSync(path.join(root, 'web/admin/index.html'), 'utf8');
const adminJs = fs.readFileSync(path.join(root, 'web/admin/js/settings.js'), 'utf8');
const adminCss = fs.readFileSync(path.join(root, 'web/admin/css/admin.css'), 'utf8');
const drawCss = fs.readFileSync(path.join(root, 'web/overlay/sorteio/draw-animations.css'), 'utf8');
const drawJs = fs.readFileSync(path.join(root, 'web/overlay/sorteio/draw-animations.js'), 'utf8');

assert.match(html, /id="captcha-layer"[^>]*hidden/);
assert.match(html, /id="captcha-countdown"/);
assert.match(html, /id="winner-progress"/);
assert.doesNotMatch(html, /id="winner-chat-(avatar|name|platform|claim)"/);
assert.match(css, /\.captcha-layer\[hidden\]/);
assert.match(legacy, /c\.deadline-Date\.now\(\)\/1000/);
for (const type of ['classic','spotlight','rise','flip','burst','random']) {
    assert.match(adminHtml, new RegExp(`<option value="${type}"`));
}
for (const keyframe of ['winnerSpotlight','winnerRise','winnerFlip','winnerBurst']) {
    assert.match(css, new RegExp(`@keyframes ${keyframe}`));
}
assert.match(adminJs, /replayWinnerAnimation/);
assert.match(adminCss, /\.winner-animation-preview/);
for(const name of ['roulette','slots','countdown','cards','dice','radar','chest','particles','portal','spotlights']) {
    assert.match(adminHtml,new RegExp(`<option value="${name}"`));
    assert.match(drawCss,new RegExp(`draw-art--${name}`));
}
assert.match(adminHtml,/<option value="random">🎲 Aleatória/);
assert.match(adminJs,/lastPreviewDrawStyle/);
assert.match(js,/g\.draw_animation_active/);
assert.match(html,/id="draw-suspense-stage"[^>]*hidden/);
assert.match(adminJs,/replayDrawAnimation/);
assert.match(js,/isDrawPending/);
assert.match(js,/shownAsWinner/);
assert.match(adminHtml,/id="appearance-obs-iframe"[^>]*src="\/overlay\/sorteio\?preview=1"/);
assert.match(adminHtml,/id="appearance-preview-mode"/);
assert.match(adminHtml,/id="giveaway-nick-feedback"/);
assert.match(adminHtml,/id="giveaway-draw-animation-status"/);
assert.match(adminHtml,/id="antibot-max-attempts"[^>]*max="100"[^>]*min="0"/);
assert.match(adminHtml,/0 = infinitas/);
assert.match(adminJs,/captcha_retry:'Captcha incorreto: nova tentativa'/);
assert.match(adminJs,/sendObsPreview/);
assert.match(js,/renderAppearancePreview/);
assert.match(js,/standalonePreview/);
assert.match(js,/nick_verification/);
assert.match(adminHtml,/settings\.js\?v=27-nomes/);
assert.match(html,/app\.js\?v=27-nomes/);
assert.match(adminHtml,/draw-animations\.js\?v=27-nomes/);
assert.match(html,/draw-animations\.css\?v=27-nomes/);
for(const selector of ['draw-wheel-labels','draw-slot-name','draw-card-name',
    'draw-dice-name','draw-radar-names','draw-chest-names','draw-particle-names',
    'draw-portal-names','draw-spotlight-names','draw-count-names']) {
    assert.match(drawJs,new RegExp(selector));
}
assert.match(drawCss,/\.draw-wheel-name/);
assert.match(drawCss,/\.draw-art--slots \.draw-slot-name/);
assert.match(adminJs,/drawPreviewNames/);
assert.match(js,/DrawAnimations\.renderNames/);
assert.match(css,/\.draw-suspense-stage\{position:fixed;inset:0;z-index:9999/);
assert.match(css,/\.draw-suspense-stage \.draw-suspense-title,[\s\S]*?display:none!important/);
assert.match(css,/\.draw-suspense-stage\.draw-shell \.draw-animation-art\{width:min\(86vw,1150px\)/);
assert.match(css,/body\.drawing-solo \.stage > :not\(\.draw-suspense-stage\)\{visibility:hidden!important\}/);

class FakeElement {
    constructor() {
        this.hidden = false;
        this.textContent = '';
        this.className = '';
        this.dataset = {};
        this.attributes = {};
        this.style = {};
        this.children = [];
        this.classes = new Set();
        this.classList = {
            add: name => this.classes.add(name),
            remove: name => this.classes.delete(name),
            toggle: (name, on) => on ? this.classes.add(name) : this.classes.delete(name),
            contains: name => this.classes.has(name),
        };
    }
    setAttribute(name, value) { this.attributes[name] = value; }
    replaceChildren(...children) { this.children = children; }
    append(child) { this.children ??= []; this.children.push(child); }
    insertBefore(child, before) {
        if(!before) this.children.push(child);
        else this.children.splice(Math.max(0,this.children.indexOf(before)),0,child);
        child.parent = this;
    }
    remove() { if(this.parent) this.parent.children=this.parent.children.filter(el=>el!==this); }
    querySelector() { return new FakeElement(); }
}
const dom = new Map();
const element = id => {
    if (!dom.has(id)) dom.set(id, new FakeElement());
    return dom.get(id);
};
let now = 1_800_000_000_000;
const context = vm.createContext({
    document: {
        getElementById: element,
        createElement: () => new FakeElement(),
        documentElement: {style: {setProperty() {}}},
        body: new FakeElement(),
    },
    Date: {now: () => now},
    setInterval: () => 1,
    clearInterval: () => {},
    setTimeout: () => 1,
    clearTimeout: () => {},
    console,
    fetch: () => Promise.reject(new Error('sem servidor: teste local')),
    location: {protocol: 'http:', host: 'localhost:8777', origin:'http://localhost:8777',search:''},
    WebSocket: class { constructor() {} },
});
context.window=context;
vm.runInContext(drawJs,context,{filename:'draw-animations.js'});
vm.runInContext(js, context, {filename: 'overlay/sorteio/app.js'});

// A roleta representa inscrições reais em fatias identificadas. Com >10
// inscritos mostra até dez nomes por vez; os demais efeitos também os exibem.
const roster=['Ana','Bia','Caio','Duda','Eli','Fefe','Gui','Hugo','Iara','Joao','Kika','Luan'];
const artFrame=context.DrawAnimations.frames(roster,0);
assert.equal(artFrame.wheel.length,10);
assert.equal(artFrame.wheel[0],'Ana');
assert.equal(artFrame.slots[0],'Ana');
assert.equal(artFrame.cards[0],'Bia');
assert.equal(artFrame.portal.length,4);
assert.equal(artFrame.particles.length,8);
assert.equal(context.DrawAnimations.frames(roster,3).wheel[0],'Kika');
const wheel=new FakeElement();
wheel.clientWidth=600;
const wheelLabels=new FakeElement();
const drawingArt={querySelector:selector=>selector==='.draw-wheel'?wheel:
    selector==='.draw-wheel-labels'?wheelLabels:null,
    querySelectorAll:()=>[]};
context.DrawAnimations.renderNames(drawingArt,roster,4,4,'Luan');
assert.equal(wheelLabels.children.length,10);
const winnerLabelIndex=wheelLabels.children.findIndex(el=>el.textContent==='Luan');
assert(winnerLabelIndex>=0);
assert.equal(wheelLabels.children[0].className,'draw-wheel-name');
assert.match(wheel.style.background,/conic-gradient\(/);
const finalAngle=Number(wheel.style.transform.match(/rotate\(([\d.]+)deg\)/)[1]);
const pointerAngle=(winnerLabelIndex+.5)*360/wheelLabels.children.length;
const offset=(finalAngle+pointerAngle)%360;
assert(Math.min(offset,360-offset)<.05,'A roleta deve terminar apontando ao vencedor real');
const entered={giveaway:{is_running:true,current_winner:{username:'Bia',platform:'kick'}},
    participants:[
        {username:'Ana',platform:'twitch',chance_pct:60,active:true},
        {username:'Bia',platform:'kick',chance_pct:0,active:true},
        {username:'Caio',platform:'kick',chance_pct:0,active:false},
    ]};
assert.deepEqual(Array.from(context.drawParticipantNames(entered)),['Ana','Bia']);

const base = {giveaway: {is_running: true}};
const winner = {username: 'Ganhador', platform: 'kick'};
const challenge = {question: 'Quanto é 12 + 7?', deadline: now / 1000 + 45};

// Animação escolhida: só acontece ao sortear, não a cada mensagem recebida.
const drawn = {...winner, chance_pct: 50, drawn_at: 2};
const drawing = {giveaway: {
    is_running:true, current_winner: drawn, winner_deadline: now/1000+60,
}, appearance:{winner_animation:'flip'}, participants:[]};
// A cena de suspense esconde o ganhador mesmo já escolhido pelo backend.
const suspense = {...drawing,giveaway:{...drawing.giveaway,winner_deadline:0,
    draw_reveal_until:now/1000+4},appearance:{...drawing.appearance,draw_animation:'portal',draw_animation_seconds:4}};
context.renderDrawSuspense(suspense);
context.renderWinner(suspense);
assert.equal(element('draw-suspense-stage').hidden,false);
assert.equal(element('draw-suspense-stage').dataset.animation,'portal');
const randomStyleResolved={...suspense,appearance:{...suspense.appearance,draw_animation:'random'},
    giveaway:{...suspense.giveaway,draw_animation_active:'dice'}};
context.renderDrawSuspense(randomStyleResolved);
assert.equal(element('draw-suspense-stage').dataset.animation,'dice');
assert.equal(element('winner-stage').classList.contains('active'),false);
assert.match(element('draw-suspense-subtitle').textContent,/4s/);
context.renderWinnerChat({...suspense,giveaway:{...suspense.giveaway,winner_chat:{messages:[{text:'teste'}]}}});
assert.equal(element('winner-chat-card').hidden,true);
now+=4100;
context.renderDrawSuspense(suspense);
context.renderWinner(suspense);
assert.equal(element('draw-suspense-stage').hidden,true);
assert.equal(element('winner-stage').classList.contains('active'),true);
now-=4100;
context.renderWinner(drawing);
assert.equal(element('winner-stage').classList.contains('active'), true);
assert.equal(element('winner-stage').dataset.animation, 'flip');
assert.equal(element('winner-stage').classList.contains('winner-animate'), true);
assert.equal(element('w-timer').hidden, false);
assert.equal(element('winner-progress').hidden, true);
context.renderWinner({...drawing, giveaway: {...drawing.giveaway, winner_chat:{messages:[{text:'oi'}]}}});
assert.equal(element('winner-stage').dataset.drawKey, 'kick:Ganhador:2');

// Mesmo que reste um snapshot antigo no navegador, o chat do vencedor deve
// desaparecer assim que o prazo acaba e não há vencedor ativo.
context.renderWinnerChat({giveaway: {
    is_running: true, current_winner: null, captcha: null,
    winner_chat: {winner, drawn_at: 1, messages: []},
}});
assert.equal(element('winner-chat-card').hidden, true);

// Depois do CAPTCHA, a mesma tela principal permanece em destaque. O cartão
// complementar traz SÓ a última mensagem, sem avatar/nome duplicados.
const claimState={giveaway: {
    is_running: true, current_winner: null, captcha: null, winner_deadline: 0,
    winner_chat: {winner:{...winner,chance_pct:50,drawn_at:2}, drawn_at: 2,
        messages: [{id:'a',text: 'k'}, {id:'b',text: 'branco'}],
        awaiting_nick: true, captcha_confirmed: true, nick_command: '!nick'},
    captcha_feedback:{username:'Ganhador',platform:'kick',status:'correct'},
}, appearance:{winner_animation:'flip'}, participants:[]};
context.renderWinner(claimState);
assert.equal(element('winner-stage').classList.contains('active'), true);
assert.equal(element('w-timer').hidden, true);
assert.equal(element('winner-progress').hidden, false);
assert.equal(element('winner-stage').classList.contains('winner-animate'), false);
assert.match(element('winner-progress').textContent, /CAPTCHA CORRETO.*!nick/);
assert.equal(element('w-name').textContent, 'Ganhador');
context.renderWinnerChat(claimState);
assert.equal(element('winner-chat-card').hidden, false);
assert.equal(element('winner-chat-messages').children.length, 1);
assert.equal(element('winner-chat-messages').children[0].textContent, 'branco');
context.renderBanner(claimState);
assert.equal(element('status-text').textContent, 'AGUARDANDO PERSONAGEM');
context.renderWinnerChat({giveaway: {is_running: true, current_winner: null, winner_chat: null}});
assert.equal(element('winner-chat-card').hidden, true);

// Opção aleatória escolhe uma variante válida a cada NOVO vencedor.
context.renderWinner({giveaway:{is_running:true,current_winner:{...drawn,drawn_at:3},
    winner_deadline:now/1000+50}, appearance:{winner_animation:'random'},participants:[]});
assert.equal(['classic','spotlight','rise','flip','burst'].includes(element('winner-stage').dataset.animation),true);

// Antes da primeira mensagem há só o relógio de presença, sem desafio.
context.renderCaptcha({giveaway: {...base.giveaway, current_winner: winner, captcha: null, winner_deadline: now/1000 + 60}});
assert.equal(element('captcha-layer').hidden, true);

context.renderCaptcha({giveaway: {...base.giveaway, current_winner: winner, captcha: {...challenge, deadline: 0}}});
assert.equal(element('captcha-layer').hidden, false);
assert.equal(element('captcha-countdown-wrap').hidden, true);
assert.match(element('captcha-feedback').textContent, /Presença confirmada/);

context.renderCaptcha({giveaway: {...base.giveaway, current_winner: winner, captcha: challenge}});
assert.equal(element('captcha-layer').hidden, false);
assert.equal(element('captcha-question').textContent, 'Quanto é 12 + 7?');
assert.equal(element('captcha-countdown').textContent, '00:45');
assert.equal(element('captcha-username').textContent, 'Ganhador');

// Erros intermediários não revelam resposta nem trocam de cena.
context.renderCaptcha({giveaway:{...base.giveaway,current_winner:winner,
    captcha:{...challenge,attempts:1,max_attempts:3,deadline:0},
    captcha_feedback:{status:'wrong',attempts:1,max_attempts:3}}});
assert.equal(element('captcha-layer').hidden,false);
assert.match(element('captcha-feedback').textContent,/1\/3.*Restam 2/);
assert.doesNotMatch(element('captcha-feedback').textContent,/A resposta correta era/);
assert.equal(element('captcha-feedback').classList.contains('wrong'),true);
context.renderCaptcha({giveaway:{...base.giveaway,current_winner:winner,
    captcha:{...challenge,attempts:7,max_attempts:0,deadline:0},
    captcha_feedback:{status:'wrong',attempts:7,max_attempts:0}}});
assert.match(element('captcha-feedback').textContent,/7\/∞.*ilimitadas/);

context.renderCaptcha(claimState);
assert.equal(element('captcha-layer').hidden, true);
assert.equal(element('winner-stage').classList.contains('active'), true);

context.renderCaptcha({giveaway: {
    ...base.giveaway, current_winner: {...winner, captcha_failed: true}, captcha: null,
    winner_deadline: 0,
    captcha_feedback: {username: 'Ganhador', platform: 'kick', status: 'wrong', expected: '19'},
}});
assert.equal(element('captcha-feedback').classList.contains('wrong'), true);
assert.equal(element('captcha-countdown-wrap').hidden, true);
assert.equal(element('captcha-card').dataset.result, 'wrong');
assert.match(element('captcha-question').textContent, /19/);

context.renderCaptcha({giveaway: {...base.giveaway, current_winner: winner, captcha: challenge}});

context.renderCaptcha({giveaway: {
    ...base.giveaway, current_winner: null, captcha: null,
    captcha_feedback: {username: 'Ganhador', platform: 'kick', status: 'correct'},
}});
assert.equal(element('captcha-card').dataset.result, 'correct');
assert.equal(element('captcha-layer').hidden, false);
assert.equal(element('captcha-question-wrap').hidden, true);

now += 2600;
context.renderCaptcha({giveaway: {...base.giveaway, current_winner: null, captcha: null}});
assert.equal(element('captcha-layer').hidden, true);

context.renderCaptcha({giveaway: {...base.giveaway, current_winner: winner, captcha: challenge}});
context.renderCaptcha({giveaway: {
    ...base.giveaway, current_winner: null, captcha: null,
    captcha_feedback: {username: 'Ganhador', platform: 'kick', status: 'expired'},
}});
assert.equal(element('captcha-card').dataset.result, 'expired');

context.renderCaptcha({giveaway: {...base.giveaway, current_winner: null, captcha: null}});
// Um novo sorteio nunca pode ficar preso na tela do CAPTCHA anterior.
context.renderCaptcha({giveaway: {...base.giveaway, current_winner: winner, captcha: null}});
assert.equal(element('captcha-layer').hidden, true);

// Consulta de personagem: feedback visível no painel principal, inclusive
// quando o bot ainda consulta ou o nome não é encontrado.
const nickFeedbackBase={...claimState,giveaway:{...claimState.giveaway,
    winner_chat:{...claimState.giveaway.winner_chat,awaiting_nick:true}}};
for(const [status,text] of [['checking','Consultando'],['error','não encontrado'],['waiting','2 segundos']]) {
    context.renderWinner({...nickFeedbackBase,giveaway:{...nickFeedbackBase.giveaway,
        winner_chat:{...nickFeedbackBase.giveaway.winner_chat,
            nick_verification:{status,nick:'DarcheMan',result:text}}}});
    assert.equal(element('winner-nick-result').hidden,false);
    assert.equal(element('winner-nick-result').dataset.status,status);
    assert.equal(element('winner-nick-result-text').textContent,text);
}
const confirmed={...nickFeedbackBase,giveaway:{...nickFeedbackBase.giveaway,
    winner_chat:{...nickFeedbackBase.giveaway.winner_chat,awaiting_nick:false,
        nick_verification:{status:'success',nick:'DarcheMan',result:'Nível 400, RR 120'}}}};
context.renderWinner(confirmed);
context.renderBanner(confirmed);
assert.equal(element('winner-stage').classList.contains('active'),true);
assert.equal(element('winner-nick-result').dataset.status,'success');
assert.equal(element('status-text').textContent,'PERSONAGEM VALIDADO');
assert.match(element('winner-nick-result-text').textContent,/RR 120/);

// A prévia de Identidade Visual reutiliza o código do OBS com participantes
// fictícios; verificar as quatro cenas em vez de mostrar só uma amostra CSS.
context.renderAppearancePreview({mode:'drawing',appearance:{draw_animation:'portal',draw_animation_seconds:4}});
assert.equal(element('draw-suspense-stage').hidden,false);
assert.equal(context.document.body.classList.contains('drawing-solo'),true);
assert.equal(element('draw-suspense-stage').dataset.animation,'portal');
assert.equal(element('winner-stage').classList.contains('active'),false);
assert.match(element('draw-suspense-style').textContent,/PORTAL/);
context.renderAppearancePreview({mode:'winner',appearance:{winner_animation:'rise'}});
assert.equal(element('draw-suspense-stage').hidden,true);
assert.equal(context.document.body.classList.contains('drawing-solo'),false);
assert.equal(element('winner-stage').classList.contains('active'),true);
assert.equal(element('winner-stage').dataset.animation,'rise');
context.renderAppearancePreview({mode:'nick'});
assert.equal(element('winner-stage').classList.contains('active'),true);
assert.equal(element('winner-nick-result').dataset.status,'success');
context.renderAppearancePreview({mode:'collection'});
assert.equal(element('winner-stage').classList.contains('active'),false);
assert.equal(element('status-text').textContent,'COLETA ABERTA');

// O iframe de prévia abre sem conectar WebSocket nem consultar sorteio real.
// Mensagens do painel trocam efetivamente a cena, inclusive um novo sorteio.
const previewDom=new Map();
const previewElement=id=>{
    if(!previewDom.has(id))previewDom.set(id,new FakeElement());
    return previewDom.get(id);
};
let messageHandler=null;
let wsAttempts=0;
let httpAttempts=0;
const previewContext=vm.createContext({
    document:{getElementById:previewElement,createElement:()=>new FakeElement(),
        documentElement:{style:{setProperty(){}}},body:new FakeElement()},
    URLSearchParams,
    Date,
    setInterval:()=>1,clearInterval:()=>{},setTimeout:()=>1,clearTimeout:()=>{},
    console,
    location:{protocol:'http:',host:'localhost:8777',origin:'http://localhost:8777',search:'?preview=1'},
    fetch:()=>{httpAttempts++;return Promise.reject(Error('não buscar dados reais'));},
    WebSocket:class{constructor(){wsAttempts++;}},
    addEventListener:(type,handler)=>{if(type==='message')messageHandler=handler;},
});
previewContext.window=previewContext;
vm.runInContext(drawJs,previewContext,{filename:'preview/draw-animations.js'});
vm.runInContext(js,previewContext,{filename:'preview/app.js'});
assert.equal(previewElement('status-text').textContent,'COLETA ABERTA');
assert.equal(wsAttempts,0);
assert.equal(httpAttempts,0);
assert.equal(typeof messageHandler,'function');
messageHandler({origin:'http://localhost:8777',data:{source:'sorteador-appearance-preview',
    mode:'drawing',appearance:{draw_animation:'cards',draw_animation_seconds:3}}});
assert.equal(previewElement('draw-suspense-stage').hidden,false);
assert.equal(previewElement('draw-suspense-stage').dataset.animation,'cards');
messageHandler({origin:'http://localhost:8777',data:{source:'sorteador-appearance-preview',mode:'nick'}});
assert.equal(previewElement('draw-suspense-stage').hidden,true);
assert.equal(previewElement('winner-stage').classList.contains('active'),true);
assert.equal(previewElement('winner-nick-result').dataset.status,'success');
messageHandler({origin:'https://outro-site.example',data:{source:'sorteador-appearance-preview',mode:'collection'}});
assert.equal(previewElement('winner-stage').classList.contains('active'),true);

console.log('OBS integrado: CAPTCHA, nick, prévia real e animações de sorteio: OK');
