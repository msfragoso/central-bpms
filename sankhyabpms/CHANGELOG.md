# Central BP-MS — histórico de versões

Formato da versão: **MAIOR.MENOR.CORREÇÃO** (ex.: 1.2.3)
- **MAIOR**: mudança grande, que muda o jeito de usar ou exige reinstalar.
- **MENOR**: tela ou função nova.
- **CORREÇÃO**: ajustes e correções, sem função nova.

Cada publicação no GitHub ganha uma versão aqui, a mesma no rodapé das telas e
uma etiqueta (tag) `vX.Y.Z` no repositório.

## 1.7.2 — 04/11/2026
- Instalador e desinstalador do Lançar ClickUp: encerram de verdade o serviço aberto, que antes
  continuava rodando a versão antiga depois de instalar. A Central BP-MS no mesmo computador
  não é encerrada.

## 1.7.1 — 04/11/2026
- Lançar ClickUp: funciona para quem acessa só algumas pastas e listas do PMO BP-MS. Parceiros,
  FAPs, X-Interno e X-Horas Cruzadas passam a usar o que a conta enxerga, e uma lista sem
  nenhuma tarefa não aparece nesse caso. O erro agora mostra o motivo informado pelo ClickUp.

## 1.7.0 — 04/11/2026
- Lançar ClickUp: a atualização online agora é automática. Ao abrir a tela com versão nova,
  ele atualiza e recarrega sozinho. Se a versão não abrir, volta para a anterior e só tenta
  essa versão de novo com o clique em "Atualizar agora". Na Central segue com o botão.

## 1.6.1 — 04/11/2026
- Lançar ClickUp: a atualização online agora baixa o pacote anexado à versão (Release) no
  GitHub. O anexo é criado automaticamente ao publicar uma versão que muda o Lançar.

## 1.6.0 — 04/11/2026
- Atualização online, na Central e no pacote Lançar ClickUp: ao abrir a tela, aparece
  "Atualizar agora" quando há versão nova no GitHub. Com a confirmação, baixa e confere o
  pacote, guarda cópia da versão atual e reinicia. Se a nova não abrir, volta sozinha.
- Pacote Lançar ClickUp: publicado em `pacote-lancar/`, sem nomes, e-mails ou parceiros. A
  lista de parceiros agora vem do ClickUp, com o token de quem usa.
- Quem está em versão anterior precisa instalar a 1.6.0 à mão uma última vez.

## 1.5.0 — 04/11/2026
- Conferência de OS: com o login feito e a Consulta de OS pronta, a janela do Sankhya-OM
  some da tela e da barra de tarefas, e a consulta continua aberta. Ela volta sozinha
  quando precisar de login ou da sua ação.
- Botão "Mostrar janela" / "Ocultar janela do Sankhya-OM" na Conferência.
- A Central responde "Não" sozinha ao aviso "Restaurar telas" do OM, só na janela dela.

## 1.4.0 — 04/11/2026
- Início: cartões só com o nome e o ícone do módulo, e o cartão inteiro abre a tela. A
  explicação e o último uso ficam dentro de cada tela; "ou pelo Claude" foi para a tela
  da Agenda.
- Ícones nos módulos, nos atalhos do Início e no menu do topo.
- Sync: consultor fora do projeto é cadastrado automaticamente, o sync roda de novo só
  para aquela FAP e o resultado aparece na tela e no log. O que não der certo fica na
  tela com o motivo e "Tentar de novo".
- Agenda semanal: "Agenda fixa" também não aparece como tarefa pai no e-mail.

## 1.3.1 — 03/11/2026
- Agenda semanal: o e-mail mostra a tarefa pai numa etiqueta acima da subtarefa, em
  "Resumo da Demanda". Não aparece quando o pai é Atendimento Base, mês (ex.: 2026-10
  Outubro) ou quando só repete o nome da subtarefa.
- Conferência de OS: a janela do OM que ficava atrás da tela é minimizada depois de
  conectar, e volta ao normal quando precisa de login.

