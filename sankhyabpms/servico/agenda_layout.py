# -*- coding: utf-8 -*-
"""
Layout aprovado do e-mail "Confirmação da Agenda de Serviço", copiado sem
alteração da skill agenda-semanal-parceiros (scripts/build_emails.py, 07/10/2026):
cores do ClickUp por parceiro, cor da linha pela Agenda, templates do cartão.
Se o layout mudar na skill, atualize aqui também.
"""
WEEKDAY_ABBR = {
    "segunda-feira": "Seg",
    "terça-feira": "Ter",
    "quarta-feira": "Qua",
    "quinta-feira": "Qui",
    "sexta-feira": "Sex",
    "sábado": "Sáb",
    "domingo": "Dom",
}

# Row styling rules per "Agenda" value
ROW_STYLES = {
    "Presencial no Cliente": {"bg": "#FB923C", "fg": "#3A1D00", "border": "#EA7C1E"},   # laranja
    "Remoto":                {"bg": "#5B9BD5", "fg": "#FFFFFF", "border": "#3E7CB1"},   # azul médio
    "Presencial na Unidade Sankhya": {"bg": "#F472B6", "fg": "#4A0625", "border": "#DB2777"},  # rosa
    "Interno":                {"bg": "#F1F5F9", "fg": "#1a202c", "border": "#e2e8f0"},
    "":                        {"bg": "#F1F5F9", "fg": "#1a202c", "border": "#e2e8f0"},
}

# Valores de "Agenda" que nunca devem aparecer no e-mail (filtrados antes de montar a tabela)
AGENDA_EXCLUIR = {"Planejamento"}

def style_for(agenda):
    return ROW_STYLES.get(agenda.strip(), ROW_STYLES[""])

CLICKUP_PARTNER_COLORS = {
    "Agrosalles": "#b6b6ff",
    "Almont": "#667684",
    "Ambient": "#07271e",
    "Amidos Nevada": "#AF7E2E",
    "Balcater": "#1bbc9c",
    "BCM": "#0231E8",
    "BioLimp": "#81B1FF",
    "Biomed MS": "#1bbc9c",
    "Biomed SP": "#1bbc9c",
    "Brasol": "#AF7E2E",
    "Central Embalagens": "#0231E8",
    "CG Telhas": "#3082B7",
    "Click TI": "#e9c162",
    "CLM": "#800000",
    "Contrafo": "#ded744",
    "DSF": "#1bbc9c",
    "Energe": "#9b59b6",
    "Germipasto": "#06b84f",
    "Germisul": "#2ecd6f",
    "GP Embalagens": "#ff7800",
    "Grande Aço": "#D5331C",
    "Guatos": "#001736",
    "Guri": "#AF7E2E",
    "Iccap": "#42874c",
    "Inovvati": "#376403",
    "Lider Soluções": "#96c7f2",
    "LPADV": "#AF7E2E",
    "Megadrone": "#f9d900",
    "MegaTrucks": "#3082B7",
    "Mix Nutri": "#22388b",
    "MS Diagnóstica": "#5C0EF0",
    "MS Energy": "#d6973f",
    "NEO": "#0231E8",
    "Netcia": "#02BCD4",
    "Neurosoft": "#C65446",
    "Nfoods": "#af4545",
    "Origem": "#aec0f5",
    "Perfilferros": "#0231E8",
    "Porto Plast": "#FF7FAB",
    "Pro-Info": "#800000",
    "Projebio": "#8dcec3",
    "Projesul": "#6647f0",
    "Quimisul": "#3397dd",
    "Semalo": "#d86b30",
    "SF-Formas": "#103117",
    "Soldamaq": "#d01414",
    "Sorpack (HPA)": "#ff7800",
    "Toposat": "#7cba6e",
    "Topparfum": "#FF4081",
    "Vo Erminia": "#97D594",
    "Volpini": "#AF7E2E",
}


CARD_ONLY_TEMPLATE = '''
<table role="presentation" width="680" cellpadding="0" cellspacing="0" style="background-color:#ffffff; border-radius:10px; overflow:hidden; box-shadow:0 1px 4px rgba(0,0,0,0.08); font-family:Arial, Helvetica, sans-serif;">

  <tr>
    <td style="padding:20px 24px 6px 24px;">
      <p style="margin:0 0 4px 0; font-size:15px; color:#1f2a44; font-weight:bold;">
        Olá, equipe <span style="color:{cor};">{parceiro}</span>!
      </p>
      <p style="margin:0; font-size:14px; color:#4a5568; line-height:1.5;">
        Segue abaixo a agenda de atendimentos confirmados para a semana de <strong>{data_ini} a {data_fim}</strong>.
      </p>
    </td>
  </tr>

  <tr>
    <td style="padding:18px 24px 24px 24px;">
      <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;">
        <tr style="background-color:#1f2a44;">
          <th align="left" style="padding:10px; color:#ffffff; font-size:12px; border:1px solid #1f2a44; width:28px;">#</th>
          <th align="left" style="padding:10px; color:#ffffff; font-size:12px; border:1px solid #1f2a44;">Consultor</th>
          <th align="left" style="padding:10px; color:#ffffff; font-size:12px; border:1px solid #1f2a44;">Resumo da Demanda</th>
          <th align="left" style="padding:10px; color:#ffffff; font-size:12px; border:1px solid #1f2a44;">Data</th>
          <th align="left" style="padding:10px; color:#ffffff; font-size:12px; border:1px solid #1f2a44;">Período</th>
          <th align="left" style="padding:10px; color:#ffffff; font-size:12px; border:1px solid #1f2a44;">Usuário Cliente</th>
          <th align="left" style="padding:10px; color:#ffffff; font-size:12px; border:1px solid #1f2a44;">Agenda</th>
        </tr>
        {rows}
      </table>
    </td>
  </tr>

  <tr>
    <td style="padding:0 24px 24px 24px;">
      <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background-color:#FFF7ED; border:1px solid #FDBA74; border-radius:6px;">
        <tr><td style="padding:12px 14px; font-size:12.5px; color:#7C2D12;">
          <strong>IMPORTANTE:</strong> solicito, por gentileza, que este e-mail seja repassado a todos os usuários envolvidos na agenda, para que todos estejam devidamente cientes das datas.
        </td></tr>
      </table>
    </td>
  </tr>

</table>
'''


