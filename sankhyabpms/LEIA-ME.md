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
