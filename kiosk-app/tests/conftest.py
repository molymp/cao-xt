"""pytest-Konfiguration für kiosk-app Tests.

Fügt kiosk-app/app und common zum Python-Suchpfad hinzu.
"""
import sys
from pathlib import Path

# kiosk-app/app → für app, config, db etc.
sys.path.insert(0, str(Path(__file__).parent.parent / 'app'))
# Repo-Root → für common.*
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
