# Central BP-MS

Telas HTML5 com layout padrão para os processos do PMO BP-MS. Todo o código fica em `sankhyabpms/` (detalhes em `sankhyabpms/LEIA-ME.md`).

| Processo | Tela |
|---|---|
| Lançar tarefa no ClickUp | `lancar.html` |
| Sync tarefa ClickUp ⇄ Experience | `sync.html` |
| Conferência de OS | `conferencia.html` |
| Apontamentos travados (Fase 3) | `fase3.html` |
| Aceite de OS | `aceite.html` |
| Agenda semanal | abre no Claude (skill agenda-semanal-parceiros) |

## Serviço local

Uma página web não executa programas do computador. As telas conversam com `sankhyabpms/servico/servidor.py`, que roda no PC em `http://127.0.0.1:8766` e usa os motores de `C:\sankhya_integracao` (caminho em `config.json`, chave `pasta_motores`). Credenciais continuam no Gerenciador de Credenciais do Windows.

- Abrir: atalho "Central BP-MS (HTML5)" na Área de Trabalho, ou `C:\sankhyabpms\Iniciar_Central.vbs`.
- Segurança: só escuta no próprio PC e só atende páginas servidas por ele mesmo ou por `https://msfragoso.github.io`. Toda ação que envia ou altera dados exige confirmação.
- As mesmas telas abrem pelo site do GitHub (com login) ou direto em `http://127.0.0.1:8766` (sem login, só no próprio PC).

## Publicação

GitHub Pages servindo a raiz do branch `main`; a raiz redireciona para `sankhyabpms/web/`. Lembrete: o site do GitHub Pages é público mesmo quando o repositório é privado. A página não guarda senha nem dado de cliente.

## Login (Firebase Authentication)

A Central abre numa tela de e-mail e senha. Quem confere é o Firebase, e o login fica salvo no navegador até clicar em Sair. Não há cadastro pela página: só entra quem você criar no console.

1. Em https://console.firebase.google.com crie um projeto (plano gratuito).
2. Authentication > Começar > Método de login: ative **E-mail/senha**.
3. Authentication > Usuários > Adicionar usuário: crie um acesso para cada pessoa.
4. Authentication > Configurações > Domínios autorizados: adicione `<seu-usuario>.github.io`.
5. Configurações do projeto > Seus apps > Web (`</>`): registre o app e copie `apiKey`, `authDomain`, `projectId` e `appId` para `sankhyabpms/web/assets/firebase-config.js`.

Esses valores são públicos por natureza e podem ir no repositório. Observação: o login esconde a Central, mas o HTML continua acessível a quem souber o endereço; por isso a página não deve conter senhas nem dados de cliente.
