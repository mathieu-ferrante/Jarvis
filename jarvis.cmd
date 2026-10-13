@echo off
rem Lance Jarvis (icône dans la zone de notification, voix, interface). Ajouter --fenetre pour ouvrir l'interface.
set PYTHONIOENCODING=utf-8
"%~dp0.venv\Scripts\python.exe" -m jarvis demarrer %*
