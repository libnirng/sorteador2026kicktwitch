# Sorteador Geral — atualização

## Atualização v27 — nomes dos participantes dentro das dez animações

- **Roleta de participantes:** as fatias agora exibem os **nicks da Twitch/Kick**. Com até dez inscritos elegíveis, todos ficam no mesmo disco. Com mais de dez, o efeito usa grupos de até dez nomes para preservar a leitura. O vencedor já escolhido pelo servidor é mantido no disco e, na desaceleração final, a seta aponta para a sua fatia antes da revelação; não há um segundo sorteio no navegador.
- **Outras nove animações:** caça-níquel mostra nicks nos três visores; contagem regressiva tem nomes associados ao número; cartas, dados, radar, baú, partículas, portal e holofotes também exibem os nomes **integrados ao próprio efeito**. A lista gira durante o suspense, para abranger participantes diferentes.
- **OBS em destaque:** o efeito continua centralizado em tela cheia, sem painel de participantes/prêmios, sem sobreposição do chat e sem o vencedor anunciado antes da hora. Os únicos nomes mostrados são aqueles que fazem parte da própria animação.
- **Prévia no painel:** em **Identidade visual → Animação durante o sorteio → Testar animação**, são usados nomes fictícios ilustrativos; a fonte OBS utiliza inscritos reais. A seleção **Aleatória** permanece disponível e escolhe um dos dez efeitos por vencedor.
- **Atualização da versão:** reinicie o aplicativo, dê `Ctrl+F5` no painel e recarregue a fonte de navegador do OBS; os arquivos visuais agora estão com identificador `v=27-nomes`. Preserve os diretórios `dados`, `.venv` e o `.env` existentes ao trocar os arquivos.
- **Verificação:** testes automatizados de nomes nos dez efeitos, páginas da roleta, elegibilidade de participantes e alinhamento com o resultado escolhido. A apresentação ao vivo na Twitch/Kick e a renderização dentro do OBS precisam ser confirmadas no computador com o sorteador instalado.

## Atualização v26 — CAPTCHA com tentativas configuráveis e suspense em tela cheia

- **Número de tentativas:** em **Anti-bot → Desafio do vencedor marcado → Máximo de tentativas do CAPTCHA**, escolha qualquer número de **0 a 100**. O padrão é **3**; **0 significa ilimitadas**. Clique em **Salvar configuração**. A escolha é guardada para a próxima abertura e aplicada a cada novo desafio (não altera um desafio já iniciado).
- **Após um erro:** o bot diz `❌ Resposta incorreta. Tentativa 1/3. Tente novamente.` e o CAPTCHA permanece ativo no OBS, com a pergunta original e as tentativas restantes. A primeira mensagem já parou o cronômetro de presença; os erros não o reiniciam nem abrem outra contagem.
- **Acertou dentro do limite:** prêmio confirmado e segue para o pedido de personagem (`!nick` ou `!NomeDoPersonagem`) como antes. **Acabaram as tentativas:** aí, e somente aí, o bot revela a resposta correta, marca o desafio como falho e aguarda o organizador confirmar manualmente, gerar outro desafio ou pular o vencedor.
- **Zero = infinito:** não revela a solução depois de uma quantidade arbitrária de erros; permite continuar tentando até acertar ou intervenção manual. A página pública do OBS nunca recebe a resposta correta durante as tentativas disponíveis.
- **Mensagens personalizáveis:** evento novo **Captcha incorreto: nova tentativa** (`captcha_retry`) com campos `{nome}`, `{tentativa}`, `{limite}`, `{restantes}` (o limite zero aparece como `∞`). O evento anterior **Captcha incorreto: tentativas esgotadas** (`captcha_fail`) continua sendo usado no último erro e pode mostrar `{resposta}`. É possível ativar/desativar e personalizar cada um por Twitch ou Kick.
- **Animação limpa:** ao clicar em **Sortear**, o efeito de suspense **cobre a tela inteira, centralizado e sem nome de participantes, banner, prêmios, legendas ou contagem visual**; aparecem apenas seus gráficos animados. Terminada a duração configurada, volta ao layout normal com o vencedor. A prévia da Identidade Visual segue essa regra.
- **Cache:** a fonte principal do OBS e os scripts do painel estão com versão visual `v=26-captcha`. Depois de atualizar os arquivos, reinicie o Sorteador, use `Ctrl+F5` no painel e recarregue a fonte de navegador no OBS.
- **Verificação local:** testes para limites **1, 3 e 0 ilimitado**, persistência, mensagem a cada erro, não divulgação antecipada da solução e modo de animação isolado. A confirmação com mensagens reais da Kick/Twitch deve ser feita no computador conectado.

## Atualização v25 — consulta do nick, prévia OBS e animações verificáveis

- **Comando enviado com exclamação:** enquanto o vencedor estiver aguardando o personagem, os dois formatos funcionam no chat da plataforma dele: `!nick darcherman` **ou** `!darcherman`. O segundo formato antes era ignorado. Comandos reservados e a palavra-chave do sorteio continuam separados.
- **Resposta na tela e no chat:** depois do comando, o painel central do vencedor exibe **Consultando MEGAMU**, **Personagem não encontrado** ou **Personagem encontrado**, com o retorno da consulta. O bot também envia o resultado no chat, se o envio estiver ligado. Um erro permite tentar novamente; o nome validado permanece **12 segundos** no OBS com os detalhes e depois a tela volta à coleta. Não é necessário mudar de cena no OBS.
- **Diagnóstico de envio:** na aba Sorteio do painel, o campo **Verificação do personagem** informa o resultado da consulta e, separadamente, se a mensagem foi efetivamente enviada ao chat da Twitch/Kick. Se o bot não estiver autorizado, o anúncio estiver desligado ou houver falha, mostra o motivo; assim não fica um silêncio sem explicação.
- **Prévia real da aparência:** na aba **Identidade visual**, há agora um quadro com **o próprio overlay do OBS**, usando dados fictícios. Selecione **Coleta aberta**, **Sorteando**, **Vencedor** ou **Personagem confirmado** e clique em **Atualizar prévia**. O modo **Sorteando** executa o suspense selecionado (incluindo **Aleatória**). Alterações de cores e animações aparecem no quadro; clique em **Salvar aparência** para gravar para as transmissões.
- **Animações durante o sorteio:** o cronômetro e anúncio começam após o suspense. O intervalo do efeito é contado **depois das gravações no banco de dados**, evitando que uma gravação lenta consuma a animação antes de o OBS recebê-la. O painel mostra o efeito ativo e os segundos restantes. Estilos diferentes mostram nomes e elementos gráficos diferentes no OBS.
- **Cache:** versões dos arquivos de CSS/JS da fonte OBS e do painel alteradas para `v=25-nick-preview`. Depois de instalar, **feche o servidor anterior, reinicie, aperte Ctrl+F5 no admin e recarregue a fonte do OBS** para garantir que o navegador da transmissão utilize o código novo.
- **Testes executados:** testes locais de lógica do CAPTCHA, consulta de nick, anúncios, suspense, dez estilos, opção aleatória, prévia das quatro cenas e envio de mensagens do painel para o iframe. **Kick, Twitch e a API MEGAMU reais não foram consultados ao vivo neste ambiente**; confirme no chat conectado antes da transmissão.

## Atualização v24 — sorteio com animação aleatória

- Em **Aparência → Animação ao clicar em Sortear**, escolha **🎲 Aleatória — muda a cada vencedor**.
- O sorteador escolhe automaticamente uma das **10 animações de suspense** antes de revelar cada vencedor. **Não repete a mesma animação do sorteio anterior**; as dez continuam disponíveis individualmente.
- A escolha é feita uma única vez no servidor, por vencedor. Assim, todas as fontes do OBS mostram o **mesmo efeito**, mesmo após reconexões e atualizações.
- O botão **Testar animação de sorteio** também escolhe um novo efeito a cada clique na opção Aleatória, sem repetir o anterior.
- O comportamento da v23 foi mantido: cronômetro e anúncio no chat só começam após a animação terminar. Nenhuma alteração nas mensagens personalizadas, CAPTCHA ou `!nick`.

## Atualização v23 — 10 animações de sorteio ANTES de revelar o vencedor

