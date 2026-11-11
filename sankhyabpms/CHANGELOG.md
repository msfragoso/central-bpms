# Central BP-MS — histórico de versões

Formato da versão: **MAIOR.MENOR.CORREÇÃO** (ex.: 1.2.3)
- **MAIOR**: mudança grande, que muda o jeito de usar ou exige reinstalar.
- **MENOR**: tela ou função nova.
- **CORREÇÃO**: ajustes e correções, sem função nova.

Cada publicação no GitHub ganha uma versão aqui, a mesma no rodapé das telas e
uma etiqueta (tag) `vX.Y.Z` no repositório.

## 1.17.1 — 11/11/2026
- Aceite de OS: a verificação de aceites recusados ou contestados passa a rodar de segunda a sábado, às 08h,
  13h e 17h (antes, só terças e quintas).

## 1.17.0 — 11/11/2026
- Nova tela Liberação GP de Melhores Práticas: lê, nas etapas Validação do escopo e Folha | Validação do escopo
  de uma FAP, os módulos e procedimentos de melhores práticas, e grava, um por vez e só depois da confirmação,
  "MP Completa" com a Liberação GP nos pendentes marcados. Procedimentos já preenchidos, "não se aplica" e do
  cliente ficam de fora. Relê antes e confere depois.
- Nova tela Acompanhamento de Projetos: etapas, módulos concluídos, encerramento e documentos de todos os
  projetos ativos (sem avulsos), com a documentação monitorada por etapa (gerado ou sem documento), alertas
  (etapa vencida, etapa sem documento, Cronograma Sintético faltando), HTML5 para compartilhar e e-mail dos
  alertas novos às 08h. Só leitura.
- Aceite de OS: quadro e e-mail de aceites recusados ou contestados pelo cliente no mês, com as OS, quem
  recusou e o motivo. Verifica às terças e quintas (08h, 13h e 17h) e pelo botão. Só leitura.

## 1.16.0 — 11/11/2026
- Conferência de OS: botão novo "📊 Prazo de apontamento (HTML)". Lê no Sankhya-OM as OS do período e mostra,
  por consultor da unidade, quantos dias passam entre a execução e o fechamento da OS: média em dias úteis e
  corridos, mediana, máximo, % dentro do prazo e média por mês. Gera um HTML5, que pode ser impresso em PDF,
  e um Excel com fórmulas. Lançamentos em planilha não entram. A lista da unidade, o prazo e os feriados
  ficam só no computador. Só leitura.

## 1.15.0 — 10/11/2026
- Chat x OS: aceita o backup de mensagens do Total Chat e passa a medir o tempo ativo de cada atendente pelas
  mensagens que ele escreveu, sem contar o almoço (12h às 14h) nem pausas de mais de 60 minutos sem escrever
  em nenhum chat. Sem o backup do mês, segue o critério anterior. O backup fica só no computador.

## 1.14.0 — 10/11/2026
- Nova tela Chat x OS: cruza os atendimentos do Total Chat com as OS do Sankhya-OM no mês e gera PDF e
  Excel com o tempo de conversa, quanto dele tem OS vinculada, índice de apontamento por atendente,
  evolução semanal e histórico entre meses. Só leitura.
- Aceite de OS: antes do envio, a Central revisa sozinha o texto da Solução com um corretor instalado no
  próprio computador (Instalar_LanguageTool.bat; o texto não sai da máquina) e mostra a aderência da
  Solução ao título e ao Detalhamento da tarefa. A correção aprovada é gravada na OS no Experience e no
  X-Observações OS da tarefa. Tarefas sem boa referência ganham sugestão de título e Detalhamento para
  aprovar. O envio só libera depois da verificação.
- Conferência de OS: apontamentos aguardando o GP passam a ligar na tarefa pela TAG do lançamento original.
- Chamados: Etapa, Status Resolvido (com cores e aviso por e-mail quando muda), Número OS e Data da
  Execução lidos do portal; nova aba Resumo, uma linha por chamado; a leitura não mostra mais a janela.

## 1.13.1 — 09/11/2026
- Sankhya-OM: o login automático agora preenche a senha e clica em Prosseguir sozinho, também na
  tela que já lembra o usuário. Cada tentativa fica registrada, sem usuário nem senha.
- Chamados: mostra o solicitante, o atribuído e as 3 últimas mensagens, com uma cor para cada papel
  (Atendente, Suporte, Solicitante, Você). O aviso de resposta nova diz de quem é.

