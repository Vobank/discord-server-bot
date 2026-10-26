"""Панель управления ботом. Запуск: двойной клик (ярлык на рабочем столе)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from manager.app import main  # noqa: E402

main()