- **Clique em Sortear → suspense → vencedor:** o servidor escolhe o ganhador imediatamente, mas no OBS exibe primeiro a animação selecionada, sem revelar seu nome, avatar ou a indicação de sorteado nos participantes. Terminada a animação, surge a tela principal do vencedor com a animação de entrada escolhida separadamente.
- **Dez estilos:** **Roleta giratória**, **Caça-níquel**, **Contagem 3–2–1**, **Cartas embaralhando**, **Dados rolando**, **Radar**, **Baú misterioso**, **Chuva de estrelas**, **Portal mágico** e **Holofotes cruzados**. A opção **Sem animação** também está disponível.
- **Configuração no admin:** entre em **Aparência → Animação ao clicar em Sortear** e escolha a opção e a duração de **2 a 10 segundos**. Clique em **Testar animação de sorteio** para ver uma prévia sem fazer um sorteio real. Depois clique em **Salvar aparência**. A prévia da **entrada do vencedor** continua logo abaixo, independente.
- **Cronômetro justo:** os 60 segundos (ou o prazo configurado) começam **somente depois da revelação**, com o anúncio de vencedor no chat. Mensagens enviadas pelo ganhador durante o suspense não confirmam presença nem disparam o CAPTCHA. O suspense também vale para novos sorteios após um vencedor expirar ou ser pulado.
- **Cancelamento:** iniciar/resetar/encerrar sorteio ou pular um vencedor durante o suspense cancela a revelação pendente. A transição mantém a mesma fonte de navegador no OBS.
- **Cache e atualização:** atualize os arquivos preservando `.env`, `.venv` e `dados`; reinicie o servidor e recarregue a fonte do OBS. Recursos estáticos da cena usam a versão `v=23`.
- **Testes locais:** `python -B tests/verify_two_phase_captcha.py` e `node tests/captcha_integrado.test.cjs` verificam a ordem suspense/revelação, o prazo integral, a não confirmação precoce, a persistência das opções e as correções do CAPTCHA/`!nick`.

## Atualização v22 — vencedor em destaque e animações escolhidas pelo cliente

- **Nome sem duplicação:** no OBS, o nome, avatar e plataforma aparecem apenas na tela central de vencedor. O painel complementar ficou menor, integrado ao destaque e mostra somente a **última mensagem** do vencedor, sem repetir sua identidade nem empilhar todas as mensagens anteriores.
- **Após o CAPTCHA:** ao acertar, a tela principal com o vencedor volta imediatamente e permanece em destaque. O cronômetro some e aparece uma faixa discreta **`✅ CAPTCHA CORRETO · ENVIE !nick NomeDoPersonagem`**. A tela separada de confirmação não substitui esse destaque; o mini-painel do chat continua abaixo.
- **Limpeza preservada:** quando o prazo de presença acaba, ao pular, ao encerrar, ao receber um `!nick` válido ou ao iniciar o próximo vencedor, o destaque e o painel complementar são atualizados/ocultados pelo estado do servidor, sem ressuscitar mensagens antigas.
- **Seis opções de entrada:** em **Aparência → Animação de entrada do vencedor**, escolha **Clássica**, **Holofote**, **Ascensão**, **Giro 3D**, **Explosão** ou **Aleatória**. Um botão reproduz a prévia sem executar sorteios. **Salvar aparência** grava a escolha e o overlay do OBS a utiliza na próxima revelação. A opção **Aleatória** sorteia um dos cinco estilos a cada novo vencedor.
- **Sem reiniciar animação:** o efeito de entrada é disparado quando um novo vencedor é escolhido, não a cada mensagem ou atualização do WebSocket. Ao confirmar o CAPTCHA, o vencedor já revelado permanece estável.
- **Atualização:** pare o servidor, substitua os arquivos do pacote e preserve `.env`, `.venv` e `dados`. Reinicie; atualize o painel (`Ctrl+F5`) e a fonte do OBS. As referências dos arquivos visuais têm nova versão para reduzir problemas de cache.
- **Testes locais:** `node tests/captcha_integrado.test.cjs`, `python tests/verify_two_phase_captcha.py` e verificações de sintaxe JavaScript/Python. O teste de aparência direto no OBS com Twitch/Kick reais ainda depende do computador do cliente.

## Atualização v21 — ordem correta do CAPTCHA e espera pelo !nick no OBS

- **Mensagens na ordem certa:** ao acertar o CAPTCHA, o bot anuncia primeiro **`✅ Resposta correta, {nome}!`** e só depois envia a mensagem personalizável **`🎁 @{nome}, mande {comando_nick} NomeDoPersonagem para receber seu prêmio ({premio}).`**. Mesmo que o envio para a plataforma demore, a instrução não ultrapassa a confirmação. O evento **Vencedor respondeu: instruções para receber prêmio (!nick)** continua editável na aba Mensagens e respeita os controles Twitch/Kick.
- **Padrão atualizado sem perder personalizações:** se o texto salvo for exatamente o padrão da v20 (`presença confirmada`), ele é atualizado automaticamente para a nova instrução; qualquer mensagem personalizada pelo cliente é preservada.
- **Aguardando nick no OBS:** depois da resposta correta, o cronômetro continua **parado** e o cartão do chat do vencedor permanece na tela com a informação **`Aguardando !nick NomeDoPersonagem…`**. Ele desaparece quando o próprio vencedor enviar o comando e a consulta do personagem for válida, quando o operador iniciar outro sorteio ou ao encerrar a coleta. Consultas inválidas não encerram essa etapa.
- **Prazo esgotado continua limpo:** para vencedor que **não respondeu aos 60 segundos iniciais**, o cartão desaparece, sem entrar na etapa de aguardar nick. O novo comando não reinicia o timer nem altera a estatística de quem respondeu/mamou.
- **Histórico operacional:** o personagem informado pelo vencedor validado é registrado na auditoria `winner_claim_nick` para que o administrador possa identificar o pedido. A consulta `!nick` não entrega itens do MEGAMU automaticamente.
- **Atualização:** pare o servidor e substitua os arquivos do pacote, preservando `.env`, `.venv` e `dados`. Reinicie e recarregue o painel (`Ctrl+F5`) e as fontes do OBS.
- **Teste:** `python tests/verify_two_phase_captcha.py` e `node tests/captcha_integrado.test.cjs`.

## Atualização v20 — orientação do `!nick` e cartão do chat que desaparece

- **Mensagem ao vencedor:** após o vencedor confirmar o prêmio (na primeira resposta quando não há CAPTCHA ou após acertar o CAPTCHA), o bot envia automaticamente uma orientação na plataforma em que ele ganhou, por exemplo: `🎁 @biaabs, presença confirmada! Para receber Teste, envie !nick NomeDoPersonagem no chat.`
- **Mensagem personalizável:** na aba **Mensagens**, o evento **Vencedor respondeu: instruções para receber prêmio (!nick)** possui controles independentes para Twitch e Kick. Use `{nome}`, `{premio}` e `{comando_nick}` para preencher o nome, o prêmio e o comando atualmente configurado em **Sorteio**. O envio respeita o botão **Anunciar este evento** e o envio automático de cada plataforma.
- **Overlay limpo após o prazo:** a janelinha do chat do vencedor desaparece quando o tempo acaba, ele é pulado ou tem a resposta confirmada. Uma mensagem antiga não mantém a janelinha visível.
- **Importante:** `!nick` consulta o personagem MEGAMU; a entrega do prêmio ainda depende do procedimento do administrador.
- **Atualização:** pare o servidor, substitua os arquivos do pacote e mantenha intactos `.env`, `.venv` e `dados`. Ao iniciar novamente, pressione `Ctrl+F5` no painel e atualize/recarregue a Fonte de Navegador no OBS.
- **Testes locais:** `python tests/verify_two_phase_captcha.py` e `node tests/captcha_integrado.test.cjs`.

## Atualização v19 — resposta primeiro, código depois

