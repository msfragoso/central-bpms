# Central BP-MS (HTML5)

Todas as telas do PMO em HTML5, com layout padrão, servidas por um serviço local
em Python (sem pacote extra para instalar).

## Como abrir

Duplo clique em **`Iniciar_Central.vbs`**. O serviço sobe em
`http://127.0.0.1:8766/` e o navegador abre na página inicial. Se já estiver
rodando, só abre a página.

## Telas

| Tela | Página | Motor usado (sem alteração) |
|---|---|---|
| Lançar tarefa no ClickUp | `lancar.html` | `clickup_tasks/lancar_tarefas_clickup.py` |
| Sync tarefa ClickUp ⇄ Experience | `sync.html` | `main.py` (`_fluxo_principal`) + `clickup_sync/` |
| Conferência de OS + Borracha | `conferencia.html` | `conferencia_os/` (dados, motor, html, clickup) |
| Apontamentos travados (Fase 3) | `fase3.html` | `conferencia_os/fase3_prazo_retroativo.py` |
| Aceite de OS | `aceite.html` | `aceite_os/enviar_aceite_os.py` |

## Conferência sem exportar CSV

Na Conferência de OS (e na Borracha), a opção **Buscar direto do ClickUp** lê a
visualização "Visão para IA" pela API (`servico/clickup_visao.py`) e gera o
mesmo CSV da exportação manual, no período da tela. Os filtros (Apontamento,
Agenda, responsável) são lidos da própria visualização; só o período da
visualização é trocado pelo da conferência. O CSV gerado fica em
`dados/clickup/` e aparece para baixar no fim. A opção de enviar o CSV continua.

## Conferência pelo Sankhya-OM (todas as FAPs)

Em "Apontamentos das OS", a opção **Sankhya-OM** lê as OS da tela "Consulta de OS"
do OM (período + executantes + tempo gasto > 0), inclusive de FAPs de outras BPs
(horas cruzadas). O login é **assistido**: "Conectar ao Sankhya-OM" abre uma janela
do Chrome só da Central (perfil em `dados/om_perfil`) na página oficial do OM, e o
usuário faz o login; a Central não imita o login do OM. Depois do login a Central
abre a Consulta de OS (`system.jsp#app/<ID da tela em base64>`) e usa a sessão dela
só para leitura (`servico/om_sessao.py`, `servico/app_om.py`).

- **TAG ID:** com a caixa marcada, cada OS do OM recebe a TAG ID ([ClickUp:id]) do
  lançamento do Experience (OS -> sub-tarefa da OS -> lançamento), e a Fase 1 casa
  pela TAG ID. O que ficar sem TAG ID segue a comparação por data/parceiro/consultor/horário.
- **Horas cruzadas:** o parceiro sai da subtarefa pai "Nome (código do parceiro)",
  ligado ao CODPARC das OS do OM (regra no motor, `conferencia_os/motor_conferencia.py`).
- **PDF:** depois da conferência, "Gerar PDF do relatório" converte o HTML em PDF
  (A4 paisagem) com o Chrome do PC (`servico/pdf_relatorio.py`).

## Lançamentos sem apontamento de OS

Na tela do Sync: lista os lançamentos PENDING (sem OS) do Experience no período,
só de projetos Em Andamento, com opção de excluir os marcados (só no Experience;
o ClickUp não é alterado). Cada exclusão fica em `log_exclusoes_orfaos.jsonl`.

## Agenda semanal dos parceiros

Tela "Agenda semanal" (`web/agenda.html`, `servico/app_agenda.py`): lê a
visualização "Agrupado p/Enviar" do ClickUp (próxima semana), aplica as regras da
skill (sem "Planejamento", sem tarefas da gestão interna, X-Horas Cruzadas,
X-Interno e Energe desmarcados), casa os parceiros com a planilha de contatos
(`G:\Meu Drive\PROJETOS\Contatos(e-mails) dos Parceiros para Envio de Agenda.xlsx`),
mostra a prévia no layout aprovado (`servico/agenda_layout.py`, copiado da skill) e
envia pelo Gmail com a senha de app do cofre do Windows (chave GMAIL_APP_PASSWORD).
"Enviar teste para mim" manda só para o remetente; o envio real pede confirmação e
fica registrado em `dados/agenda_envios.jsonl`.

Erros do serviço (que roda sem janela) ficam em `dados/servico.log`.

## Editar os textos das telas

Botão **✎** no topo de qualquer tela: os títulos, descrições e itens do menu
ficam com contorno tracejado. Clique, escreva e use **Salvar textos**.
"Restaurar padrão" volta ao texto original. Os textos ficam em
`dados/textos.json`; o código das páginas não muda.

## Onde ficam as coisas

- `config.json`: `pasta_motores` (hoje `C:\sankhya_integracao`) e `porta` (8766,
  para não conflitar com o servidor_local da 8765). Quando os motores mudarem de
  pasta, troque só `pasta_motores`.
- Credenciais: as mesmas de sempre, no Gerenciador de Credenciais do Windows
  (`credenciais.py` / `configurar_credenciais.py`).
- Saídas: continuam onde os motores sempre gravaram (logs, xlsx, csv, jsonl,
  relatório em `C:\Conferencia OS`). Cada processo mostra botões para baixar ou
  abrir os arquivos que gerou.
- `dados/`: só a memória desta Central (último lançamento, último uso, uploads
  do CSV/Excel da conferência).

## Segurança

- Só atende a própria máquina (127.0.0.1) e recusa chamadas de outros sites.
- Toda ação que envia ou altera dados (lançar tarefa, atualizar ClickUp,
  Borracha, envio para a planilha, aceite, sync) pede confirmação na tela, e o
  serviço recusa a ação sem essa confirmação.
- Um processo longo por vez. Se fechar a aba no meio, ao abrir a tela de novo
  ela volta a acompanhar o processo.

## Telas antigas

As telas Tkinter e os .bat em `C:\sankhya_integracao` continuam funcionando.
Nada foi alterado lá.