## 1.3.0 — 28/10/2026
- Nova tela **Conferência Planilhas**: cruza as tarefas do ClickUp com Apontamento de
  planilha (Bonificado, Planilha - Serviços, Treinamento, Faturado) com a PLANILHA DE
  HORAS de cada consultor no Drive. Aponta horário/cliente diferente, falta na planilha,
  sem tarefa no ClickUp, conflito de horário e lançamento duplicado com OS (pelo horário
  do X-Observações OS).
- Relatório HTML5/PDF da Conferência Planilhas: 1ª página com o resumo de horas por
  consultor (ClickUp, planilha, diferença, conflito com OS e Horas Confirmadas), linha do
  consultor que expande os detalhes, e relatório separado dos Apontamentos travados
  (aba do ciclo da Fase 3) por consultor.
- "Fechar planilhas": preenche a OBS (Roboto 11, vermelho negrito; VISTO - data sem
  amarelo, alertas com a linha amarela), mantém o texto manual e a data do primeiro
  VISTO, e pergunta se cria a aba vazia do próximo ciclo (datas dd/mm/aaaa e abas
  ocultas preservadas; cópia de segurança antes de gravar).
- Conferência de OS: tarefa concluída só sai da conferência com OS Sankhya e tempo
  rastreado; sem OS para casar volta para "não iniciado" (só Apontamento OS Experience
  ou "(Apontamento OS)"). Pergunta se recria e vincula a tarefa quando ela foi excluída
  do ClickUp, e confere o campo OS Sankhya no ClickUp inteiro antes de listar sobra.
- Apontamentos travados (Fase 3): botões "Ciclo atual" e "Ciclo anterior".
- Início: botão "Organizar módulos" para arrastar os cartões; a ordem vale também para
  o menu do topo.
- Sync: modelo 63 (RH - 2a Fase) e módulo Distribuição na Trilha do Sucesso.

## 1.2.0 — 23/10/2026
- Nova tela **Backlog Base**: tarefas do PMO BP-MS por status (padrão Backlog Base),
  agrupadas por Agendamento, filtros por status, parceiro e responsável, ordenação por
  coluna e botão "Relatório HTML5" (arquivo único para guardar, enviar ou imprimir).
- Até 3 processos ao mesmo tempo na Central (os que mexem no mesmo sistema continuam
  um de cada vez); a pílula do topo mostra quantos estão rodando.
- Data da última atualização de cada módulo nos cartões e nas telas.
- Lançar ClickUp: X-Horas Cruzadas com busca só da tarefa pai (nome ou código do
  parceiro) e título "lista (parceiro curto) - título", com o nome curto editável e
  guardado por tarefa pai; parceiro X-Interno (lista Adm/Particular, tarefa do mês
  criada sozinha, Agenda Interno e Apontamento Ajuste Administrativo).
- Sync: seleção de vários consultores na mesma rodada.

## 1.1.0 — 21/10/2026
- Lançar ClickUp: campos 1, 2, 3, 4 (Usuário cliente) e 8 obrigatórios, com * vermelho;
  confirmação avisa quais campos opcionais ficaram vazios ("Lançar assim mesmo").
- Lançar ClickUp: anexar arquivos na tarefa (vários, somando a cada escolha ou
  arrastando, até 25 MB), enviados pelo anexo nativo do ClickUp.
- Rodapé de todas as telas com a versão ("by MarceloFragoso · vX.Y.Z") e este CHANGELOG.

## 1.0.0 — 21/10/2026
Primeira versão numerada (marca tudo o que foi publicado até o commit 9c43dab):
- Telas: Início, Lançar ClickUp, Sync tarefa ClickUp ⇄ Experience (com filtro por
  consultor), Conferência de OS (OM + travados do Experience + WhatsApp), Apontamentos
  travados (Fase 3 + relatório do ciclo), Aceite de OS (por OS, VERIFICAR, Solução),
  Agenda semanal, Atendimentos WhatsApp, Permissões ClickUp.
- Serviço local com módulos configuráveis e pacote "só Lançar ClickUp".
