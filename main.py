"""
main.py  ─  アプリケーションエントリポイント
─────────────────────────────────────────────────────────────────────────────
起動:
    python main.py

旧エントリポイント main_gui.py は後方互換のため残存するが、
今後はこのファイルを使用する。
"""
from __future__ import annotations

import logging
import logging.handlers
import os
import sys

# プロジェクトルートを sys.path に追加して core / ui パッケージを解決
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

_LOG_DIR  = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")
_LOG_FILE = os.path.join(_LOG_DIR, "app.log")


def _setup_logging() -> None:
    """ロギングを初期化する。logs/app.log にローテーション付きで出力する。"""
    os.makedirs(_LOG_DIR, exist_ok=True)

    fmt = logging.Formatter(
        "%(asctime)s %(levelname)-8s %(name)s  %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # ファイルハンドラ: 5MB × 3世代ローテーション
    fh = logging.handlers.RotatingFileHandler(
        _LOG_FILE, maxBytes=5 * 1024 * 1024, backupCount=3,
        encoding="utf-8",
    )
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(fmt)

    # コンソールハンドラ: INFO 以上のみ
    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(logging.INFO)
    ch.setFormatter(fmt)

    root = logging.getLogger()
    root.setLevel(logging.DEBUG)
    root.addHandler(fh)
    root.addHandler(ch)

    logging.getLogger("numba").setLevel(logging.WARNING)
    logging.getLogger("librosa").setLevel(logging.WARNING)
    logging.getLogger("tensorflow").setLevel(logging.WARNING)


from PyQt5.QtWidgets import QApplication

from ui.main_window import MainWindow


def main() -> None:
    _setup_logging()
    log = logging.getLogger(__name__)
    log.info("=== DrumTabApp 起動 ===")
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    ret = app.exec_()
    log.info("=== DrumTabApp 終了 (exit=%d) ===", ret)
    sys.exit(ret)


if __name__ == "__main__":
    main()
