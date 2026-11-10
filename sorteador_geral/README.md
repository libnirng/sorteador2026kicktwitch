# Sorteador Geral — Twitch + Kick

Aplicativo local para organizar sorteios em transmissões ao vivo, com painel web, overlays para OBS, participantes da Twitch e Kick, roleta de prêmios, verificação do vencedor e mensagens no chat.

## Funcionalidades

- Coleta de participantes pela Twitch e Kick, com regras de entrada e pesos.
- Painel administrativo para sorteios, prêmios, participantes, histórico e identidade visual.
- Overlays para o OBS: sorteio, roleta de prêmios e CAPTCHA.
- Dez efeitos de suspense com **nomes dos participantes dentro da animação**: roleta, caça-níquel, contagem, cartas, dados, radar, baú, estrelas, portal e holofotes; também há seleção aleatória.
- CAPTCHA do vencedor com tentativas configuráveis (**0 = ilimitadas**).
- Pedido de personagem após o CAPTCHA pelo comando `!nick NomeDoPersonagem` ou `!NomeDoPersonagem`, com retorno de validação.
- Mensagens personalizáveis e modo de simulação para testar o visual sem contas conectadas.

## Requisitos

- **Windows 10/11** para usar o iniciador e os arquivos `.bat` incluídos.
- **Python 3.10 ou superior** e acesso à internet na primeira instalação.
- OBS Studio, se quiser exibir as animações durante a transmissão.
- Contas e autorizações próprias da Twitch/Kick para os recursos de chat ao vivo.

## Instalação no Windows

1. No GitHub, escolha **Code → Download ZIP** e extraia a pasta; ou clone o repositório com Git.
2. Execute `instalar.bat` **uma vez**. Ele cria `.venv` e instala as dependências de `requirements.txt`.
3. Execute `Iniciar Sorteador.bat` (ou `run.bat`) para abrir a central e iniciar o servidor.
4. No navegador, abra `http://localhost:8777/admin/` e configure suas conexões na aba **Conexões**.
5. Teste primeiro no modo de simulação. Em seguida, configure as credenciais das plataformas para usar chat real.

Para execução no console, use `run_console.bat` depois da instalação.

## Endereços para o OBS

Adicione uma **Fonte de navegador** no OBS com a URL desejada:

| Cena | URL |
| --- | --- |
| Sorteio principal | `http://127.0.0.1:8777/overlay/sorteio` |
| Roleta de prêmios | `http://127.0.0.1:8777/overlay/roleta` |
| CAPTCHA legado | `http://127.0.0.1:8777/overlay/captcha` |

O CAPTCHA do vencedor já está integrado à cena principal de sorteio. **Não é necessário adicionar a cena legada ao mesmo tempo**, para evitar sobreposições.

## Configuração e segurança

O arquivo `.env.example` contém **campos vazios**, apenas para referência. As credenciais reais são salvas localmente pelo programa em `.env`, que é ignorado pelo Git.

**Nunca publique no GitHub:**

- `.env` real e outros arquivos de tokens, senhas e chaves de API.
- Pastas `dados/`, backups, bancos de dados e registros privados dos participantes.
- `.venv/`, caches, logs ou arquivos produzidos durante a execução.

> **Importante:** este projeto foi pensado para execução **local**. Não exponha a porta `8777` ou o painel administrativo diretamente na internet sem antes implementar e revisar autenticação, controle de acesso, HTTPS e proteções adequadas. O GitHub hospeda o código, **não** executa automaticamente o bot.

Se atualizar uma instalação existente, preserve seu `.env`, `dados/` e `.venv/`. Recarregue o painel com `Ctrl+F5` e a Fonte de navegador do OBS após substituir os arquivos.

## Organização do código

| Pasta/arquivo | Função |
| --- | --- |
| `servidor/` | API local, sorteios, integrações de chat e persistência |
| `web/admin/` | Painel web de administração |
| `web/overlay/` | Cenas para o OBS |
| `tests/` | Testes de regressão e verificações da interface |
| `docs/` e `GUIA_*.md` | Guias complementares |
| `launcher.py` e arquivos `.bat` | Inicialização no Windows |

## Testes básicos

Com Node.js e as dependências Python instaladas:

```bash
node tests/captcha_integrado.test.cjs
node tests/connection_help.test.cjs
node tests/option_help.test.cjs
python -B tests/verify_two_phase_captcha.py
```

O workflow de integração contínua em `.github/workflows/testes.yml` executa essas verificações no GitHub. Os testes simulados não substituem a conferência das conexões reais na Twitch, Kick e OBS.

## Documentação

- [Guia de instalação e configuração visual](GUIA_CONFIGURACAO_VISUAL.md)
- [Guia de CAPTCHA](GUIA_CAPTCHA_INTEGRADO.md)
- [Guia de comandos do chat](GUIA_COMANDOS_CHAT.md)
- [Histórico das atualizações](LEIA-ME-ATUALIZACAO.md)

Este repositório não inclui um arquivo de licença de código aberto. Defina uma licença somente se desejar conceder direitos de uso, modificação ou distribuição a terceiros.