- **Cronômetro de presença:** depois que alguém é sorteado, o relógio só mede o tempo para a pessoa falar pela primeira vez na Twitch ou Kick. A primeira mensagem válida, mesmo que seja "oi" ou "as", para o relógio imediatamente.
- **CAPTCHA em segunda etapa:** para vencedor marcado, a primeira fala **não** é comparada ao código. Só após essa fala o servidor gera e exibe o código no overlay centralizado e no chat (se o anúncio estiver ativado). Não inicia uma segunda contagem regressiva.
- **Código incorreto:** a resposta correta é exibida no overlay, no painel e na resposta automática do bot. O prêmio não é concedido sozinho; o administrador pode **Confirmar prêmio manualmente**, **Gerar novo** ou **Pular vencedor** na aba Antibot. Mensagens antigas que não tinham `{resposta}` recebem a resposta correta automaticamente.
- **Histórico:** a pessoa que apareceu no chat conta como alguém que respondeu, mesmo se falhar no CAPTCHA. "Mamou" continua reservado a quem deixou o prazo acabar sem responder.
- **Como atualizar:** feche o programa e substitua os arquivos do pacote, preservando suas pastas `.venv` e `dados` e o arquivo `.env`. Reinicie e atualize o cache da Fonte do Navegador no OBS.
- **Teste local:** `python tests/verify_two_phase_captcha.py` e `node tests/captcha_integrado.test.cjs`.

## Atualização v16.2 — Participantes + Chances, mensagens padrão e `!rank`

- **Abas unificadas:** a antiga aba **Chances** foi incorporada à aba **Participantes**. A tabela mostra nome, plataforma, categoria, peso, **chance percentual real** (com barra), situação ativo/inativo e vencedor. Desativados ou já sorteados aparecem com 0% de chance; ao reativar, o sistema recalcula imediatamente. As regras e multiplicadores continuam configurados em Sorteio.
- **Mensagens automáticas:** os textos vazios salvos em versões anteriores são substituídos pelos padrões ao carregar; textos personalizados não vazios são mantidos. Ao salvar, um campo deixado vazio volta ao texto padrão do evento, e é possível desligar o anúncio pelo interruptor sem apagar seu conteúdo.
- **Comando `!rank`:** ativado por padrão e personalizável em **Sorteio → Regras de entrada → Comandos do chat**. `!rank` consulta o próprio histórico; `!rank Nome` consulta o nome informado **na mesma plataforma da mensagem**. A resposta padrão é `🏆 @{nick} já ganhou {total} vezes, respondeu {respondeu} e mamou {mamou}.`, com textos independentes para Twitch/Kick na aba Mensagens. Há limites de frequência (10 s por espectador; 2 s global).
- **O que significa “mamou”:** apenas vencedor cujo **prazo expirou sem resposta**. O banco agora distingue `answered` (respondeu), `timeout` (mamou), `declined` (desistiu com comando), `skipped` (pulado manualmente) e `pending` (ainda sem resultado conhecido). O histórico antigo é migrado preservando todos os registros e usando os eventos de auditoria para reconhecer os prazos/desistências antigos quando eles foram registrados. Registros sem causa identificável não são tratados como timeout automaticamente.
- **Atualização:** mantenha seus diretórios `dados`, `.venv` e o `.env` original. Feche o servidor, atualize os arquivos, inicie novamente e pressione Ctrl+F5 no painel.

**Verificação:** testes locais com SQLite antigo/novo, mensagens padrão, comandos reservados, limites, chances recalculadas e fluxo de resposta/desistência/timeout. As contas reais da Twitch e Kick não foram utilizadas nos testes.

## Atualização v16.1 — participantes, confirmação de nick e Twitch

- **Participantes:** em **Participantes**, clique no nome ou no status **ATIVO/INATIVO** para desativar ou reativar a pessoa. Quem estiver inativo não participa do sorteio, mas continua na lista, com status visível no painel e identificação discreta no overlay do OBS. Os controles são filtráveis e as alterações ficam no histórico de auditoria. O bloqueio vale somente para a coleta atual; ao iniciar outra, a lista é reiniciada. O vencedor atualmente em atendimento não pode ser desativado até o sorteio dele terminar.
- **`!nick`:** `!nick darcherman` responde, conforme a API: `✅ DArcherMan existe no MEGAMU! ⚔️ Nível 400 | 🔄 200 RR | 🎯 Hunt 138`. A resposta negativa `Player não existente.` passa a gerar o anúncio configurado de erro, com mensagem de personagem inexistente, sem confirmar falsamente. As mensagens ainda podem ser personalizadas na aba **Mensagens**.
- **Twitch:** mantido o botão de identificação do Client ID porque ele valida o token e seus escopos de leitura/escrita. Seu nome é agora **Verificar token e preencher Client ID** e a finalidade fica explicada ao lado. A verificação usa o serviço oficial `/oauth2/validate` da Twitch.
- **Instalação:** feche o servidor, atualize os arquivos do programa e **preserve** `.env`, `dados` e `.venv`. Reinicie e use `Ctrl+F5` no navegador. O endereço do painel e os links do OBS continuam os mesmos.

**Validação da atualização:** testes da API local para ativação, desativação, recálculo das chances, proteção contra alteração do vencedor atual e leitura de nick válido/inválido, além dos testes anteriores de chat e CAPTCHA. Consultas MegaMu/Twitch reais e envio ao vivo dependem das suas credenciais/conexões.

## Atualização v16 — CAPTCHA integrado e comandos do chat

- **CAPTCHA integrado** ao sorteador, no mesmo endereço `/overlay/sorteio`, com fundo escurecido, nome do vencedor, pergunta e contador. A fonte antiga `/overlay/captcha` continua para compatibilidade, mas não deve ficar ativa junto da nova no OBS. O contador antigo também foi corrigido.
- **Desistência pelo chat:** o vencedor pode digitar `!pular` (ou outro comando configurado) para devolver o prêmio e sortear outra pessoa. O limite de desistências voluntárias por coleta é configurável de 1 a 100 (padrão: 3). O comando só vale para o vencedor da mesma plataforma, e o limite zera ao começar outra coleta.
- **Consulta MEGAMU:** `!nick darcherman` chama o endpoint público `getdata.php` e tenta publicar o retorno na plataforma da mensagem. Há controle de frequência; nenhum DV ou chave da API de prêmios é utilizado nessa consulta.
- **Painel:** em Sorteio → Regras de entrada → Comandos do chat, altere comandos, limites e habilitação. Em Conexões → Mensagens automáticas, personalize as mensagens de desistência, limite e consulta de nick para Twitch e Kick.

Consulte `GUIA_CAPTCHA_INTEGRADO.md` e `GUIA_COMANDOS_CHAT.md`. Ao atualizar, mantenha seus diretórios **`dados`** e **`.venv`** e o arquivo **`.env`**; eles não estão incluídos no ZIP de distribuição. A leitura real de `getdata.php` não foi possível no ambiente da ferramenta web; testes locais usaram resposta simulada e o usuário poderá confirmar com `!nick darcherman` no chat conectado.

## Atualização — iniciador gráfico para o cliente

O servidor agora pode ser iniciado por **`Iniciar Sorteador.bat`** ou **`run.bat`**, que abrem uma central gráfica com botões Iniciar/Parar, indicador online, links do painel/OBS e logs em tempo real. **`run_console.bat`** mantém o modo antigo de terminal para diagnóstico. A porta continua **8777**, sem alterar os overlays. Veja **`GUIA_CONFIGURACAO_VISUAL.md`** para instalar e usar.

As instruções antigas nesta página que mencionam a janela de terminal referem-se às versões anteriores. Preservar `.env`, `dados` e `.venv` ao atualizar continua obrigatório.

## Atualização v15 — regras de entrada com gravação imediata

Revisadas as opções da captura “Aceitar Twitch”, “Aceitar Kick” e “Bloquear vencedor repetido”. Foram encontrados interruptores sem envio ao servidor no clique, redefinição das plataformas ao iniciar coleta e uso dos controles de novas inscrições para filtrar pessoas que já estavam na lista.

