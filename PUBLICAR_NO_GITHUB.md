# Como publicar o Sorteador Geral no GitHub

**Esta versão já inclui** `README.md`, `.gitignore`, `.env.example` e testes automáticos. O projeto deve ser enviado como **código-fonte**, não como o arquivo ZIP inteiro dentro do repositório.

## Opção 1 — GitHub Desktop (mais simples no Windows)

1. Extraia o ZIP `sorteador_geral_github_v27.zip` em uma pasta no PC.
2. Abra o [GitHub Desktop](https://desktop.github.com/) e faça login na sua conta.
3. Escolha **File → Add local repository**, selecione a pasta `sorteador_geral`. Se aparecer a opção para criar o repositório ali, confirme.
4. Confira a lista de arquivos modificados. **Não deve aparecer `.env`, pasta `dados`, banco de dados nem tokens.**
5. Escreva um resumo, por exemplo `Versão inicial do Sorteador Geral`, e clique em **Commit to main**.
6. Clique em **Publish repository**. Recomendo marcar **Keep this code private** inicialmente. Depois é possível mudar a visibilidade.

## Opção 2 — linha de comando (Git)

1. Crie no [GitHub](https://github.com/new) um repositório vazio chamado, por exemplo, `sorteador-geral`. Não selecione README ou `.gitignore` na criação; eles já estão no pacote.
2. Extraia o ZIP e abra o **Git Bash** dentro da pasta `sorteador_geral`.
3. Execute os comandos abaixo, substituindo `SEU_USUARIO` pelo seu usuário do GitHub:

```bash
git init -b main
git add .
git status
git commit -m "Versão inicial do Sorteador Geral"
git remote add origin https://github.com/SEU_USUARIO/sorteador-geral.git
git push -u origin main
```

Antes do `git commit`, inspecione o `git status` e interrompa se algum arquivo privado estiver listado.

## Cuidados

- **Não publique credenciais:** o `.env.example` deve ficar no GitHub, mas o `.env` real não.
- **Não publique informações pessoais:** arquivos da pasta `dados/`, bancos, históricos e logs devem ficar somente no seu computador.
- **Não confunda GitHub com hospedagem:** o repositório guarda o código. O servidor Python, a conexão com Twitch/Kick e as cenas do OBS continuam rodando no computador que executa o Sorteador.
- **Não exponha o painel administrativo:** a aplicação foi preparada para rede local; publicar a interface ou a API na internet exige proteção e revisão de segurança adicionais.
- **Licença:** o pacote não define uma licença de código aberto. Se decidir disponibilizar o projeto para terceiros reutilizarem, escolha uma licença conforme sua intenção.

Depois da publicação, o GitHub executará o workflow **Verificações básicas** na aba **Actions**. Ele testa a lógica local, não as conexões reais com Twitch, Kick e OBS.
