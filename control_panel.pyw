"""Старое имя программы: теперь всё в одной панели управления (manager.pyw)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from manager.app import main  # noqa: E402

main([])
