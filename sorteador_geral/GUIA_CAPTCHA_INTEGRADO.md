# CAPTCHA integrado ao sorteador — OBS

O CAPTCHA agora abre automaticamente no centro do **mesmo overlay do sorteador**, com o painel de participantes e prêmios escurecido ao fundo. Não é necessário alternar cenas, controlar duas fontes ou abrir um segundo endereço.

## Configurar no OBS

1. Inicie o servidor normalmente pelo lançador do Sorteador Geral.
2. No OBS, adicione uma **Fonte de navegador**.
3. Use a URL `http://127.0.0.1:8777/overlay/sorteio`.
4. Recomenda-se largura **1920** e altura **1080** (ou **1280 × 720** para uma cena HD).
5. Se havia uma fonte antiga apontando para `/overlay/captcha`, **oculte ou remova aquela fonte** para não duplicar o desafio na tela.
6. Se o OBS exibir o visual anterior, clique em **Atualizar cache da página atual** nas propriedades da fonte.

## O que acontece durante a transmissão

| Situação | Exibição na mesma fonte do OBS |
|---|---|
| Sorteio aberto | Tela de participantes e prêmios, como antes |
| Vencedor sem CAPTCHA | Tela padrão do vencedor e contador até a primeira fala no chat |
| Vencedor marcado para CAPTCHA | Inicialmente, apenas tela de vencedor e contador de presença; **não mostra o código ainda** |
| Primeira fala do vencedor marcado | Encerra imediatamente o contador e **só agora** gera o desafio; painel escurecido e código centralizado, sem novo relógio |
| Código incorreto | Exibe a resposta certa, sem contagem regressiva. O vencedor fica pendente de decisão manual: confirmar, gerar novo código ou pular |
| Código correto | Confirmação de vitória por cerca de 2,4 segundos; depois retorna ao painel |
| Ninguém falou antes de acabar o prazo | Aviso de tempo esgotado; o servidor decide o próximo sorteio conforme a configuração de avanço |

O vencedor responde no **chat da Twitch ou da Kick**, na plataforma em que foi sorteado. A **primeira mensagem** (qualquer frase que não seja um comando do bot) confirma a presença, independentemente de ser igual ao futuro código. Se o vencedor foi marcado para CAPTCHA, a **segunda mensagem** é verificada contra o desafio apresentado somente após a primeira. A interface não recebe respostas diretamente; ela exibe o resultado do servidor. O prêmio só é confirmado automaticamente se a resposta ao código estiver certa. Em caso de erro, o organizador pode usar os controles da aba Antibot.

O endereço antigo `/overlay/captcha` permanece funcionando para compatibilidade, mas seu contador foi corrigido. Para clientes novos, use apenas `/overlay/sorteio`.

## Verificação técnica

Execute `node tests/captcha_integrado.test.cjs` para conferir os estados da interface, inclusive presença, código sem cronômetro, erro e acerto, sem subir um servidor.

O teste de navegador completo fica em `tests/browser_captcha_integrado.py`; requer Chromium com suporte ao Playwright e permissões para abrir um navegador local.
