# Central BP-MS

Página única com os 5 processos do PMO BP-MS:

| Processo | Onde roda |
|---|---|
| Lançar tarefa no ClickUp | Formulário na página + serviço local (motor `lancar_tarefas_clickup.py`) |
| Lançar tarefa no Experience | PC, sync sankhya_integracao |
| Conferência de OS (ClickUp x Experience) | PC, `conferencia_os\Rodar_Conferencia.bat` |
| Envio de Aceite de OSs | PC, `aceite_os\Rodar_Aceite.bat` |
| Agenda semanal | Claude (skill agenda-semanal-parceiros) |

## Serviço local

Uma página web não executa programas do computador. Por isso a Central conversa com `servico/servidor_local.py`, que roda no PC em `http://127.0.0.1:8765`:

- **Lançar no ClickUp:** usa o mesmo motor da tela antiga (`lancar_tarefas_clickup.py`, achado sozinho dentro de `C:\sankhya_integracao`) e grava o mesmo `ultimo_lancamento.json`.
- **Executar / Abrir pasta:** roda os scripts configurados em `C:\sankhya_integracao\central\config_central.json`. Se um caminho estiver vazio ou errado, o serviço abre a janela do Windows para escolher o arquivo e guarda a escolha.
- **Segurança:** só atende pedidos vindos de `https://msfragoso.github.io` e só escuta no próprio PC (127.0.0.1).

Instalação: baixe `servico/Instalar_Central.bat` e `servico/servidor_local.py` para a mesma pasta e dê duplo clique no `.bat`. Ele copia o serviço para `C:\sankhya_integracao\central`, liga agora e cria o atalho na pasta Inicializar do Windows. Log em `C:\sankhya_integracao\central\servidor_local.log`.

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
