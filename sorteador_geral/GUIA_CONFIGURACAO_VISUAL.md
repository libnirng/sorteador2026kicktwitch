# Sorteador Geral — Configuração visual do `.env`

Esta atualização mantém o servidor local na porta **8777** e adiciona uma central visual na aba **Conexões**.

## Como aplicar o pacote de atualização

1. Feche a janela do `run.bat` e faça uma cópia de segurança do seu sorteador.
2. Extraia o ZIP de atualização na pasta que contém `sorteador_geral`, substituindo os arquivos solicitados.
3. O pacote **não contém** `.env`, banco de dados ou ambiente virtual. Seus arquivos `dados`, `.env` e `.venv` atuais devem ser preservados.
4. Execute **`Iniciar Sorteador.bat`** (ou `run.bat`) para abrir a central gráfica, que inicia o servidor automaticamente.
5. Quando a janela mostrar **Servidor online**, o painel abrirá no navegador. Pressione **Ctrl+F5** e abra **Conexões**.

### Nova instalação para um cliente

O arquivo `sorteador_cliente_env_visual.zip` é uma instalação limpa, sem banco, tokens, `.env` real ou ambiente virtual de outra máquina. Extraia em uma pasta nova e execute **`instalar.bat`** uma vez para instalar as dependências; depois abra **`Iniciar Sorteador.bat`**. O Windows precisa ter Python 3.10 ou superior e conexão com a internet para a instalação inicial.

**Não use o pacote de cliente limpo para substituir sua instalação atual:** ele começa sem os seus participantes, prêmios e configurações. Use o pacote de atualização para preservar esses dados.

## Nova central gráfica do servidor

- **Iniciar Sorteador.bat**: abre a janela gráfica e inicia o servidor na porta 8777.
- **run.bat**: faz a mesma coisa, para manter o atalho antigo funcionando.
- **run_console.bat**: alternativa técnica para executar pelo console tradicional.
- **Status**: mostra *Iniciando*, *Servidor online*, *Encerrando* e mensagens de erro.
- **Logs em tempo real**: exibem o resultado da inicialização e mensagens do servidor; use **Salvar log** para exportar um arquivo de diagnóstico.
- **Abrir painel**: abre `http://localhost:8777/admin/`.
- **OBS • Sorteio**: copia o link do overlay para a área de transferência.
- **Parar servidor**: solicita encerramento seguro ao processo; ao fechar a janela, o programa pergunta se pode desligar o servidor.

O iniciador impede que um segundo processo seja iniciado na porta 8777 e não tenta encerrar um servidor que já estava em execução fora da janela.

## O que o cliente verá

- Um resumo de **Twitch**, **Kick** e **MegaMu** mostrando o que já foi configurado.
- Botões para salvar cada conjunto de dados diretamente no `.env`, antes de efetuar conexões externas.
- Um controle de **conexões reais / modo simulação**.
- Um checkbox para reconectar automaticamente à Kick quando o servidor iniciar.
- Indicação de token ou chave **salva/pendente**, sem mostrar seu conteúdo.
- Ícones **?** ao lado dos campos da aba **Conexões**. Passe o mouse ou clique para abrir o passo a passo de onde obter cada informação da Twitch, Kick ou MegaMu, com links relevantes. Para usar o teclado, pressione Tab até o **?** e depois Enter.
- A mesma ajuda contextual também aparece nos ajustes mais importantes de **Sorteio**, **Participantes**, **Roleta**, **Anti-bot**, **Chats**, **Mensagens**, **Auditoria**, **Aparência** e **OBS**, explicando efeito das opções e exemplos de uso.

### Twitch

Preencha **Canal**, **Client ID** e **OAuth token**; clique em **Salvar Twitch no .env**.
O token ficará em branco depois de salvar. Clique em **Conectar** para iniciar a conexão.

### Kick — leitura

Informe o canal, escolha **Conexão direta** e clique em **Salvar recepção no .env**.
IDs de sala e canal são opcionais. Selecione **Reconectar ao iniciar** caso queira restaurar a leitura quando o programa for aberto novamente.
Para iniciar imediatamente, clique em **Conectar chat**.

### Kick — envio de mensagens

Informe o **Client ID**, a **Redirect URI** e o **Client Secret**. Clique em **Salvar aplicativo no .env**.
Depois clique em **Autorizar** para gerar os tokens de acesso e renovação automaticamente.

### MegaMu

Preencha **DV**, **Chave da API** e o checkbox de atualização do catálogo. Clique em **Salvar MegaMu no .env** e depois em **Consultar prêmios** para testar.

## Observações de segurança

- O painel não devolve ao navegador tokens, segredos ou chaves salvos. Um campo secreto vazio **mantém** a credencial anterior.
- A API de resumo e os novos comandos de gravação são restritos a acesso local.
- A gravação é atômica e mantém outras variáveis existentes no `.env`.
- **Não compartilhe** seu `.env` real nem backups que contenham credenciais.
- Salvar não implica que a conexão externa funcionou: é preciso usar **Conectar**, **Autorizar** ou **Consultar prêmios** para validar cada serviço.

## Endereços do OBS (inalterados)

- Painel: `http://localhost:8777/admin/`
- Sorteio: `http://127.0.0.1:8777/overlay/sorteio`
- Roleta: `http://127.0.0.1:8777/overlay/roleta`
- Captcha: `http://127.0.0.1:8777/overlay/captcha`
