// Ajuda contextual para os campos de Conexões.
// Não lê credenciais, não faz requisições e não altera valores dos formulários.
(() => {
  'use strict';

  const guides = {
    'twitch-channel': {
      title: 'Canal da Twitch',
      steps: ['Abra seu canal na Twitch.', 'Copie somente o nome depois de twitch.tv/ (sem @, barras ou URL).', 'Exemplo: twitch.tv/darcherman → darcherman.'],
      url: 'https://www.twitch.tv/', link: 'Abrir Twitch'
    },
    'twitch-client-id': {
      title: 'Client ID da Twitch',
      steps: ['É o identificador do aplicativo usado para gerar seu token, não o nome do canal.', 'Na Twitch Developer Console, abra Aplicações → Gerenciar → Client ID.', 'Se já possui um token, use “Verificar token e preencher Client ID” logo abaixo. O ID precisa corresponder ao token.'],
      url: 'https://dev.twitch.tv/console/apps', link: 'Console de desenvolvedor'
    },
    'twitch-helix-token': {
      title: 'User Access Token da Twitch',
      steps: ['Autorize sua conta Twitch para o aplicativo correspondente ao Client ID.', 'O token precisa de user:read:chat para ler e user:write:chat para enviar mensagens.', 'Cole somente o Access Token. É uma credencial privada: não envie em prints ou no chat.'],
      url: 'https://dev.twitch.tv/docs/chat/authenticating', link: 'Guia oficial de autenticação'
    },
    'kick-receive-channel': {
      title: 'Canal da Kick',
      steps: ['Abra o canal desejado em kick.com.', 'Copie apenas o nome que aparece após kick.com/.', 'Exemplo: kick.com/darcherman → darcherman. Para somente receber chat no modo direto, não precisa criar aplicativo.'],
      url: 'https://kick.com/', link: 'Abrir Kick'
    },
    'kick-receive-mode': {
      title: 'Modo de recepção do chat',
      steps: ['Conexão direta: recomendada para começar; recebe chat sem OAuth ou ngrok.', 'Webhooks: alternativa que exige aplicativo Kick, autorização OAuth, URL pública e assinatura de eventos.', 'Deixe “Conexão direta” se não sabe qual escolher.']
    },
    'kick-receive-room': {
      title: 'ID da sala de chat da Kick',
      steps: ['Opcional: normalmente o programa detecta sozinho.', 'Se a detecção falhar, abra kick.com/api/v1/channels/SEU_CANAL e procure o valor numérico chatroom.id.', 'Não confunda com o Client ID do aplicativo. Se a página não abrir, deixe o campo vazio.']
    },
    'kick-receive-channel-id': {
      title: 'ID numérico do canal Kick',
      steps: ['Opcional: normalmente o programa detecta sozinho.', 'Se precisar preencher, consulte kick.com/api/v1/channels/SEU_CANAL e procure o campo id do canal.', 'Não use o nick, o ID da sala ou o Client ID do aplicativo.']
    },
    'kick-client-id': {
      title: 'Client ID do aplicativo Kick',
      steps: ['Faça login na Kick e acesse Configurações → Desenvolvedor.', 'Crie ou abra seu aplicativo e copie o Client ID.', 'Este ID identifica o aplicativo usado para autorizar o envio de mensagens; não é o nick nem o ID numérico do canal.'],
      url: 'https://kick.com/settings/developer', link: 'Abrir aplicativos Kick'
    },
    'kick-redirect-uri': {
      title: 'Redirect URI da Kick',
      steps: ['É o endereço local para onde a Kick retorna após a autorização.', 'Use http://localhost:8777/api/oauth/kick/callback quando o servidor usar a porta padrão.', 'Cadastre exatamente a mesma URL nas configurações do aplicativo Kick; não é um token.'],
      url: 'https://docs.kick.com/llms.txt', link: 'Documentação Kick'
    },
    'kick-client-secret': {
      title: 'Client Secret da Kick',
      steps: ['No mesmo aplicativo Kick do Client ID, localize o Client Secret nas configurações de desenvolvedor.', 'Copie o segredo do aplicativo e cole aqui para autorizar a conta.', 'Mantenha em sigilo: deixe vazio quando já estiver salvo e não compartilhe seu .env.'],
      url: 'https://kick.com/settings/developer', link: 'Abrir aplicativos Kick'
    },
    'megamu-dv': {
      title: 'Identificação DV da MegaMu',
      steps: ['Entre na sua conta em megamu.net.', 'Abra Minha conta → DV Panel (painel de streamer/parceiro).', 'Informe o login/identificador DV associado a esse painel, não o nick de um personagem. O acesso ao DV depende da habilitação da MegaMu.'],
      url: 'https://megamu.net/panel/dv', link: 'Abrir painel DV'
    },
    'megamu-key': {
      title: 'Chave da API MegaMu',
      steps: ['No site da MegaMu, abra Minha conta → DV Panel → aba API.', 'Use a opção de gerar/copiar a chave do seu DV e cole neste campo.', 'A chave é privada. Se já está salva, deixe vazio para mantê-la; teste pelo botão “Consultar prêmios”.'],
      url: 'https://megamu.net/panel/dv', link: 'Abrir painel DV'
    },
    'bot-send-twitch': {
      title: 'Anúncios automáticos na Twitch',
      steps: ['Ative para o bot divulgar sorteios e resultados no chat Twitch.', 'O token precisa da permissão user:write:chat.', 'Os textos e eventos podem ser personalizados na aba Mensagens.']
    },
    'bot-send-kick': {
      title: 'Anúncios automáticos na Kick',
      steps: ['Ative para o bot enviar mensagens de sorteio e resultados no chat Kick.', 'Para enviar, autorize o aplicativo Kick com uma conta que tenha permissão chat:write.', 'Receber chat pelo modo direto funciona mesmo com esta opção desligada.']
    },
    'kick-receive-autostart': {
      title: 'Reconectar a Kick automaticamente',
      steps: ['Com esta opção ativada, o servidor tenta reconectar a recepção do chat Kick ao iniciar.', 'Salve o canal e o modo de recepção para que a configuração fique no .env.']
    },
    'megamu-enabled': {
      title: 'Catálogo de prêmios da MegaMu',
      steps: ['Ative depois de informar o DV e a chave da API.', 'O sorteador consulta os prêmios disponíveis na MegaMu e os exibe no overlay.', 'Use “Consultar prêmios” para verificar se a integração responde.']
    },
    'env-real-mode': {
      title: 'Conexões reais ou simulação',
      steps: ['Ativado: o programa usa as conexões reais configuradas para Twitch e Kick.', 'Desativado: permanece no modo de simulação para testes.', 'Salve o modo no .env usando o botão ao lado.']
    }
  };

  let serial = 0;
  function buildHelp(fieldId, guide) {
    const field = document.getElementById(fieldId);
    const label = field?.closest('label');
    if (!field || !label || !label.closest('[data-panel="connections"]')) return;

    const isCheckbox = field.type === 'checkbox';
    const help = document.createElement('span');
    help.className = 'connection-field-help';
    const trigger = document.createElement('span');
    trigger.className = 'connection-help-trigger';
    trigger.textContent = '?';
    trigger.setAttribute('role', 'button');
    trigger.setAttribute('tabindex', '0');
    trigger.setAttribute('aria-label', 'Como obter ou configurar: ' + guide.title);
    trigger.setAttribute('aria-expanded', 'false');
    const popup = document.createElement('span');
    popup.className = 'connection-help-popup';
    popup.id = 'connection-help-' + (++serial);
    popup.setAttribute('role', 'tooltip');
    trigger.setAttribute('aria-describedby', popup.id);
    const heading = document.createElement('strong');
    heading.textContent = guide.title;
    popup.appendChild(heading);
    const steps = document.createElement('ol');
    for (const step of guide.steps) {
      const item = document.createElement('li');
      item.textContent = step;
      steps.appendChild(item);
    }
    popup.appendChild(steps);
    if (guide.url) {
      const link = document.createElement('a');
      link.href = guide.url;
      link.target = '_blank';
      link.rel = 'noopener noreferrer';
      link.textContent = (guide.link || 'Ver referência') + ' ↗';
      popup.appendChild(link);
    }
    help.append(trigger, popup);

    // Os rótulos com input usam texto simples antes do campo.
    // Preservamos o próprio <label>, para não afetar salvamento ou seleção.
    const titleText = [...label.childNodes].find(node => node.nodeType === 3 && node.textContent.trim());
    if (!isCheckbox && titleText) {
      const caption = document.createElement('span');
      caption.className = 'connection-field-caption';
      caption.textContent = titleText.textContent.trim();
      caption.appendChild(help);
      label.replaceChild(caption, titleText);
    } else {
      label.appendChild(help);
    }

    const setOpen = open => {
      help.classList.toggle('is-open', open);
      trigger.setAttribute('aria-expanded', String(open));
    };
    trigger.addEventListener('click', event => {
      event.preventDefault();
      event.stopPropagation();
      const willOpen = !help.classList.contains('is-open');
      document.querySelectorAll('.connection-field-help.is-open').forEach(other => {
        if (other !== help) {
          other.classList.remove('is-open');
          other.querySelector('.connection-help-trigger')?.setAttribute('aria-expanded', 'false');
        }
      });
      setOpen(willOpen);
    });
    trigger.addEventListener('keydown', event => {
      if (event.key === 'Enter' || event.key === ' ') {
        event.preventDefault();
        trigger.click();
      }
      if (event.key === 'Escape') {
        setOpen(false);
        trigger.blur();
      }
    });
    help.addEventListener('click', event => event.stopPropagation());
  }

  for (const [fieldId, guide] of Object.entries(guides)) buildHelp(fieldId, guide);
  document.addEventListener('click', () => {
    document.querySelectorAll('.connection-field-help.is-open').forEach(help => {
      help.classList.remove('is-open');
      const trigger = help.querySelector('.connection-help-trigger');
      trigger?.setAttribute('aria-expanded', 'false');
      trigger?.blur();
    });
  });
})();
