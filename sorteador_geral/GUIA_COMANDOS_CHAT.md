# Comandos do chat — Sorteador Geral

## `!pular` (desistir do prêmio)

- Somente o **vencedor atual** pode desistir; a plataforma e, quando disponível, o ID da conta precisam corresponder ao sorteado.
- O comando deve começar com `!` e pode ser renomeado, por exemplo para `!desistir`.
- No painel **Sorteio → Regras de entrada → Comandos do chat**, ative ou desative o comando e escolha o **limite total de desistências por coleta** (1 a 100, padrão 3).
- O limite é compartilhado entre todos os vencedores e reiniciado em **Iniciar coleta**. Um vencedor que desistiu é excluído dos próximos sorteios daquela lista, como no botão administrativo **Pular agora**.
- Quando alguém desiste, o mesmo prêmio volta ao re-sorteio. Quem digitar o comando sem ser o vencedor não interfere.
- O comando é processado **antes** da resposta comum do vencedor para evitar que `!pular` confirme o prêmio ou erre um CAPTCHA.
- Com o limite esgotado, a desistência não ocorre, mas o vencedor ainda pode confirmar normalmente antes do prazo.

## `!nick <personagem>` (consulta MEGAMU)

- Exemplo: `!nick darcherman`.
- Funciona mesmo sem coleta ativa, contanto que o bot possa responder na Twitch/Kick e a opção esteja habilitada.
- Consulta a URL pública `https://megamu.net/getdata.php?char=darcherman&default=SEUNICK`.
- O texto `$(urlfetch ...)` é um atalho do Nightbot. Não precisa colá-lo no nosso painel: o sorteador faz a consulta HTTP diretamente, usando o argumento digitado depois de `!nick`.
- A resposta pública em texto é encaminhada ao chat; **não utiliza** as credenciais `MEGAMU_DV` nem `MEGAMU_KEY` destinadas ao catálogo de prêmios.
- Quando a API responde `[DArcherMan] 400(200rr), HuntLevel: 138`, o bot publica uma confirmação amigável: `✅ DArcherMan existe no MEGAMU! ⚔️ Nível 400 | 🔄 200 RR | 🎯 Hunt 138`.
- Quando a API responde `Player não existente.`, o bot **não** confirma a existência: envia uma mensagem de erro personalizável, como `❌ Espectador: O personagem Nome não existe no MEGAMU.`. Respostas HTTP 200 podem ser negativas.
- Para evitar excesso de requisições: intervalo de 15 segundos por espectador e 3 segundos global entre consultas.
- Se o endpoint estiver indisponível, o bot mostra a mensagem de erro configurada. A API é consultada pelo servidor no momento do comando, e os exemplos acima foram verificados com respostas simuladas conforme as mensagens fornecidas pelo usuário; não foi testada a entrega nos chats reais.

## Mensagens personalizadas

Em **Conexões → Mensagens automáticas**, edite individualmente para Twitch e Kick:

- **Vencedor desistiu pelo chat**: evento `winner_declined`;
- **Limite de desistências atingido**: `winner_skip_limit`;
- **Resposta ao comando de nick MEGAMU**: `nick_lookup`;
- **Erro ao consultar nick MEGAMU**: `nick_lookup_error`.

Campos disponíveis: `{nome}`, `{comando}`, `{usos}`, `{limite}`, `{nick}`, `{resultado}`, `{motivo}` e os campos anteriores do sorteador.

O envio de mensagens exige que o bot esteja habilitado para a plataforma, conectado e autorizado a escrever no chat. Em **modo simulação** não há envio externo.

## `!rank` — histórico de vencedores

- `!rank` retorna o histórico do próprio usuário; `!rank darcherman` consulta outra pessoa na **mesma plataforma** (Twitch ou Kick).
- O comando é configurável (ex.: `!historico`) e pode ser desligado em **Sorteio → Regras de entrada → Comandos do chat**.
- Modelo padrão: `🏆 @{nick} já ganhou {total} vezes, respondeu {respondeu} e mamou {mamou}.`
- Campos personalizáveis: `{nick}`, `{total}`, `{respondeu}`, `{mamou}`, `{desistiu}`, `{pulou}`, `{pendente}`. O evento em Mensagens é **Consulta ao histórico (!rank)**.
- `{mamou}` soma **somente quem deixou o prazo acabar**; não inclui os que usaram `!pular` voluntariamente nem os que o administrador pulou. Essas duas situações aparecem nos contadores opcionais `{desistiu}` e `{pulou}`. Registros antigos com resposta desconhecida ficam em `{pendente}` se não houver auditoria suficiente para classificá-los.
- Os resultados vêm do banco SQLite do próprio sorteador e incluem todas as coletas anteriores, independentemente de a coleta atual estar aberta. Limites de consultas: 10 segundos por usuário e 2 segundos global.
