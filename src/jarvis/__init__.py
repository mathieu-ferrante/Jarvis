"""Jarvis : assistant personnel vocal, 100 % local."""

import os

# Règle absolue (SEC-04) : aucune bibliothèque ne doit contacter un service distant de sa
# propre initiative. On coupe la télémétrie et les téléchargements implicites dès l'import.
for _var, _valeur in {
    "HF_HUB_OFFLINE": "1",
    "HF_HUB_DISABLE_TELEMETRY": "1",
    "HF_HUB_DISABLE_IMPLICIT_TOKEN": "1",
    "TRANSFORMERS_OFFLINE": "1",
    "DO_NOT_TRACK": "1",
    "ANONYMIZED_TELEMETRY": "False",
}.items():
    os.environ.setdefault(_var, _valeur)

__version__ = "0.0.1"