def build_table(rows):
    trs = []
    for i, r in enumerate(rows, start=1):
        dia = WEEKDAY_ABBR.get(r["Dia da Semana"].strip(), r["Dia da Semana"])
        data_fmt = f'{r["Data"][:5]} ({dia})'
        agenda = r["Agenda"].strip()
        sty = style_for(agenda)
        usuario = r["Usuário Cliente"].strip() or "—"
        periodo = r["Período"].strip() or "—"
        trs.append(f'''
        <tr style="background-color:{sty['bg']};">
          <td style="padding:9px 10px; border:1px solid {sty['border']}; color:{sty['fg']}; font-size:13px; text-align:center;">{i}</td>
          <td style="padding:9px 10px; border:1px solid {sty['border']}; color:{sty['fg']}; font-size:13px;">{r['Consultor']}</td>
          <td style="padding:9px 10px; border:1px solid {sty['border']}; color:{sty['fg']}; font-size:13px;">{r['Atividade']}</td>
          <td style="padding:9px 10px; border:1px solid {sty['border']}; color:{sty['fg']}; font-size:13px; white-space:nowrap;">{data_fmt}</td>
          <td style="padding:9px 10px; border:1px solid {sty['border']}; color:{sty['fg']}; font-size:13px; white-space:nowrap;">{periodo}</td>
          <td style="padding:9px 10px; border:1px solid {sty['border']}; color:{sty['fg']}; font-size:13px;">{usuario}</td>
          <td style="padding:9px 10px; border:1px solid {sty['border']}; color:{sty['fg']}; font-size:13px; font-weight:bold;">{agenda or '—'}</td>
        </tr>''')
    return "".join(trs)


EMAIL_TEMPLATE = '''
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background-color:#e5e7eb; padding:10px 0 6px 0;">
<tr><td align="center">
  <table role="presentation" width="680" cellpadding="0" cellspacing="0">
    <tr><td style="font-family:Arial, Helvetica, sans-serif; font-size:12.5px; color:#475569; padding:0 4px 2px 4px;">
      <strong>Para:</strong> {para}
    </td></tr>
    <tr><td style="font-family:Arial, Helvetica, sans-serif; font-size:12.5px; color:#475569; padding:0 4px 2px 4px;">
      <strong>Cc:</strong> {cc}
    </td></tr>
    <tr><td style="font-family:Arial, Helvetica, sans-serif; font-size:12.5px; color:#475569; padding:0 4px 6px 4px;">
      <strong>Assunto sugerido:</strong> {assunto}
    </td></tr>
  </table>
</td></tr>
<tr><td align="center">
<table role="presentation" width="680" cellpadding="0" cellspacing="0" style="background-color:#ffffff; border-radius:10px; overflow:hidden; box-shadow:0 1px 4px rgba(0,0,0,0.08); font-family:Arial, Helvetica, sans-serif;">

  <tr>
    <td style="padding:28px 32px 6px 32px;">
      <p style="margin:0 0 4px 0; font-size:15px; color:#1f2a44; font-weight:bold;">
        Olá, equipe <span style="color:{cor};">{parceiro}</span>!
      </p>
      <p style="margin:0; font-size:14px; color:#4a5568; line-height:1.5;">
        Segue abaixo a agenda de atendimentos confirmados para a semana de <strong>{data_ini} a {data_fim}</strong>.
      </p>
    </td>
  </tr>

  <tr>
    <td style="padding:18px 32px 24px 32px;">
      <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;">
        <tr style="background-color:#1f2a44;">
          <th align="left" style="padding:10px; color:#ffffff; font-size:12px; border:1px solid #1f2a44; width:28px;">#</th>
          <th align="left" style="padding:10px; color:#ffffff; font-size:12px; border:1px solid #1f2a44;">Consultor</th>
          <th align="left" style="padding:10px; color:#ffffff; font-size:12px; border:1px solid #1f2a44;">Resumo da Demanda</th>
          <th align="left" style="padding:10px; color:#ffffff; font-size:12px; border:1px solid #1f2a44;">Data</th>
          <th align="left" style="padding:10px; color:#ffffff; font-size:12px; border:1px solid #1f2a44;">Período</th>
          <th align="left" style="padding:10px; color:#ffffff; font-size:12px; border:1px solid #1f2a44;">Usuário Cliente</th>
          <th align="left" style="padding:10px; color:#ffffff; font-size:12px; border:1px solid #1f2a44;">Agenda</th>
        </tr>
        {rows}
      </table>
    </td>
  </tr>

  <tr>
    <td style="padding:0 32px 28px 32px;">
      <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background-color:#FFF7ED; border:1px solid #FDBA74; border-radius:6px;">
        <tr><td style="padding:12px 14px; font-size:12.5px; color:#7C2D12;">
          <strong>IMPORTANTE:</strong> solicito, por gentileza, que este e-mail seja repassado a todos os usuários envolvidos na agenda, para que todos estejam devidamente cientes das datas.
        </td></tr>
      </table>
    </td>
  </tr>

</table>
</td></tr>
</table>
'''