- **Aceitar novas entradas · Twitch/Kick:** controla apenas novas inscrições daquela plataforma. Não retira quem já está inscrito, não desconecta o chat, não desliga o bot e não impede a resposta/captcha do vencedor. Pausar continua bloqueando inscrições globalmente; encerrar termina o sorteio e oculta o overlay.
- As escolhas podem ser feitas antes ou durante a coleta, são gravadas imediatamente no banco e continuam após recarregar/reiniciar. Iniciar uma nova coleta respeita as plataformas escolhidas.
- **Quem já ganhou:** continua marcado e bloqueado na plataforma vencedora, independentemente do interruptor adicional. Uma nova coleta libera os participantes.
- **Bloquear o mesmo nick também na outra plataforma:** ligado impede esse nick de ser sorteado também na outra plataforma da lista. Desligado permite que a entrada da outra plataforma seja considerada. Nomes das opções e explicações no painel foram ajustados para deixar a diferença clara.
- Os demais interruptores de regras também passam a salvar ao clicar. As requisições são sequenciadas, atualizações antigas do estado não desfazem cliques em andamento e erros de gravação ficam visíveis. A API aplica apenas os campos enviados, preservando outras regras.

Validação: 110 testes automatizados, incluindo reinicialização real, preferência por plataforma, preservação de inscritos, atualizações parciais, bloqueio adicional entre plataformas e resposta do vencedor com novas inscrições desativadas. Navegador: gravação imediata, atualização de estado durante o envio, recarregamento, mudanças durante coleta e restauração do valor confirmado quando ocorre falha no servidor. As APIs externas são simuladas; não houve teste nas contas reais do usuário.

Atualize preservando `dados`, `.env` e `.venv`. Reinicie o servidor e pressione Ctrl+F5 no painel. Atualize também as fontes de navegador do OBS.

## Atualização v14 — vencedor marcado, chat no OBS e canais da Twitch

- Quem já foi sorteado fica marcado e não volta ao sorteio da mesma lista. Vale mesmo com a antiga preferência de repetição desligada. A identidade é conferida pela plataforma/ID e pelo login; “Iniciar coleta” abre uma nova lista e libera todos. O painel e o overlay identificam os participantes já sorteados. A opção de regras agora especifica o bloqueio adicional do mesmo nick na outra plataforma.
- O overlay do sorteio possui uma janela compacta com foto/inicial, nome e plataforma do último vencedor. Mostra somente as mensagens recebidas dele desde o sorteio, até seis mensagens, com rolagem. Respostas continuam visíveis depois da confirmação automática. Um novo vencedor limpa o chat anterior; encerrar esconde a janela junto com o overlay. Mensagens de outras pessoas, da outra plataforma e ecos enviados pelo bot ficam fora da janela.
- Revisado o chat da Twitch comparando `chat_channels.js`, `shared_chat.py` e a integração do `script.js` no ZIP do bot enviado. Adicionada a consulta da sessão compartilhada pelo servidor, com cache e credenciais protegidas. Os nomes dos canais podem aparecer antes das primeiras mensagens; se a consulta falhar, o histórico e os filtros continuam funcionando.
- Corrigida a lista de seleção para refletir “Só meu canal”, “Toda a colab” e “Canais específicos”. Ao remover um canal de “Toda a colab”, preserva os outros canais selecionados. O novo botão “Restaurar filtros do chat” recupera a visualização do próprio canal e desliga filtros de somente menções. Preferências continuam salvas no navegador.
- Sons e menções permanecem configuráveis. O áudio pode ser liberado por um clique ao usar preferências já salvas; “Testar som” continua disponível.
- Novas entradas no overlay reaproveitam os cartões existentes. Adicionar alguém não reinicia as animações/fotos de quem já estava na tela.

Validação: 103 testes automatizados. Verificações de navegador sem erros de JavaScript, incluindo detecção de canais antes da primeira mensagem, filtros, menções/som, resposta exclusiva de cada plataforma, permanência após confirmação, troca do vencedor, ausência de sobreposição com o cronômetro e preservação dos cartões. APIs externas foram simuladas; o teste com contas reais e OBS instalado depende do ambiente local.

Para atualizar, feche o servidor, preserve `dados`, `.env` e `.venv`, substitua os arquivos do programa e reinicie. Use Ctrl+F5 no painel e atualize a fonte de navegador do OBS. O link permanece `http://127.0.0.1:8777/overlay/sorteio`.

Referência conferida para sessão compartilhada e origem das mensagens: https://dev.twitch.tv/docs/api/reference/#get-shared-chat-session e https://dev.twitch.tv/docs/eventsub/eventsub-reference/.

## Atualização v13 — chances, sorteio integrado e overlay estável

- Removida a opção “Adicionar novos prêmios à roleta” de Conexões. A lista do sorteio recebe os prêmios da API diretamente.
- Um único botão faz o primeiro sorteio e os próximos, mantendo os participantes. Com vencedor ativo, pede confirmação antes de substituí-lo. O avanço automático ao fim do prazo continua opcional.
- Salvar a conexão MegaMu com a atualização habilitada consulta os prêmios imediatamente. “Consultar prêmios” também ativa o catálogo integrado. Painel e OBS usam a mesma lista, incluindo personalizados. Falhas mantêm o último catálogo; o diagnóstico aparece em Conexões.
- A palavra-chave é gravada ao iniciar a coleta e reaparece ao recarregar ou reiniciar.
- As chances ficam em colunas Twitch e Kick, com Sub, VIP e Moderador. Viewer vale 1x. Sempre considera a maior chance aplicável, nunca a soma: Sub 2x e VIP 2,5x resulta em 2,5x. Aceita vírgula e ponto. Os fatores individuais existentes são preservados; a combinação passa a seguir a nova regra.
- Moderadores têm permissão de entrada independente por plataforma. Ajuste os controles e clique em “Salvar chances”. A lista atual é recalculada; o histórico do vencedor conserva o valor do momento do sorteio.
- Mensagens enviadas pelo bot são reconhecidas pelo identificador e, antes da confirmação do envio, pela conta remetente e texto exato. Elas não viram respostas ao captcha. Mensagens recebidas duplicadas são descartadas e o aviso de erro tem intervalo mínimo de três segundos. Mensagens reais da conta principal continuam sendo processadas.
- O overlay atualiza participantes, prêmios e vencedor apenas quando o conteúdo visual muda. Consultas e mensagens de estado repetidas preservam os elementos e não reiniciam as animações nem recarregam as fotos. As consultas continuam em segundo plano.
- No OBS, todos os prêmios aparecem só com o nome/ícone, sem botão de exclusão ou indicação de que são personalizados.

**Para atualizar:** feche o servidor, substitua os arquivos do programa preservando `dados`, `.env` e `.venv`, reinicie, use Ctrl+F5 no painel e atualize a fonte de navegador no OBS. Link do sorteio: `http://127.0.0.1:8777/overlay/sorteio`.

Validação: 99 testes automatizados; navegador sem erros de JavaScript, persistência dos controles de moderadores, valores decimais e palavra-chave após recarregar; catálogo compartilhado e estabilidade dos elementos do overlay após consultas periódicas. Os testes de APIs usam respostas simuladas, incluindo retorno da mensagem do bot antes da resposta HTTP. O teste nas contas reais e no OBS instalado fica para o ambiente local.

Referências dos contratos de chat conferidos: https://github.com/KickEngineering/KickDevDocs/blob/main/events/event-types.md e https://dev.twitch.tv/docs/api/reference/#send-chat-message.

## Atualização v12 — pesos em x e lista de prêmios

- A aba Mensagens agora possui ícone. Os textos padrão de confirmação e repetição mostram o fator real: `darcherman, inscrição confirmada! Chance: 2,5x.` O campo `{peso}` traz somente o número; acrescente `x` no texto. `{chance}` continua disponível para porcentagens em mensagens personalizadas. Textos antigos que eram padrão são atualizados; personalizações existentes são preservadas.
- **Sorteio → Regras de entrada → Pesos de Sub e VIP** permite configurar pesos totais decimais, com vírgula ou ponto (`1,5` e `2.5`). Viewer tem peso 1x. A regra anterior foi mantida: quem acumula Sub e VIP soma os bônus, isto é, `1 + (peso Sub − 1) + (peso VIP − 1)`. Os valores já cadastrados são preservados. Salvar atualiza a lista atual e novas entradas; o histórico mantém o peso que valia no sorteio.
- O status Aberto mostra luz azul para Twitch e verde para Kick. A luz apaga quando a coleta daquela plataforma estiver fechada ou pausada.
- O campo Prêmio opcional foi substituído por **Prêmios disponíveis**, com rolagem e altura limitada. A lista combina a disponibilidade da MegaMu e os prêmios personalizados, salvos no banco.
- **Adicionar prêmio** cadastra um item próprio. Apenas itens próprios têm o botão × no painel. A API rejeita tentativas de remover um item MegaMu por esse botão. Uma falha na consulta mantém o último catálogo; uma resposta válida atualiza a lista e retira os itens ausentes. Trocar as credenciais da MegaMu inicia um novo catálogo.
- Clicar em um prêmio seleciona o item para o próximo sorteio e dispara o evento **Próximo sorteio: prêmio selecionado**, configurável na aba Mensagens, com texto padrão `Próximo sorteio: {premio}`. Os interruptores do evento, da plataforma e do envio geral continuam sendo respeitados. O prêmio selecionado é associado ao vencedor e ao histórico.
- **No OBS, prêmios próprios e MegaMu aparecem juntos somente como prêmios, sem botão × nem indicação de origem.** O controle de exclusão e os rótulos Personalizado/MegaMu ficam apenas no painel administrativo.

