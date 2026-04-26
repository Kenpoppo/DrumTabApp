"""
main.py  ─  アプリケーションエントリポイント
─────────────────────────────────────────────────────────────────────────────
起動:
    python main.py

旧エントリポイント main_gui.py は後方互換のため残存するが、
今後はこのファイルを使用する。
"""
from __future__ import annotations

import os
import sys

# プロジェクトルートを sys.path に追加して core / ui パッケージを解決
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PyQt5.QtWidgets import QApplication

from ui.main_window import MainWindow


def main() -> None:
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
