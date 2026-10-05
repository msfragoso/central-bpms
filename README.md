# Central BP-MS

Página única com os 5 processos do PMO BP-MS:

| Processo | Onde roda |
|---|---|
| Lançar tarefa no ClickUp | Claude (skill lancar-tarefas-clickup) |
| Lançar tarefa no Experience | PC, sync sankhya_integracao |
| Conferência de OS (ClickUp x Experience) | PC, `conferencia_os\Rodar_Conferencia.bat` |
| Envio de Aceite de OSs | PC, `aceite_os\Rodar_Aceite.bat` |
| Agenda semanal | Claude (skill agenda-semanal-parceiros) |

## Como os botões verdes rodam scripts locais

Uma página web não pode executar programas do computador. Os botões verdes usam o endereço `bpms://<ação>`, que o `instalador/Instalar_Central.bat` registra no Windows (só para o usuário, sem administrador). O Windows entrega o link ao `central_handler.ps1`, que roda **apenas** os programas listados em `C:\sankhya_integracao\central\acoes.json`. Qualquer outra ação é recusada.

Para mudar o caminho de um processo, edite `acoes.json` ou apague a entrada: o handler pergunta o arquivo no próximo clique.

## Publicação

GitHub Pages servindo a raiz do branch `main`. Lembrete: o site do GitHub Pages é público mesmo quando o repositório é privado. A página não guarda senha nem dado de cliente.

## Login (Firebase Authentication)

A Central abre numa tela de e-mail e senha. Quem confere é o Firebase, e o login fica salvo no navegador até clicar em Sair. Não há cadastro pela página: só entra quem você criar no console.

1. Em https://console.firebase.google.com crie um projeto (plano gratuito).
2. Authentication > Começar > Método de login: ative **E-mail/senha**.
3. Authentication > Usuários > Adicionar usuário: crie um acesso para cada pessoa.
4. Authentication > Configurações > Domínios autorizados: adicione `<seu-usuario>.github.io`.
5. Configurações do projeto > Seus apps > Web (`</>`): registre o app e copie `apiKey`, `authDomain`, `projectId` e `appId` para `firebase-config.js`.

Esses valores são públicos por natureza e podem ir no repositório. Observação: o login esconde a Central, mas o HTML continua acessível a quem souber o endereço; por isso a página não deve conter senhas nem dados de cliente.