Atualize preservando `dados`, `.venv` e `.env`; reinicie o servidor, recarregue o painel com Ctrl+F5 e atualize as fontes do OBS. Para usar a nova confirmação em uma mensagem já personalizada, substitua a parte desejada por `Chance: {peso}x` e salve na aba Mensagens.

Validação: 94 testes automatizados, incluindo reinicialização real, pesos 1,5/2,5, confirmação no chat, remoção protegida de prêmios externos, falha temporária da API, seleção e prêmio do vencedor. Navegador para lista com rolagem, pesos com vírgula, luzes das plataformas, seleção e apresentação dos personalizados no overlay sem controles de administração. As integrações reais ainda dependem das suas contas e credenciais locais.


## Atualização v11 — prazo unificado, próxima pessoa e catálogo de prêmios

- O prazo da aba Sorteio é o mesmo para Twitch, Kick e captcha. O campo no Anti-bot apenas mostra esse prazo; não existe mais um cronômetro separado de 30 segundos. Alterações no prazo valem para novos vencedores.
- Respostas erradas ao captcha mostram o erro no painel e, se habilitado em Mensagens, no chat. A pessoa pode tentar novamente até o prazo terminar. Acertar confirma a presença e para o cronômetro. Não há eliminação por duas respostas erradas.
- **Sortear próximo (mesma lista)** sorteia outra pessoa sem limpar inscrições. Pode pausar a coleta e fazer vários sorteios da lista existente. O botão respeita o bloqueio de vencedores repetidos. Se quiser repetir pessoas já confirmadas, desative esse bloqueio nas regras.
- **Sortear próximo automaticamente quando o prazo acabar** é opcional e começa desligado. Desligado: o prazo termina e aguarda seu clique. Ligado: sorteia outra pessoa quando não há resposta. Pessoas sem resposta não retornam indefinidamente no mesmo sorteio.
- A nova aba **Mensagens** reúne eventos, textos separados para Twitch/Kick e controles de ativação por evento/plataforma. Inclui inscrição confirmada com chance atual, já está participando, captcha correto/incorreto e prazo encerrado. Confirmações de inscrição e repetição vêm habilitadas nesta versão; podem ser desligadas na aba.
- Campos novos: `{chance}` (número já calculado, adicione `%` ao texto), `{participantes}` (quantidade na lista) e `{proximo}` (orientação de avanço). A chance considera os pesos e a elegibilidade naquele momento; pode mudar com novas inscrições e sorteios.
- Mensagens de entrada e feedback são enviadas em segundo plano para não atrasar a leitura do chat. O envio da Twitch respeita o intervalo local entre mensagens.

### API de prêmios MegaMu

Em **Conexões → Prêmios MegaMu**, informe o DV e a chave usados pelo seu overlay, marque a atualização e clique em **Salvar conexão**. Os campos são sincronizados com `MEGAMU_DV`, `MEGAMU_KEY` e `MEGAMU_ENABLED` no `.env`. Campo de chave vazio mantém a chave cadastrada. Clique em **Consultar prêmios** para verificar.

A consulta usa `https://megamu.net/dvapi.php` com `action=getawards`, conforme o HTML enviado. A chave fica no servidor: não usa proxies públicos nem expõe a URL autenticada ao navegador. O catálogo é atualizado a cada 5 segundos, com cache compartilhado entre os overlays.

Quando ativada, a lista de prêmios do overlay principal mostra os nomes disponíveis na API. **Adicionar novos prêmios à roleta** inclui apenas nomes ainda não cadastrados, com peso inicial 1, preservando os itens e pesos existentes. Ajuste as chances na Roleta. A integração consulta disponibilidade; não entrega ou resgata prêmios do jogo automaticamente.

Validação: 88 testes automatizados, incluindo reinicialização real do servidor, contratos HTTP simulados da MegaMu, prazo nas duas plataformas, múltiplos erros de captcha, sorteios manuais da lista pausada e avanço automático opcional. Navegador Chromium para os controles, persistência das mensagens, avatar e overlays. A API real da MegaMu precisa ser testada com seu DV/chave; nenhuma conta real foi usada nos testes.


## Atualização v10 — credenciais, confirmação automática e fotos

- O programa cria `.env` na pasta do projeto, com credenciais sincronizadas pela página Conexões. O arquivo é carregado na inicialização, antes da reconexão. O token da Twitch não é apagado ao salvar um formulário vazio depois de recarregar. Os campos secretos permanecem vazios na página, com indicação de que já estão salvos.
- A autorização da Kick salva também o refresh token, expiração absoluta, escopos e canal no `.env`. As renovações atualizam o arquivo; a sessão é renovada em segundo plano quando necessário. Corrigida a liberação de memória do DPAPI no Windows, que podia fazer o armazenamento protegido falhar. O armazenamento protegido continua disponível em paralelo ao arquivo solicitado.
- Os anúncios vêm habilitados ao conectar. O controle de silenciar está visível junto da configuração de cada plataforma e salva automaticamente. Os textos e eventos continuam personalizáveis em Mensagens automáticas. Uma escolha explícita de silêncio é mantida nas reconexões.
- Removido o botão Confirmar resposta. Uma mensagem do vencedor na plataforma em que ganhou confirma a presença e para o cronômetro; se estiver marcado pelo anti-bot, precisa acertar o captcha. Outra pessoa ou uma mensagem em outra plataforma não confirma a resposta.
- Vencedores sem resposta são excluídos dos próximos re-sorteios automáticos deste sorteio. Isso impede o cronômetro de voltar infinitamente para a mesma pessoa mesmo com repetição de vencedores permitida. Quando não há mais pessoas elegíveis, o cronômetro encerra.
- A foto oficial da Twitch é exibida nos participantes e no vencedor do overlay, incluindo quando a busca do avatar termina depois do sorteio. A inicial continua como alternativa se a imagem falhar.
- O overlay recupera estado via HTTP quando o WebSocket não estiver disponível. A fonte do OBS usa `http://127.0.0.1:8777/overlay/sorteio`; atenção aos dois-pontos antes de 8777. Prefira o botão Copiar da aba OBS e recarregue a fonte após atualizar.

**Atualização:** feche o servidor, substitua o código preservando `dados`, `.venv` e qualquer `.env` existente, execute `run.bat`, use Ctrl+F5 no painel e recarregue a fonte do OBS. Se uma credencial anterior não chegou a ser gravada, cadastre-a uma vez nesta versão. O `.env` real nunca acompanha o ZIP de atualização; ele é gerado no seu computador. O arquivo contém credenciais: não compartilhe.

Tokens expirados ou revogados podem exigir renovação/autorização conforme a plataforma. Guardar o token no `.env` não prolonga a validade dele. Na Kick, o refresh funciona quando a autorização ainda permite renovação.

## Atualização v9 — coleta, overlay e mensagens

