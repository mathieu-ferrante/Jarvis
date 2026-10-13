# Installation de Jarvis sur le PC de jeu.
#   .\installer.cmd                   installe tout (environnement, dépendances, modèles)
#   .\installer.cmd -Demarrage        + lancement automatique à l'ouverture de session (NF-05)
#   .\installer.cmd -Tailscale        + accès depuis le téléphone et le Mac via Tailscale (HTTPS privé)
param([switch]$Demarrage, [switch]$Tailscale, [switch]$Navigateur)
$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot

& py -3.13 --version *> $null
if ($LASTEXITCODE -ne 0) {
    Write-Host "Python 3.13 introuvable : winget install Python.Python.3.13" -ForegroundColor Red
    exit 1
}
if (-not (Test-Path ".venv\Scripts\python.exe")) {
    Write-Host "Création de l'environnement Python…"
    & py -3.13 -m venv .venv
}
$python = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
$pythonw = Join-Path $PSScriptRoot ".venv\Scripts\pythonw.exe"
$extras = if ($Navigateur) { "voix,app,navigateur" } else { "voix,app" }

Write-Host "Dépendances…"
& $python -m pip install --disable-pip-version-check -q --upgrade pip
& $python -m pip install --disable-pip-version-check -q -e ".[$extras]"
if ($LASTEXITCODE -ne 0) { Write-Host "Échec de l'installation des dépendances." -ForegroundColor Red; exit 1 }

$env:PYTHONIOENCODING = "utf-8"
Write-Host "Modèles et outils (selon jarvis.toml ; plusieurs Go la première fois)…"
& $python -m jarvis installer
if ($LASTEXITCODE -ne 0) { Write-Host "Téléchargements incomplets : relancer le script (il reprend où il s'est arrêté)." -ForegroundColor Yellow }

if ($Demarrage) {
    $dossier = [Environment]::GetFolderPath("Startup")
    $shell = New-Object -ComObject WScript.Shell
    $lien = $shell.CreateShortcut((Join-Path $dossier "Jarvis.lnk"))
    $lien.TargetPath = $pythonw
    $lien.Arguments = "-m jarvis demarrer"
    $lien.WorkingDirectory = $PSScriptRoot
    $lien.Description = "Jarvis, assistant personnel local"
    $lien.Save()
    Write-Host "Jarvis démarrera à l'ouverture de session (raccourci dans le dossier Démarrage)."
}

if ($Tailscale) {
    $ts = Get-Command tailscale -ErrorAction SilentlyContinue
    if (-not $ts) {
        Write-Host "Tailscale n'est pas installé : https://tailscale.com/download/windows" -ForegroundColor Yellow
    } else {
        # Expose l'interface en HTTPS UNIQUEMENT sur le réseau privé Tailscale (pas « funnel » : rien sur Internet).
        & tailscale serve --bg --https=443 http://127.0.0.1:8730
        & tailscale serve status
        Write-Host "Depuis le téléphone (Tailscale actif) : ouvrir l'adresse https://<nom-du-pc>.<tailnet>.ts.net ci-dessus."
    }
}

Write-Host "`nTerminé. Lancer Jarvis : jarvis.cmd (ou redémarrer la session si -Demarrage)." -ForegroundColor Green
