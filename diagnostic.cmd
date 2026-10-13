@echo off
rem Lance diagnostic.ps1 sans modifier la politique d'exécution de Windows (portée : ce seul processus).
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0diagnostic.ps1" %*
pause