- O overlay do sorteio aparece quando a coleta é iniciada e desaparece ao encerrar, mesmo se o vencedor continuar registrado no painel. O estado do OBS é publicado antes de aguardar as APIs de chat.
- Removido o bloqueio da conta dona do canal na Twitch. Em ambas as plataformas, o dono segue a opção de permitir moderadores na seleção de vencedores.
- Corrigida a requisição de envio da Twitch: `broadcaster_id`, `sender_id` e `message` vão juntos no corpo JSON exigido pelo endpoint `POST /helix/chat/messages`. Ao trocar de canal, os IDs são resolvidos novamente.
- A leitura direta da Kick agora negocia o transporte Centrifugo usado no bot de referência enviado. Trata confirmação de assinatura, mensagens em lote, ping/pong, duplicatas e reconexão com nova credencial pública efêmera. A credencial de leitura não é o token OAuth da conta que envia mensagens.
- A identificação automática obtém `id` do canal e `chatroom.id`. Se o serviço bloquear essa consulta, os dois campos podem ser informados nas opções avançadas. O modo Webhooks continua disponível como alternativa.
- O painel mostra os anúncios habilitados antes de iniciar e o resultado de envio de cada plataforma depois da abertura. **Mensagens de teste não ligam anúncios automaticamente.** Em Conexões → Mensagens automáticas, habilite a plataforma e o evento Abertura e clique em Salvar mensagens. Suas escolhas de silêncio são preservadas.

### Teste depois de atualizar

1. Feche o programa, substitua o código conforme a instalação abaixo, preserve a pasta `dados` e abra novamente. Atualize o painel com Ctrl+F5 e recarregue a fonte do OBS.
2. Conecte a Twitch e, separadamente, clique em Conectar chat na recepção da Kick. Autorizar a Kick permite enviar, mas não substitui essa conexão de leitura.
3. Em Conexões → Mensagens automáticas, habilite as plataformas e o evento Abertura se quiser os anúncios. Salve.
4. Inicie a coleta e confira o overlay e o resultado dos anúncios. Envie a palavra-chave exata em cada chat e confira os participantes. Para testar a conta principal, permita moderadores nas regras.
5. Encerre o sorteio e confira que a fonte do OBS fica transparente. Link: `http://localhost:8777/overlay/sorteio` (OBS e servidor no mesmo computador).

Validação da versão: testes com SQLite temporário, contratos HTTP simulados, servidor WebSocket local e navegador Chromium. Não houve acesso às suas contas para validar mensagens ao vivo. A conexão pública da Kick depende do serviço do site e pode mudar; uma falha não ativa participantes simulados.

## Instalação no Windows

1. Feche o terminal do sorteador e guarde uma cópia da pasta atual.
2. Copie o conteúdo da pasta `sorteador_geral` deste ZIP para a pasta atual do programa, substituindo os arquivos de código. **Este ZIP de atualização não contém a pasta `dados` nem `.venv`**: seu banco, prêmios e configurações locais permanecem no lugar.
3. Execute `instalar.bat` para instalar/atualizar dependências no ambiente `.venv`. Ele reutiliza o ambiente existente; não instala pacotes no Python global. Requer Python 3.10 ou superior.
4. Execute `run.bat` e abra http://localhost:8777/admin . Mantenha o terminal aberto.
5. Recarregue o painel com Ctrl+F5 e atualize as fontes de navegador do OBS para carregar os controles e scripts novos.

O `run.bat` agora inicia especificamente `.venv\Scripts\python.exe`, corrigindo o conflito de dependências relatado na instalação anterior. Ele orienta executar `instalar.bat` quando o ambiente ainda não existe.

## Twitch

Em **Conexões**, configure Client-ID e um **User Access Token** correspondente ao mesmo aplicativo. O botão **Identificar Client ID do token** pode preencher o ID correto usando a validação oficial. Para receber mensagens pelo EventSub, autorize `user:read:chat`; para enviar, também `user:write:chat`. Um App Access Token não substitui esse token no transporte WebSocket utilizado pelo programa.

Clique em **Salvar credenciais**, **Testar** e depois **Conectar** no canal correto. O status fica conectado depois da assinatura EventSub. Tokens vencidos/revogados precisam ser renovados e testados novamente.

O tratamento de `session_reconnect` foi corrigido: a leitura continua no novo socket sem recriar a assinatura transferida. Conectar uma conta real também tira o programa do modo de simulação.

## Kick

**Modo padrão sem ngrok:** em Conexões → Receber chat e inscrições, informe o canal e use Conexão direta. OAuth só é necessário para enviar. Consulte a seção Atualização v7 ao final.

### Alternativa por webhooks oficiais

1. No app de desenvolvedor da Kick, cadastre a **Redirect URI** exibida em Conexões. Para acesso por localhost, use `http://localhost:8777/api/oauth/kick/callback`. `localhost` e `127.0.0.1` são endereços distintos para OAuth; use exatamente o endereço cadastrado.
2. Preencha Client ID, Redirect URI e, quando exigido pelo aplicativo, Client Secret. Clique em **Autorizar**.
3. Autorize `user:read`, `channel:read` e `events:subscribe`. O botão solicita também `chat:write` para permitir anúncios opcionais. Se um token antigo não possui esse escopo, autorize novamente.
4. Configure o ngrok no seu Windows e clique em **Conectar ngrok**.
5. Copie a URL HTTPS exibida (incluindo `/api/webhooks/kick`) para **Webhook URL** do app no painel da Kick e habilite webhooks. A assinatura não configura essa URL automaticamente na Kick.
6. Clique em **Criar assinatura** e **Atualizar**. Se o endereço do túnel mudar, atualize o endereço no painel da Kick.
7. Abra um sorteio e envie a palavra-chave pelo chat. Confira a chegada do participante no painel.

No modo Webhooks, o recebimento usa eventos oficiais; não usa cookies do navegador. Foram corrigidos formato RFC3339, verificação RSA/SHA256, leitura da chave pública, encaminhamento ao loop principal e interpretação das respostas de assinatura. A expiração do token agora é absoluta: reiniciar o programa não aumenta sua validade. Escopos e canal são preservados no armazenamento protegido do Windows.

**Estado operacional** indica OAuth válido + túnel ativo + assinatura registrada. É necessário enviar uma mensagem real para confirmar também a entrega do webhook. O estado de assinatura é atualizado pelo botão Atualizar; mudanças externas precisam de nova consulta.

## Mensagens no chat

Em **Conexões → Mensagens automáticas**, ative ou desative **Twitch** e **Kick** de forma independente. Desativar silencia os anúncios e captcha, mantendo a coleta de participantes.

Cada evento tem seu próprio interruptor e textos separados para as duas plataformas. Inscrição aceita/repetida vêm desligadas para evitar mensagens em excesso. Campos disponíveis: `{nome}`, `{plataforma}`, `{premio}`, `{keyword}`, `{tempo}`. Clique em **Salvar mensagens**. Salvar não envia mensagens de teste.

O captcha exige também a opção **Anti-bot → Enviar desafio no chat**. Os envios só são tentados com a plataforma habilitada e fora do modo de simulação. O histórico de auditoria registra sucesso/falha dos anúncios automáticos. O envio à Kick agora usa `/public/v1/chat` e só confirma sucesso quando a API devolve `is_sent: true`.

Para um teste de anúncio, use um sorteio real com um participante conhecido. **Giro de teste da roleta não anuncia o prêmio no chat.**

## Chats ao vivo, colab e autorização única

A aba **Chats** apresenta as conversas da Twitch e da Kick, filtros da colab e preferências de leitura, sons e menções. A nova aba **Conexões** reúne contas, credenciais, OAuth, ngrok, assinaturas de eventos, diagnóstico e mensagens automáticas, sem um segundo formulário de token para respostas do bot.

### Twitch e colab

- **Só meu canal:** filtra a origem das mensagens para o canal Twitch conectado.
- **Toda a colab:** mostra todas as mensagens da sessão compartilhada que a Twitch entregar ao canal conectado.
- **Canais específicos:** escolha os canais no botão Canais. A lista reúne os canais que já enviaram mensagens; também permite informar um login da colab.
- Adicionar um login é um filtro da sessão compartilhada, não abre uma conexão com qualquer canal independente.
- **Sempre mostrar @menções:** mantém visíveis mensagens que mencionem seu canal, a conta conectada ou um dos nicks adicionais, inclusive vindas de um canal oculto pelo filtro.
- **Só menções:** mostra apenas mensagens que mencionem esses nicks.
- O canal de origem aparece junto de cada mensagem. As opções de visualização não alteram as regras de inscrição do sorteio: a palavra-chave continua sendo processada nas mensagens recebidas, como antes.

