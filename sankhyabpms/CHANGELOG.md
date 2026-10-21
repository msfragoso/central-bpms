# Central BP-MS — histórico de versões

Formato da versão: **MAIOR.MENOR.CORREÇÃO** (ex.: 1.2.3)
- **MAIOR**: mudança grande, que muda o jeito de usar ou exige reinstalar.
- **MENOR**: tela ou função nova.
- **CORREÇÃO**: ajustes e correções, sem função nova.

Cada publicação no GitHub ganha uma versão aqui, a mesma no rodapé das telas e
uma etiqueta (tag) `vX.Y.Z` no repositório.

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
