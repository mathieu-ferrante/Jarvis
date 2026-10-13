# Diagnostic Jarvis (lot J0) — à lancer sur le PC de jeu.
# Prépare l'environnement Python puis lance les mesures. Les arguments sont transmis tels quels,
# par exemple :  .\diagnostic.ps1 --avec-moe --avec-rocm
$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot

# Python 3.13 via le lanceur « py »
$py = Get-Command py -ErrorAction SilentlyContinue
if (-not $py) {
    Write-Host "Python introuvable. Installez Python 3.13 (https://www.python.org/downloads/ ou 'winget install Python.Python.3.13'), puis relancez." -ForegroundColor Red
    exit 1
}
& py -3.13 --version *> $null
if ($LASTEXITCODE -ne 0) {
    Write-Host "Python 3.13 introuvable. Installez-le ('winget install Python.Python.3.13'), puis relancez." -ForegroundColor Red
    exit 1
}

if (-not (Test-Path ".venv\Scripts\python.exe")) {
    Write-Host "Création de l'environnement Python (.venv)…"
    & py -3.13 -m venv .venv
}
$python = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"

Write-Host "Installation des dépendances (première fois : quelques minutes)…"
& $python -m pip install --disable-pip-version-check -q --upgrade pip
& $python -m pip install --disable-pip-version-check -q -e ".[voix]"
if ($LASTEXITCODE -ne 0) { Write-Host "Échec de l'installation des dépendances." -ForegroundColor Red; exit 1 }

$env:PYTHONIOENCODING = "utf-8"
$env:PYTHONUTF8 = "1"
& $python -m jarvis.diagnostic @args
exit $LASTEXITCODE