A origem é obtida de `source_broadcaster_user_login` do EventSub, quando a mensagem vem de outro canal da colab. Não é inferida do nome de quem escreveu. Mensagens de outro canal da colab não podem acionar os comandos administrativos da roleta.

### Sons e leitura

Cada chat tem som independente, para mensagens visíveis ou apenas menções. Use **Ativar / testar som** uma vez por sessão do navegador para liberar o áudio. O volume e os nicks adicionais ficam nas preferências gerais. Avisos não tocam novamente quando as mesmas mensagens chegam por atualização de estado ou reconexão.

As preferências são salvas neste navegador. As últimas 300 mensagens ficam na memória do servidor e são apagadas ao encerrá-lo; não são gravadas no banco. Os sons são produzidos pelo navegador que estiver com o painel aberto.

### Uma conta para leitura e envio

O único formulário Twitch contém canal, Client-ID e User Access Token. A mesma autorização atende à leitura do chat, mensagens manuais, anúncios automáticos e avatares. Trocar a credencial durante uma conexão pede reconectar para usar a nova autorização. O Client-ID deve corresponder ao aplicativo que emitiu o token.

Na Kick, a mesma autorização OAuth atende aos webhooks e ao envio de mensagens. Não é necessário um token separado de “bot de resposta”.

O campo **Enviar** publica no canal conectado da respectiva plataforma, mesmo se o filtro da colab estiver exibindo outros canais. O envio manual exige a permissão de escrita e uma conta real conectada. Ele não ativa os anúncios automáticos; estes continuam sujeitos aos interruptores de plataforma e evento na aba Conexões. O captcha também continua sujeito à opção de envio do anti-bot.

## Roleta e várias tentativas

- Design inspirado em **Grafite & Ouro**, com borda dourada, fatias grafite/dourado, ícones vetoriais e lista lateral de prêmios. O fundo permanece transparente para o OBS.
- Os tamanhos das fatias representam as probabilidades. Para seis fatias iguais à referência, atribua o mesmo peso aos seis prêmios e salve a distribuição. Prêmios inativos não são desenhados nem sorteados.
- **Voltas extras = 0** funciona: apenas alinha o resultado, sem adicionar voltas completas. A duração ainda controla o tempo de animação.
- **Quantidade de prêmios para este nick** aceita 1 a 20 giros consecutivos. Cada giro faz um sorteio independente, registra um resultado e espera o intervalo configurado antes do próximo. O mesmo prêmio pode sair mais de uma vez.
- Giros concorrentes são bloqueados. **Ocultar** interrompe o giro visual, cancela as tentativas restantes e deixa o overlay transparente. O resultado já sorteado continua no histórico.
- **Ocultar automaticamente** vem habilitado. O campo de segundos define por quanto tempo cada resultado fica visível; ao final da sequência, o overlay desaparece. Desabilitar mantém o resultado até clicar em Ocultar.
- O resultado selecionado permanece em um snapshot durante o giro. Alterar prêmios durante a animação não muda o resultado daquele giro. O ponteiro é alinhado pelo ID do prêmio, incluindo quando existem itens inativos.
- Somente o dono do canal ou moderadores podem usar `!roleta mostrar` / `!roleta ocultar` no chat.

O ZIP recebido não possuía um botão chamado “várias tentativas”; foi acrescentado um controle explícito para giros consecutivos. **Bloquear vencedor repetido** é outra função, do sorteio de participantes, e sua configuração também foi corrigida no estado enviado ao painel.

## OBS

Adicione uma **Fonte do Navegador** com largura **1920**, altura **1080**:

- Roleta: http://localhost:8777/overlay/roleta
- Sorteio: http://localhost:8777/overlay/sorteio
- Captcha: http://localhost:8777/overlay/captcha

Deixe **Desligar fonte quando não estiver visível** desmarcado para a roleta acompanhar os giros. O painel e o OBS devem acessar o mesmo servidor. Nenhuma conexão com a API do OBS é necessária: o conteúdo HTML controla a transparência e visibilidade da fonte.

Teste sugerido:

1. Adicione a fonte e confirme que a roleta começa oculta.
2. Cadastre prêmios, selecione Giro de teste e execute uma tentativa. Confira o prêmio sob o ponteiro.
3. Ative o ocultamento automático e espere o intervalo após o resultado. A fonte deve ficar transparente.
4. Faça uma sequência com três tentativas e observe três resultados no histórico.
5. Inicie outra sequência e clique em Ocultar. Ela deve parar sem iniciar os giros restantes.

Sem um overlay aberto, o servidor encerra o estado de giro após a duração mais uma margem de três segundos. Ele mantém a sequência e o ocultamento funcionando, mas não pode confirmar que o OBS exibiu algo. O painel avisa quando o overlay não confirma o início.

## Aparência e painel

A aba Aparência agora permite alterar destaque, cor secundária, fundo do painel, dourado/grafite da roleta, tamanho da roda, fonte, tamanho do nome do vencedor e exibição de lista/probabilidades. Há prévia de cores e restauração dos padrões. Clique em **Salvar aparência** para persistir. As alterações chegam aos overlays conectados.

O painel usa a organização da segunda referência: navegação lateral, indicadores, cartões, controles do sorteio, regras, participantes com filtro e vencedor. Dados e estados exibidos são reais, sem números ilustrativos. O histórico de vencedores fica abaixo.

## Anti-bot: seleção por inscrição

A probabilidade agora é avaliada **uma única vez na entrada de cada participante**, antes do sorteio do vencedor. O mesmo nick na mesma plataforma não ganha uma nova decisão ao repetir a palavra-chave. Uma inscrição pela outra plataforma é independente.

- **50%** significa uma chance independente de 50% por nova inscrição elegível. Não garante que exatamente metade da lista será marcada.
- **0%** não marca ninguém novo; **100%** marca todos os novos participantes elegíveis.
- Se **Isentar subs e VIPs** estiver ligado, essas novas inscrições não são marcadas.
- O captcha só é emitido se uma pessoa marcada vencer. A marcação não altera seu peso nem sua chance de ganhar.
- A opção **Aplicar só em parte dos vencedores** foi removida. Não há um novo sorteio de marcação no momento da vitória.
- Mudanças de probabilidade e isenção valem para novas inscrições; não refazem decisões já tomadas. Desativar o anti-bot impede novos desafios, mas não cancela um captcha já iniciado.
- **Pessoas marcadas** mostra nick, plataforma, chance usada na entrada e situação: aguardando sorteio, captcha em andamento, respondido, confirmado pelo painel, erro, prazo esgotado ou vencedor pulado. A lista possui busca/filtro e reinicia junto com os participantes ao abrir um novo sorteio ou resetar.
- Uma pessoa marcada é selecionada para verificação aleatória; isso não é uma classificação de que ela seja um bot.
- Para o vencedor marcado, o prazo do captcha substitui o prazo normal do sorteio. Reemitir o desafio renova o prazo. A resposta correta confirma o vencedor; dois erros ou o fim do prazo passam ao próximo elegível.

O botão **Confirmar resposta** do painel continua sendo uma confirmação manual: na lista, esse caso aparece como **Confirmado pelo painel**, sem alegar que o captcha foi resolvido.

A quantidade de prêmios da roleta é independente das voltas da animação. Ao escolher 3 prêmios, a sequência mantém o nick e exibe **prêmio 1 de 3**, **2 de 3** e **3 de 3** no overlay. Cada resultado é registrado no histórico. As legendas de Nome, Ícone, Peso relativo, Chance real, Ativo e Excluir agora ficam visíveis na configuração.

## Validação e limites

- 39 testes automatizados com SQLite temporário e APIs simuladas em `tests/test_regressions.py`.
- Teste em Chromium com todas as abas, giros consecutivos, transparência, ocultamento, zero voltas/peso, anúncios, persistência de aparência, vencedor, marcação por entrada, filtros de colab, menções, som sem repetição, envio manual simulado e layout em tela menor em `tests/browser_smoke.py`.
- Os testes não acessam contas reais nem enviam mensagens para canais. O banco local do usuário não é incluído nem substituído pelo pacote de atualização.
- Twitch/Kick reais, armazenamento DPAPI no Windows, execução do ngrok e renderização dentro do OBS precisam da validação no seu computador. A verificação local do HTML não equivale a um teste dentro do OBS.

