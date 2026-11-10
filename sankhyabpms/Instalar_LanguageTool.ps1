# Instala o Java (JRE 21) e o LanguageTool em ferramentas\, sem mexer no Windows, e testa em portugues.
# O corretor roda so neste computador: o servidor escuta apenas em localhost.
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
$raiz = Split-Path -Parent $MyInvocation.MyCommand.Path
$dest = Join-Path $raiz 'ferramentas'
$temp = Join-Path $dest '_baixando'
New-Item -ItemType Directory -Force -Path $temp | Out-Null

function Instalar($nome, $url, $arquivo, $filtro) {
    if (Get-ChildItem -Path $dest -Directory -Filter $filtro -ErrorAction SilentlyContinue) {
        Write-Host "$nome ja instalado."
        return
    }
    $zip = Join-Path $temp $arquivo
    Write-Host "Baixando $nome ..."
    Invoke-WebRequest -Uri $url -OutFile $zip -UseBasicParsing
    Write-Host "Extraindo $nome ..."
    Expand-Archive -Path $zip -DestinationPath $dest -Force
    Remove-Item -Path $zip -Force
}

Instalar 'Java 21 (cerca de 47 MB)' 'https://api.adoptium.net/v3/binary/latest/21/ga/windows/x64/jre/hotspot/normal/eclipse?project=jdk' 'jre.zip' 'jdk-21*'
Instalar 'LanguageTool (cerca de 240 MB)' 'https://languagetool.org/download/LanguageTool-stable.zip' 'languagetool.zip' 'LanguageTool-*'
Remove-Item -Path $temp -Recurse -Force -ErrorAction SilentlyContinue

$java = Join-Path (Get-ChildItem -Path $dest -Directory -Filter 'jdk-21*' | Select-Object -First 1).FullName 'bin\java.exe'
$lt = (Get-ChildItem -Path $dest -Directory -Filter 'LanguageTool-*' | Select-Object -First 1).FullName
$porta = 8095
Write-Host 'Testando o corretor em portugues (pode levar ate 1 minuto) ...'
$proc = Start-Process -FilePath $java -ArgumentList @('-cp', 'languagetool-server.jar', 'org.languagetool.server.HTTPServer', '--port', "$porta") -WorkingDirectory $lt -WindowStyle Hidden -PassThru
try {
    $resposta = $null
    for ($i = 0; $i -lt 60 -and -not $resposta; $i++) {
        Start-Sleep -Seconds 2
        try {
            $resposta = Invoke-RestMethod -Method Post -Uri "http://localhost:$porta/v2/check" -Body @{ language = 'pt-BR'; text = 'As casa foi vendida ontem e nos ficamos sem resposta.' }
        } catch { }
    }
    if (-not $resposta) { throw 'O corretor nao respondeu.' }
    Write-Host ("Corretor OK: encontrou {0} apontamento(s) na frase de teste." -f $resposta.matches.Count)
    foreach ($m in $resposta.matches) { Write-Host ("  - " + $m.message) }
} finally {
    Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
}
Write-Host 'Instalacao concluida.'
