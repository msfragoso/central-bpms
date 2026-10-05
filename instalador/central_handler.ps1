# Central BP-MS: recebe links bpms://<acao> da página e roda SÓ os programas listados em acoes.json.
# Qualquer outra ação é recusada, então um site qualquer não consegue rodar comandos arbitrários.
param([string]$Url = "")
Add-Type -AssemblyName System.Windows.Forms

$base   = Split-Path -Parent $MyInvocation.MyCommand.Path
$config = Join-Path $base "acoes.json"
$padrao = [ordered]@{
  experience  = ""
  conferencia = "C:\sankhya_integracao\conferencia_os\Rodar_Conferencia.bat"
  travados    = "C:\sankhya_integracao\conferencia_os\Rodar_Fase3.vbs"
  aceite      = "C:\sankhya_integracao\aceite_os\Rodar_Aceite.bat"
}

function Aviso($msg, $icone = "Information") {
  [System.Windows.Forms.MessageBox]::Show($msg, "Central BP-MS", "OK", $icone) | Out-Null
}

$acoes = $padrao
if (Test-Path $config) {
  try {
    $lido = Get-Content $config -Raw -Encoding UTF8 | ConvertFrom-Json
    foreach ($k in @($padrao.Keys)) { if ($lido.$k) { $acoes[$k] = $lido.$k } }
  } catch { }
}

$partes = ($Url -replace '^bpms:(//)?', '').Trim('/').ToLower() -split '/'
$pasta  = $partes[0] -eq "pasta"
$acao   = if ($pasta) { $partes[1] } else { $partes[0] }

if (-not $acoes.Contains($acao)) { Aviso "Ação desconhecida: '$acao'." "Warning"; exit 1 }

$alvo = $acoes[$acao]
if (-not $alvo -or -not (Test-Path $alvo)) {
  $motivo = if ($alvo) { "não foi encontrado em`n$alvo" } else { "ainda não foi configurado" }
  $r = [System.Windows.Forms.MessageBox]::Show("O programa de '$acao' $motivo.`n`nQuer escolher o arquivo agora?", "Central BP-MS", "YesNo", "Question")
  if ($r -ne "Yes") { exit 0 }
  $dlg = New-Object System.Windows.Forms.OpenFileDialog
  $dlg.Title = "Escolha o programa de '$acao'"
  $dlg.Filter = "Programas|*.bat;*.cmd;*.vbs;*.py;*.pyw;*.exe;*.lnk|Todos|*.*"
  if (Test-Path "C:\sankhya_integracao") { $dlg.InitialDirectory = "C:\sankhya_integracao" }
  if ($dlg.ShowDialog() -ne "OK") { exit 0 }
  $alvo = $dlg.FileName
  $acoes[$acao] = $alvo
  $acoes | ConvertTo-Json | Set-Content $config -Encoding UTF8
}

$dir = Split-Path -Parent $alvo
try {
  if ($pasta) { Start-Process explorer.exe $dir }
  else        { Start-Process -FilePath $alvo -WorkingDirectory $dir }
} catch {
  Aviso "Não consegui iniciar:`n$alvo`n`n$($_.Exception.Message)" "Error"
}