## 1.13.0 — 06/11/2026
- Nova tela Chamados: acompanha os chamados do portal ajuda.sankhya.com.br (cola um ou vários links,
  exclui quando quiser). Lê o andamento com o login Sankhya ID do navegador da Central, sem abrir abas
  e só leitura: status igual ao do portal, assunto, última resposta e dias sem movimento. Sinais de
  resposta nova, aguardando você, acompanhamento vencido e parado, com cores por status, parceiro em
  etiqueta editável e adiamento com um clique. Leitura automática de hora em hora nos dias úteis (sem
  feriados), aviso no topo das telas e e-mail só com o que é novo. Os chamados ficam só no computador.
- Sync: listas sem número de FAP no nome ficam fora (também na contagem da tela).
- Lançar ClickUp: ícone azul no atalho e no navegador, para não confundir com a Central (verde).

## 1.12.0 — 06/11/2026
- Nova tela Organograma: pessoas da Sankhya por grupo e área (começa com os PO de Produtos), com
  demandas resumidas por área e busca por pessoa, área ou demanda. Os nomes ficam só no computador.
- Lançar ClickUp: destinos específicos por parceiro, fora das listas Avulso (a tarefa nasce como
  subtarefa de uma tarefa pai escolhida). Configurados no próprio computador.
- Conferência de OS: quando o tempo de uma OS muda no Sankhya depois de gravado (ex.: intervalo
  corrigido), o tempo rastreado da tarefa é ajustado, com aviso para conferir no X-Observações OS e o
  arquivo "OS com tempo alterado no Sankhya" na tela. Entrada de tempo lançada à mão não é apagada.
- Organograma e Lançar: a tela avisa quando o serviço ainda está na versão anterior.

## 1.11.0 — 06/11/2026
- Lançar ClickUp, para quem acessa só algumas pastas e listas: o Responsável lista as pessoas das
  tarefas que a conta enxerga (antes vinha só o próprio nome) e a tela abre na hora, com as listas
  guardadas no computador e atualizadas em segundo plano.
- Conferência de OS: a tarefa-gêmea (mais de uma tarefa com a mesma OS) só vale na mesma FAP e com o
  Período dentro do horário da OS; a TAG ID continua decidindo sozinha. O tempo da OS é dividido entre
  as gêmeas pelo Período de cada uma e cada caso é sinalizado para conferir (aviso no X-Observações OS
  e o arquivo "Gêmeas com tempo dividido" na tela).

## 1.10.0 — 05/11/2026
- Aceite de OS: confere todas as FAPs ativas. Além da lista fixa, entram as listas abertas do
  ClickUp e os projetos Em Andamento no Experience (de 34 para 68 FAPs).
- Verificação de Pedidos: filtros Em alerta, Medição, Empreito, Banco de Horas e Todos; a tela e
  o e-mail mostram de onde vem cada dado (pedidos e saldos do Experience, tarefas do ClickUp); o
  botão do OM deixa claro que serve só para ajustar horas.

## 1.9.0 — 05/11/2026
- Sankhya-OM: quando a Central precisa do OM, ela abre a janela, entra com o login do cofre e
  continua sozinha. Faz uma tentativa só e para se o OM pedir qualquer outra coisa ou recusar.
- Credenciais: seção Login do Sankhya-OM. Por padrão usa o mesmo login do Experience, e a senha
  nova gravada vale para os dois.
- Conferência de OS e Ajustar no OM não exigem mais clicar em Conectar antes.

## 1.8.0 — 05/11/2026
- Nova tela Verificação de Pedidos: compara o saldo dos pedidos 110401 e 110501 com as tarefas
  de OS da semana, às 08h e pelo botão, e avisa por e-mail. Pedido que não é Medição é sinalizado.
- Verificação de Pedidos: sem login no Experience, a verificação para em vez de gerar alertas
  falsos, e a checagem das 08h tenta entrar só uma vez por dia.
- Ajustar no OM, na Verificação de Pedidos: só pedido 104 - SERV MEDIÇÃO e só a quantidade, com
  o recálculo do OM e sempre com confirmação. O ajuste no Experience continua manual.
- Nova tela Credenciais: testa e grava a senha do Experience, com aviso de senha expirada em
  todas as telas.
- Sync: botão Parar Sync. Tarefa sem responsável não vai para o Experience. Grupos grandes não
  repetem a alteração de lançamentos que já estão certos.

## 1.7.4 — 04/11/2026
- Lançar ClickUp: quando o ClickUp não libera os nomes da equipe para a conta, o Responsável já
  vem preenchido com o nome da própria pessoa.

## 1.7.3 — 04/11/2026
- Lançar ClickUp, X-Interno: além de Adm / Particular, dá para lançar nas listas Treinamentos e
  Tickets Acompanhamento, direto na lista. A tela mostra só as listas que a conta alcança.

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
