#!/bin/zsh
# Installation de l'agent Jarvis sur le Mac (lot J14).
#   ./mac/installer.sh https://<pc>.<tailnet>.ts.net 123456
# Prérequis : Tailscale actif ; Python 3.13 (brew install python@3.13).
set -euo pipefail
cd "$(dirname "$0")/.."
PY=${PY:-python3.13}
command -v "$PY" >/dev/null || { echo "Python 3.13 introuvable : brew install python@3.13"; exit 1; }

[ -d .venv-mac ] || "$PY" -m venv .venv-mac
.venv-mac/bin/python -m pip install -q --upgrade pip
.venv-mac/bin/python -m pip install -q -e ".[mac]"

if [ $# -eq 2 ]; then
  .venv-mac/bin/python -m jarvis.mac appairer "$1" "$2"
fi

# Lancement automatique à l'ouverture de session (LaunchAgent utilisateur)
PLIST="$HOME/Library/LaunchAgents/fr.mathieu.jarvis.plist"
cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>fr.mathieu.jarvis</string>
  <key>ProgramArguments</key><array>
    <string>$PWD/.venv-mac/bin/python</string><string>-m</string><string>jarvis.mac</string>
  </array>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>ProcessType</key><string>Interactive</string>
  <key>StandardErrorPath</key><string>$HOME/Library/Logs/jarvis-mac.log</string>
</dict></plist>
EOF
launchctl unload "$PLIST" 2>/dev/null || true
launchctl load "$PLIST"
echo "Agent Jarvis installé. Autoriser au premier lancement : Micro, Accessibilité (raccourci), Automatisation (Rappels, Calendrier, Notes, Mail), Enregistrement de l'écran."
