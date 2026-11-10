# Configuração do ngrok para Webhooks da Kick

## O que é o ngrok?

O ngrok é um túnel que cria um endereço HTTPS público para seu computador local,
permitindo que a Kick envie webhooks para seu sorteador sem precisar de servidor
na nuvem ou configuração de rede complexa.

## Por que preciso do ngrok?

A Kick envia webhooks para uma URL pública HTTPS. Como seu sorteador roda no
computador local (localhost), ele não é acessível pela internet. O ngrok cria
um "túnel" seguro entre seu computador e uma URL HTTPS pública.

## Configuração (uma vez só)

### 1. Crie uma conta no ngrok

Acesse https://ngrok.com e crie uma conta gratuita.

### 2. Baixe o ngrok

Acesse https://ngrok.com/download e baixe a versão para Windows.

### 3. Extraia o ngrok

Extraia o arquivo ZIP para uma pasta. Recomendamos:
- `C:\Tools\ngrok\ngrok.exe`

### 4. Adicione ao PATH do Windows

1. Pressione `Win + R`, digite `sysdm.cpl` e pressione Enter
2. Vá em "Avançado" > "Variáveis de Ambiente"
3. Em "Variáveis do Sistema", procure "Path" e clique em "Editar"
4. Clique em "Novo" e adicione o caminho onde está o ngrok.exe
5. Exemplo: `C:\Tools\ngrok`

### 5. Configure seu authtoken

1. Acesse https://dashboard.ngrok.com/tokens para ver seu token
2. Abra o Prompt de Comando (cmd.exe)
3. Execute:
   ```
   ngrok config add-authtoken SEU_TOKEN_AQUI
   ```

Isso configura o ngrok para usar sua conta. O authtoken fica salvo
no arquivo de configuração do ngrok, não neste programa.

## Uso no Sorteador

Após configurar o ngrok uma vez:

1. Execute `run.bat` normalmente
2. O sorteador inicia e mostra informações sobre o ngrok
3. Abra o painel admin (http://localhost:8765)
4. Vá em "Chats" > "Kick"
5. Clique em "Conectar ngrok"
6. Use a URL gerada para configurar o webhook na Kick API

## Perguntas Frequentes

### O ngrok é seguro?

Sim! O túnel é criptografado com TLS. Apenas a Kick pode enviar dados
para sua URL ngrok. Você pode verificar isso na documentação do ngrok.

### Preciso pagar pelo ngrok?

Não! A conta gratuita funciona perfeitamente para webhooks.
A versão gratuita oferece:
- 1 túnel simultâneo
- URLs aleatórias (mudam a cada reinicialização)
- 60 conexões/minuto

Para uso básico de webhooks, isso é mais que suficiente.

### O que acontece se eu fechar o computador?

O túnel ngrok fecha junto. Você precisará reconectar quando
abrir o sorteador novamente.

### Posso usar outro serviço?

Você pode usar qualquer túnel que redirecione para localhost:8766.
Alternativas incluem localtunnel, serveo, etc. Mas o ngrok é
o mais confiável e bem documentado.

## Solução de Problemas

### "ngrok não encontrado"

O ngrok não está no PATH do Windows. Revise o passo 4.

### "ngrok sem authtoken configurado"

Execute o comando do passo 5 com seu token correto.

### "Timeout ao iniciar ngrok"

Verifique sua conexão com a internet.

## Links Úteis

- Site do ngrok: https://ngrok.com
- Documentação: https://ngrok.com/docs
- Dashboard (tokens): https://dashboard.ngrok.com/tokens
