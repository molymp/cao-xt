"""pytest-Konfiguration für kasse-app Tests.

Fügt kasse-app/app zum Python-Suchpfad hinzu.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / 'app'))
