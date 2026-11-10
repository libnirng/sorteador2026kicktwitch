# Conectar os chats

Use a aba **Conexões** para configurar as plataformas. A aba **Chats** mostra conversas, filtros, sons e menções.

## Twitch

Configure Client-ID e User Access Token com user:read:chat. Para enviar mensagens, inclua user:write:chat. A mesma autorização atende leitura e envio.

## Kick sem ngrok

Em Receber chat e inscrições, informe o canal, mantenha Conexão direta e clique em Conectar chat. Não precisa de OAuth para leitura. Se a identificação automática falhar, preencha chatroom.id em Opções avançadas. A conexão depende do chat público usado pelo site da Kick.

Para enviar, autorize sua conta com chat:write. As mensagens usam o nome da conta autorizada; uma conta de bot separada é opcional. Não precisa de Kicklet.

## Kick por webhooks (alternativa)

Selecione Webhooks para exibir OAuth, túnel ngrok e assinaturas. Cadastre a Redirect URI exatamente como aparece no programa; conecte o túnel, cadastre a URL pública do webhook no aplicativo da Kick, habilite webhooks e crie a assinatura chat.message.sent.

## Anúncios

Em Mensagens automáticas, ative o envio por plataforma e os eventos desejados. Receber chat não ativa anúncios. O envio manual também não ativa mensagens automáticas.

Veja LEIA-ME-ATUALIZACAO.md para instalação, OBS, testes e detalhes.
