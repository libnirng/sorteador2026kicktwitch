// Ajuda contextual das abas além de Conexões. Não modifica configurações.
(() => {
  'use strict';
  const help = [
    // Sorteio: coleta, elegibilidade e chances.
    {id:'giveaway-keyword', title:'Palavra-chave de inscrição', steps:['Digite o comando que o público deve escrever no chat para participar, por exemplo !sorteio.','A coleta precisa estar iniciada e a plataforma deve aceitar novas entradas.']},
    {id:'giveaway-timer', title:'Prazo de presença do vencedor', steps:['Tempo, em segundos, até o vencedor falar pela primeira vez no chat.','A primeira fala encerra o relógio. Se for marcado para CAPTCHA, o código será gerado só depois disso, sem um segundo contador.']},
    {id:'giveaway-auto-advance', title:'Sortear automaticamente o próximo', steps:['Quando o prazo de resposta terminar sem confirmação, o sorteador poderá avançar sozinho.','Se desativado, a coleta permanece aberta e você decide quando sortear novamente.']},
    {id:'rule-viewers', title:'Permitir participantes comuns', steps:['Ativa ou desativa a participação de viewers sem categoria especial.','Não muda o peso dos inscritos como Sub, VIP ou moderador.']},
    {id:'rule-subs', title:'Permitir inscritos (Subs)', steps:['Define se usuários identificados como Sub podem entrar no sorteio.','O peso específico da categoria é configurado em Chances por plataforma.']},
    {id:'rule-vips', title:'Permitir VIPs', steps:['Permite a participação de pessoas identificadas como VIP.','A chance relativa do VIP pode ser diferente para Twitch e Kick.']},
    {id:'rule-entry-twitch', title:'Aceitar novas entradas pela Twitch', steps:['Desative para interromper somente novas inscrições da Twitch, sem desconectar o chat.','Quem já está na lista continua concorrendo, salvo se estiver inativo.']},
    {id:'rule-entry-kick', title:'Aceitar novas entradas pela Kick', steps:['Desative para interromper somente novas inscrições da Kick, sem desconectar o chat.','Quem já está na lista continua concorrendo, salvo se estiver inativo.']},
    {id:'rule-repeat', title:'Impedir segundo prêmio pelo mesmo nick', steps:['Ativado: quem ganhar numa plataforma também fica bloqueado pelo mesmo nick na outra.','Desativado: Twitch e Kick são tratadas separadamente. Uma nova coleta libera a lista.']},
    {id:'rule-mods-twitch', title:'Moderadores da Twitch', steps:['Permite que moderadores participem da coleta pela Twitch.','Se habilitados, o peso Moderador da Twitch entra no cálculo de chances.']},
    {id:'rule-mods-kick', title:'Moderadores da Kick', steps:['Permite que moderadores participem da coleta pela Kick.','Se habilitados, o peso Moderador da Kick entra no cálculo de chances.']},
    {id:'weight-twitch-sub', title:'Peso do Sub na Twitch', steps:['1 = chance-base; 2 = duas vezes o peso-base; 1,5 = uma vez e meia.','Se o usuário for Sub e VIP, vale apenas o maior peso, não a soma.']},
    {id:'weight-twitch-vip', title:'Peso do VIP na Twitch', steps:['Defina quantas vezes o peso-base um VIP terá na Twitch.','Exemplo: peso 2,5x significa duas vezes e meia o peso de um viewer com 1x.']},
    {id:'weight-twitch-mod', title:'Peso do moderador na Twitch', steps:['Define o peso de moderadores da Twitch quando a entrada deles estiver permitida.','O sistema usa o maior peso entre as categorias da mesma pessoa.']},
    {id:'weight-kick-sub', title:'Peso do Sub na Kick', steps:['Defina um multiplicador para os Subs da Kick; 1x é o valor padrão.','Este valor é independente dos pesos configurados para Twitch.']},
    {id:'weight-kick-vip', title:'Peso do VIP na Kick', steps:['Define quantas vezes o peso-base um VIP da Kick recebe.','Se for Sub e VIP, somente o maior multiplicador é utilizado.']},
    {id:'weight-kick-mod', title:'Peso do moderador na Kick', steps:['Define o peso para moderadores da Kick, caso possam participar.','Não é porcentagem; a chance real é calculada pela soma dos pesos ativos.']},
    {id:'viewer-skip-enabled', title:'Desistência pelo chat', steps:['Permite que apenas o vencedor atual abra mão do prêmio com o comando configurado.','A desistência fica registrada e respeita o limite definido para a coleta.']},
    {id:'viewer-skip-command', title:'Comando para desistir', steps:['Escolha o texto que o vencedor digitará no chat; o padrão é !pular.','Use um comando iniciado por ! e diferente dos outros comandos do sorteador.']},
    {id:'viewer-skip-limit', title:'Máximo de desistências', steps:['Quantidade total de vezes que a desistência voluntária pode ser usada em cada coleta.','Exemplo: 3 permite três desistências na mesma coleta; ao iniciar outra, o contador recomeça.']},
    {id:'viewer-nick-enabled', title:'Consulta pública MegaMu', steps:['Permite consultar o personagem de MegaMu por comando no chat.','O bot precisa estar autorizado a enviar mensagens na plataforma.']},
    {id:'viewer-nick-command', title:'Comando de personagem', steps:['O padrão é !nick. Para pesquisar, a pessoa digita !nick NomeDoPersonagem.','O bot consulta MegaMu e responde com os dados encontrados ou informa que não existe.']},
    {id:'viewer-rank-enabled', title:'Consulta ao histórico de vencedores', steps:['Permite consultar a contagem histórica de prêmios, respostas e prazos perdidos.','O comando busca no histórico salvo daquela plataforma.']},
    {id:'viewer-rank-command', title:'Comando de histórico', steps:['O padrão é !rank para consultar o próprio histórico.','Também é possível usar !rank OutroNick para consultar outro participante da mesma plataforma.']},

    // Participantes e probabilidades.
    {selector:'[data-panel="participants"] .page-head h1', title:'Participantes, pesos e chance real', steps:['Clique no nick ou no status para tirar temporariamente uma pessoa do sorteio; clique novamente para reativar. A ação fica na auditoria.','Peso é o multiplicador da pessoa. Chance real é o peso dividido pela soma dos pesos ativos: 2 em um total de 10 = 20%.','Pessoas inativas continuam listadas, mas não concorrem.']},

    // Roleta e seus overlays.
    {selector:'[data-panel="roleta"] h2', title:'Peso dos prêmios da roleta', steps:['Peso relativo não precisa somar 100. O sistema normaliza os pesos ativos automaticamente.','Exemplo: pesos 45 e 5 somam 50 e geram chances de 90% e 10%.','Cada item precisa estar ativo para participar. Clique em Salvar tudo depois de ajustar.']},
    {id:'roleta-duration', title:'Duração do giro', steps:['Define quantos segundos a animação da roleta demora para parar.','É apenas visual: não muda o resultado escolhido nem a quantidade de prêmios.']},
    {id:'roleta-spins', title:'Voltas extras na animação', steps:['Quantidade de voltas visuais antes de parar no prêmio.','Não concede giros nem prêmios adicionais.']},
    {id:'roleta-equal-slices', title:'Fatias iguais ou proporcionais', steps:['Ativado: fatias da mesma largura, independentemente do peso.','Desativado: a apresentação pode refletir pesos diferentes. A escolha real continua baseada no peso do prêmio.']},
    {id:'roleta-auto-hide', title:'Ocultar overlay automaticamente', steps:['Após mostrar o resultado pelo tempo configurado, o overlay desaparece do OBS.','Desativado: você poderá usar o botão Ocultar quando quiser.']},
    {id:'roleta-result-seconds', title:'Tempo de exibição do prêmio', steps:['Quantidade de segundos em que cada resultado fica visível depois do giro.','Não é o tempo de animação da roda; ele é configurado separadamente.']},
    {id:'roleta-announce-chat', title:'Anunciar prêmio no chat', steps:['Envia nick e prêmio automaticamente quando o giro termina, se a plataforma estiver autorizada.','Giros de teste não enviam mensagens. Você pode mudar o texto na aba Mensagens.']},
    {id:'roleta-nick', title:'Nick que receberá os prêmios', steps:['Digite o nick do ganhador para associar os giros ao histórico da pessoa.','Para um giro apenas demonstrativo, marque Giro de teste.']},
    {id:'roleta-mode-teste', title:'Giro de teste', steps:['Use para apresentar a animação sem associar o resultado a um nick.','Giros de teste não disparam anúncios de prêmio no chat.']},
    {id:'roleta-attempts', title:'Quantidade de prêmios do nick', steps:['Exemplo: 3 executa três giros seguidos para o mesmo nick.','Um mesmo prêmio pode ser sorteado mais de uma vez; Ocultar cancela os giros restantes.']},

    // Desafio anti-bot integrado.
    {id:'antibot-enabled', title:'Marcação para CAPTCHA', steps:['Quando ativado, cada nova inscrição elegível tem a chance configurada de ser marcada.','Só quem for marcado e depois sorteado recebe um CAPTCHA; a marcação não significa que seja bot.']},
    {id:'antibot-waive', title:'Isenção de Subs e VIPs', steps:['Se ativado, novas inscrições de Subs e VIPs não são selecionadas para CAPTCHA.','A regra vale para inscrições futuras, sem apagar marcações já feitas.']},
    {id:'antibot-chance', title:'Chance de marcação no CAPTCHA', steps:['Percentual independente aplicado uma vez a cada inscrição elegível.','0% não marca ninguém; 100% marca todos os elegíveis. 50% não garante que exatamente metade da lista seja marcada.']},
    {id:'antibot-timer', title:'Prazo para confirmar presença', steps:['Usa o tempo definido na aba Sorteio para a primeira mensagem do vencedor.','Quando ele fala, o relógio para e só então aparece o código, sem outra contagem.']},
    {id:'antibot-send-chat', title:'Enviar desafio no chat', steps:['Quando a pessoa marcada vencer, o bot aguarda a primeira fala dela; só depois anuncia o código.','É preciso habilitar anúncios e autorizar a permissão de envio em Conexões.','O overlay integrado mostra o CAPTCHA sobre o sorteador escurecido.']},
    {selector:'#antibot-current-card h2', title:'Decisão manual após erro no código', steps:['Se a pessoa errar o CAPTCHA, o cronômetro continua parado e o vencedor aguarda sua decisão.','Na mesma caixa, você pode confirmar o prêmio por exceção, gerar novo código ou pular o vencedor.']},

    // Preferências de chat.
    {id:'twitch-chat-scope', title:'Filtro dos chats da Twitch', steps:['Só meu canal mostra mensagens do canal conectado.','Toda a colab inclui mensagens de canais da sessão compartilhada; Canais específicos permite escolher alguns.','O filtro muda a visualização, não a inscrição do sorteio.']},
    {id:'twitch-always-mentions', title:'Sempre mostrar menções', steps:['Exibe suas @menções mesmo quando o canal de origem estiver oculto pelo filtro da colab.','Não altera o funcionamento dos comandos do sorteio.']},
    {id:'twitch-only-mentions', title:'Mostrar só @menções na Twitch', steps:['Filtra a lista de mensagens visíveis para mostrar apenas menções.','O bot continua acompanhando inscrições normalmente.']},
    {id:'kick-only-mentions', title:'Mostrar só @menções na Kick', steps:['Filtra a visualização para mensagens que mencionem a conta.','Não desativa o recebimento de inscrições pelo chat Kick.']},
    {id:'chat-mention-names', title:'Nicks reconhecidos como menção', steps:['Inclua outros nomes que devem gerar alerta de @menção, separados por vírgula.','Seu canal e a conta conectada já são considerados automaticamente.']},
    {id:'chat-sound-volume', title:'Volume dos alertas de chat', steps:['Controla o volume dos avisos sonoros deste navegador.','Clique em Ativar / testar som para liberar o áudio antes de iniciar a live.']},

    // Modelos de mensagem, auditoria, aparência e OBS.
    {selector:'[data-panel="messages"] .page-head h1', title:'Personalização das mensagens do bot', steps:['Abra cada evento, marque Anunciar este evento e escolha Twitch e/ou Kick.','Edite o texto usando variáveis, como {nome}, {premio}, {peso}, {chance} e {tempo}.','Para !rank: {nick}, {total}, {respondeu}, {mamou}, {desistiu}. Salvar não envia mensagem de teste.']},
    {selector:'[data-panel="history"] .page-head h1', title:'Consultar histórico', steps:['Escolha Vencedores, Giros ou Auditoria e aplique os filtros para localizar registros antigos.','Exportar CSV baixa os registros para abrir em uma planilha; não apaga o banco.']},
    {selector:'[data-panel="audit"] > h2', title:'O que é Fairness?', steps:['Mostra métricas para acompanhar a distribuição dos resultados: vencedores únicos, repetidos e plataformas.','Os números ajudam a auditar tendências, mas não substituem a análise de pesos e regras em cada sorteio.']},
    {id:'audit-filter', title:'Filtro de eventos da auditoria', steps:['Digite um nome de ação registrada para encontrar eventos relacionados, como draw_winner ou captcha_issued.','É uma consulta ao histórico: não altera sorteios nem participantes.']},
    {id:'ap-wheel_size', title:'Tamanho da roda do overlay', steps:['Define o diâmetro visual da roleta em pixels.','Se ficar cortada no OBS, confira também a resolução da Fonte do Navegador.']},
    {id:'ap-winner_font_size', title:'Tamanho do nome vencedor', steps:['Controla o tamanho da fonte usada para destacar o vencedor no overlay.','Ajuste e confira a prévia para nomes muito longos.']},
    {id:'ap-show_prize_list', title:'Mostrar lista de prêmios', steps:['Exibe os prêmios no overlay da roleta durante a apresentação.','Desative se quiser uma tela mais limpa.']},
    {id:'ap-show_chances_overlay', title:'Exibir porcentagens no overlay', steps:['Mostra as probabilidades dos prêmios na lista visível do overlay.','As chances reais são calculadas pelos pesos ativos, independentemente desta opção visual.']},
    {selector:'[data-panel="obs"] .links-list li:nth-child(1) strong', title:'Overlay principal do sorteio', steps:['No OBS, adicione uma Fonte do Navegador e cole a URL do Sorteio.', 'Use 1920×1080 e mantenha a fonte carregada, mesmo quando não estiver visível.', 'O CAPTCHA integrado aparece sobre este overlay, escurecendo o sorteador ao fundo.'],url:'https://obsproject.com/kb/Browser-Source',link:'Guia oficial OBS'},
    {selector:'[data-panel="obs"] .links-list li:nth-child(2) strong', title:'Overlay de roleta', steps:['Adicione uma Fonte do Navegador separada com esta URL para mostrar os giros.','Deixe “Desligar fonte quando não estiver visível” desmarcado para evitar recarregamentos ao trocar de cena.'],url:'https://obsproject.com/kb/Browser-Source',link:'Guia oficial OBS'},
    {selector:'[data-panel="obs"] .links-list li:nth-child(3) strong', title:'Overlay de CAPTCHA separado', steps:['Este link permite uma fonte dedicada ao CAPTCHA, se você quiser posicioná-lo em outra cena.', 'Para o efeito centralizado sobre o sorteador escurecido, basta usar o overlay principal de Sorteio.', 'Evite exibir os dois CAPTCHA ao mesmo tempo.']}
  ];

  function makeTooltip(item) {
    const container = document.createElement('span');
    container.className = 'connection-field-help option-field-help';
    const trigger = document.createElement('span');
    trigger.className = 'connection-help-trigger';
    trigger.textContent = '?';
    trigger.tabIndex = 0;
    trigger.setAttribute('role', 'button');
    trigger.setAttribute('aria-label', 'Ajuda: ' + item.title);
    trigger.setAttribute('aria-expanded', 'false');
    const popup = document.createElement('span');
    popup.className = 'connection-help-popup';
    popup.setAttribute('role', 'tooltip');
    const title = document.createElement('strong');
    title.textContent = item.title;
    const list = document.createElement('ol');
    for (const step of item.steps) {
      const li = document.createElement('li');
      li.textContent = step;
      list.appendChild(li);
    }
    popup.append(title, list);
    if (item.url) {
      const link = document.createElement('a');
      link.href = item.url;
      link.target = '_blank';
      link.rel = 'noopener noreferrer';
      link.textContent = (item.link || 'Ver referência') + ' ↗';
      popup.appendChild(link);
    }
    popup.id = 'option-help-' + (item.id || item.title.toLowerCase().replace(/[^a-z0-9]+/g, '-'));
    trigger.setAttribute('aria-describedby', popup.id);
    container.append(trigger, popup);

    const show = state => {
      container.classList.toggle('is-open', state);
      trigger.setAttribute('aria-expanded', String(state));
    };
    trigger.addEventListener('click', event => {
      event.preventDefault();
      event.stopPropagation();
      const next = !container.classList.contains('is-open');
      document.querySelectorAll('.option-field-help.is-open').forEach(other => {
        other.classList.remove('is-open');
        other.querySelector('.connection-help-trigger')?.setAttribute('aria-expanded', 'false');
      });
      show(next);
    });
    trigger.addEventListener('keydown', event => {
      if (event.key === 'Enter' || event.key === ' ') {
        event.preventDefault();
        trigger.click();
      } else if (event.key === 'Escape') {
        show(false);
        trigger.blur();
      }
    });
    container.addEventListener('click', event => event.stopPropagation());
    return container;
  }

  function attach(item) {
    const field = item.id ? document.getElementById(item.id) : null;
    let anchor = item.selector ? document.querySelector(item.selector) : null;
    if (!anchor && field) {
      const label = field.closest('label');
      if (label?.classList.contains('switch')) {
        const row = label.closest('.switch-row');
        anchor = row?.querySelector('label[for], label.label, :scope > span, :scope > div') || null;
      } else if (label && !label.classList.contains('sr-only')) {
        anchor = label;
      }
    }
    if (!anchor || anchor.querySelector('.option-field-help')) return false;
    anchor.classList.add('has-option-help');
    const tip = makeTooltip(item);
    const textNode = [...anchor.childNodes].find(node => node.nodeType === 3 && node.textContent.trim());
    if (anchor.tagName === 'LABEL' && textNode) {
      const caption = document.createElement('span');
      caption.className = 'connection-field-caption';
      caption.textContent = textNode.textContent.trim();
      caption.appendChild(tip);
      anchor.replaceChild(caption, textNode);
    } else {
      anchor.appendChild(tip);
    }
    return true;
  }

  for (const item of help) attach(item);
  document.addEventListener('click', () => {
    document.querySelectorAll('.option-field-help.is-open').forEach(container => {
      container.classList.remove('is-open');
      const trigger = container.querySelector('.connection-help-trigger');
      trigger?.setAttribute('aria-expanded', 'false');
      trigger?.blur();
    });
  });

  // Abre para cima ou para a esquerda quando faltar espaço na janela.
  // Funciona também para os 17 balões de ajuda existentes em Conexões.
  function fitPopup(event) {
    const parent = event.target.closest?.('.connection-field-help');
    if (!parent) return;
    const popup = parent.querySelector('.connection-help-popup');
    if (!popup) return;
    parent.classList.remove('help-open-up', 'help-align-right', 'help-align-start');
    const rect = parent.getBoundingClientRect();
    let bounds = popup.getBoundingClientRect();
    if (bounds.left < 12) parent.classList.add('help-align-start');
    else if (bounds.right > window.innerWidth - 12) parent.classList.add('help-align-right');
    bounds = popup.getBoundingClientRect();
    if (bounds.bottom > window.innerHeight - 12 && rect.top > bounds.height + 12)
      parent.classList.add('help-open-up');
  }
  document.addEventListener('mouseover', fitPopup, true);
  document.addEventListener('focusin', fitPopup, true);
})();