Para repetir os testes opcionais:

```bat
".venv\Scripts\python.exe" -m pip install -r requirements-dev.txt
".venv\Scripts\python.exe" -m pytest -q tests
".venv\Scripts\python.exe" -m playwright install chromium
".venv\Scripts\python.exe" tests/browser_smoke.py
```

## Documentação consultada

- https://dev.twitch.tv/docs/eventsub/eventsub-reference/#channel-chat-message-event
- https://dev.twitch.tv/docs/chat/authenticating/
- https://dev.twitch.tv/docs/chat/send-receive-messages/
- https://docs.kick.com/apis/chat
- https://github.com/KickEngineering/KickDevDocs/blob/main/events/webhook-security.md
- https://github.com/KickEngineering/KickDevDocs/blob/main/events/subscribe-to-events.md

## Atualização v4 — cor e salvamento integrado

O painel usa verde neon suave (#79e8a4). Instalações com o antigo amarelo padrão são atualizadas automaticamente; cores personalizadas continuam configuráveis em Aparência.

Na aba Roleta, **Salvar tudo** grava os prêmios, a distribuição de chances, a animação e a opção **Anunciar nick e prêmio no chat** juntos. Corrija campos inválidos antes de salvar; um erro não grava apenas parte da configuração. O botão Girar agora salva e valida alterações pendentes automaticamente antes de iniciar a animação. Se houver erro, a mensagem aparece junto ao botão e nenhum giro é iniciado.

O anúncio informa o nick e o prêmio ao fim de cada giro. Giros de teste não anunciam. Habilite os destinos Twitch/Kick em **Conexões → Mensagens automáticas**, onde também pode personalizar os textos e ativar **Anunciar vencedor do sorteio**. As plataformas precisam estar conectadas com permissão de escrita. Salvar configurações não envia mensagens de teste.

## Atualização v5 — persistência e cor

Corrigida a migração dos amarelos antigos #ffcc00 e #ffd400 para verde suave, preservando outras cores personalizadas. Os recursos do painel têm versão no endereço para evitar misturar arquivos antigos em cache. Confira o indicador **v5** junto ao nome do programa.

Os pesos digitados agora são gravados exatamente como informados e reaparecem iguais após reiniciar o servidor. A chance real é calculada separadamente: valores 70 e 30 representam 70% e 30%; valores 20 e 30 continuam salvos como 20 e 30, com chances reais de 40% e 60%. Adicionar ou editar um prêmio não altera os valores dos outros.

Feche a janela do servidor anterior, extraia os arquivos na mesma pasta do programa, preservando **dados**, e execute run.bat. A pasta dados contém o banco com seus prêmios e configurações; iniciar uma cópia em outra pasta usa outro banco. Atualize o painel uma vez com Ctrl+F5.

## Atualização v6 — fatias iguais e autorização da Kick

Em Roleta → Animação, habilite **Fatias com tamanhos iguais** e clique em **Salvar tudo**. A mudança é somente visual: os pesos/chances continuam determinando os vencedores. Desligada, a opção mantém fatias proporcionais. O modo é salvo e capturado no início de cada giro; o ponteiro usa a mesma geometria da roda. A opção de mostrar porcentagens no overlay continua independente.

Na Kick, Client ID é a identificação do aplicativo no painel de desenvolvedor; não use seu nick. Client Secret deve vir do mesmo aplicativo. Cadastre exatamente a Redirect URI exibida pelo programa. O padrão local agora usa http://localhost:8777/api/oauth/kick/callback. Se já cadastrou http://127.0.0.1:8777/api/oauth/kick/callback, mantenha ambos os lados iguais: o programa aplica o parâmetro redirect antes de redirect_uri conforme a correção oficial da Kick.

Se a página externa continuar vazia após corrigir as credenciais, teste a autorização sem extensões de bloqueio (ou numa janela limpa). Mensagens de CSP no site externo não confirmam, por si só, a causa do erro 400. O formulário agora mostra instruções e erros junto ao botão, e abre a janela no clique para evitar bloqueio de pop-up.

Referência: https://docs.kick.com/getting-started/generating-tokens-oauth2-flow

## Atualização v7 — Kick sem ngrok

Em **Conexões → Kick → Receber chat e inscrições**, informe o canal, selecione **Conexão direta — sem ngrok** e clique em **Conectar chat**. O programa usa o chat público por WebSocket/Pusher, com confirmação de assinatura, reconexão automática e deduplicação de mensagens. Não exige OAuth para leitura. Uma falha real é mostrada como erro; o programa não troca para simulação automaticamente. O canal e modo são salvos.

A identificação automática usa https://kick.com/api/v1/channels/SEU_CANAL. Se a Kick recusar essa consulta (por exemplo HTTP 403), abra o endereço no seu navegador e copie apenas o número **chatroom.id** para **Opções avançadas → ID da sala**. Não é preciso fornecer cookies ou senha. O transporte depende de interfaces internas da Kick e pode ficar indisponível; **Webhooks** continua como alternativa opcional.

**Para falar no chat**, use a autorização OAuth já configurada, com **chat:write**. Não precisa de Kicklet. O programa envia via API oficial usando o nome da conta autorizada. O aplicativo de desenvolvedor não cria um perfil de bot. Para ter um nome próprio de bot, crie/use uma conta separada da Kick e autorize essa conta; o canal em Receber chat continua sendo o destino. O programa consulta o ID do canal de destino pela API oficial quando necessário.

O envio manual continua na aba Chats. Para mensagens automáticas, ative **Enviar mensagens na Kick** em Conexões → Mensagens automáticas e os eventos desejados (vencedor, prêmio, etc.). Receber mensagens não ativa anúncios. A autorização de envio e a conexão de leitura podem ser desconectadas separadamente.

A integração direta foi implementada a partir da observação do protocolo no projeto de referência enviado pelo usuário, sem copiar seu código: https://github.com/kleanins/kickaway. Envio oficial: https://docs.kick.com/apis/chat.

## Atualização v8 — diagnóstico de autenticação e envio

### Twitch

O gerador twitchapps.com/tmi foi descontinuado e não é mais indicado pelo programa. Em https://twitchtokengenerator.com, use **Custom Scope Token**, selecione **user:read:chat** e **user:write:chat** e autorize a conta desejada. Copie **Access token**; não use Refresh token. O Client ID deve ser o exibido junto desse token, não o Client ID da Kick nem outro aplicativo Twitch.

Cole o Access token no painel e clique em **Identificar Client ID do token**. O programa consulta a validação oficial da Twitch, preenche o Client ID correspondente e informa conta/escopos. Esse botão não salva a credencial nem publica mensagens. Depois use **Salvar credenciais**, **Testar** e **Conectar**. Tokens somente com chat:read/chat:edit (IRC) não atendem ao EventSub.

Apenas HTTP 401 da validação é tratado como token recusado. Falhas de rede, respostas inesperadas e indisponibilidade da Twitch mostram erro de comunicação, sem declarar falsamente que o token foi revogado. Prefixos oauth: e Bearer são normalizados. Ausência de user:read:chat bloqueia a conexão antes de abrir o socket.

### Kick

OAuth autorizado é o estado de **envio**. Se a identificação da sala for recusada com HTTP 403/429, o painel tenta a consulta pública pelo navegador (sem cookies). Se funcionar, o ID é preenchido e a conexão é repetida; se também falhar, o erro orienta o preenchimento manual.

Para receber entradas, clique em **Conectar chat** na seção Receber chat e inscrições e confira se aparece conectado. As mensagens novas aparecem em Chats. Para cadastrar participantes, o sorteio deve estar aberto, as entradas da Kick habilitadas e a palavra-chave precisa corresponder ao texto enviado.

O botão **Enviar mensagem de teste** publica uma mensagem pela conta autorizada e mostra se a Kick confirmou is_sent; falhas informam o estágio/HTTP. Ele não ativa anúncios automáticos. Para anunciar vencedor e prêmios, ative Enviar mensagens na Kick e os eventos correspondentes em Mensagens automáticas. O painel agora mostra quando os anúncios estão desligados.
