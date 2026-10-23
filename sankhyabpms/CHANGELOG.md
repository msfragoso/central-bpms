# Central BP-MS — histórico de versões

Formato da versão: **MAIOR.MENOR.CORREÇÃO** (ex.: 1.2.3)
- **MAIOR**: mudança grande, que muda o jeito de usar ou exige reinstalar.
- **MENOR**: tela ou função nova.
- **CORREÇÃO**: ajustes e correções, sem função nova.

Cada publicação no GitHub ganha uma versão aqui, a mesma no rodapé das telas e
uma etiqueta (tag) `vX.Y.Z` no repositório.

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
