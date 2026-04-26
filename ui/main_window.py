"""
ui/main_window.py
─────────────────────────────────────────────────────────────────────────────
メインウィンドウ。

設計上の改善点（旧 main_gui.py との比較）:
  - 汎用 _Worker スレッドで「全解析」をバックグラウンド実行
    （旧実装はドラムのみ非同期、ギター・ベースはメインスレッドをブロック）
  - ワーカー実行中はボタンを無効化 → 多重実行・クラッシュを防止
  - エラーシグナルで例外をキャッチし、UIに表示
  - QStatusBar でステータスを常時表示
  - モノスペースフォントで TAB の桁揃えを保持
  - core/ パッケージへの遅延インポートで起動を高速化
"""
from __future__ import annotations

import os
from typing import Callable

from PyQt5.QtCore import QThread, pyqtSignal
from PyQt5.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QStatusBar,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

# プロジェクトルート基準のデフォルトディレクトリ
_ROOT_DIR     = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_DOWNLOADS    = os.path.join(_ROOT_DIR, "downloads")


# ── バックグラウンドワーカー ────────────────────────────────────────────────────
class _Worker(QThread):
    """
    任意の callable を別スレッドで実行し、結果 or エラーをシグナルで通知する。
    """
    finished = pyqtSignal(str)   # 成功: 結果テキスト
    error    = pyqtSignal(str)   # 失敗: エラーメッセージ

    def __init__(self, fn: Callable[[], str]) -> None:
        super().__init__()
        self._fn = fn

    def run(self) -> None:
        try:
            self.finished.emit(self._fn())
        except Exception as exc:
            self.error.emit(f"{type(exc).__name__}: {exc}")


# ── メインウィンドウ ──────────────────────────────────────────────────────────
class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self._selected_file: str | None = None
        self._worker: _Worker | None = None
        self._setup_ui()

    # ── UI 構築 ─────────────────────────────────────────────────────────────────
    def _setup_ui(self) -> None:
        self.setWindowTitle("Sonic Blue Tab Generator")
        self.setGeometry(200, 200, 960, 700)

        # ファイル選択
        self._file_btn   = QPushButton("音源ファイルを選択")
        self._file_label = QLabel("ファイル未選択")
        self._file_label.setStyleSheet("color: gray; padding-left: 6px;")
        self._file_btn.clicked.connect(self._select_file)

        # 解析ボタン
        self._guitar_btn = QPushButton("Guitar TAB 生成")
        self._bass_btn   = QPushButton("Bass TAB 生成")
        self._drum_btn   = QPushButton("Drum 解析")
        self._export_btn = QPushButton("PDF エクスポート")

        self._guitar_btn.clicked.connect(self._run_guitar)
        self._bass_btn.clicked.connect(self._run_bass)
        self._drum_btn.clicked.connect(self._run_drum)
        self._export_btn.clicked.connect(self._export_pdf)

        # TAB 表示エリア（等幅フォント）
        self._display = QTextEdit()
        self._display.setReadOnly(True)
        self._display.setFontFamily("Courier New")
        self._display.setFontPointSize(10)

        # レイアウト
        file_row = QHBoxLayout()
        file_row.addWidget(self._file_btn)
        file_row.addWidget(self._file_label, stretch=1)

        btn_row = QHBoxLayout()
        for btn in (self._guitar_btn, self._bass_btn, self._drum_btn, self._export_btn):
            btn_row.addWidget(btn)

        layout = QVBoxLayout()
        layout.addLayout(file_row)
        layout.addLayout(btn_row)
        layout.addWidget(self._display)

        container = QWidget()
        container.setLayout(layout)
        self.setCentralWidget(container)

        self.setStatusBar(QStatusBar())
        self.statusBar().showMessage("音源ファイルを選択してください")

        # 解析ボタンはファイル選択後に有効化
        self._set_analysis_enabled(False)

    # ── ファイル選択 ────────────────────────────────────────────────────────────
    def _select_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "音源ファイルを選択",
            _DOWNLOADS,
            "Audio Files (*.mp3 *.wav *.flac *.m4a *.ogg)",
        )
        if path:
            self._selected_file = path
            self._file_label.setText(os.path.basename(path))
            self._file_label.setStyleSheet("color: black; padding-left: 6px;")
            self._set_analysis_enabled(True)
            self.statusBar().showMessage(f"選択: {os.path.basename(path)}")

    # ── 解析ランチャー ──────────────────────────────────────────────────────────
    def _run_guitar(self) -> None:
        path = self._selected_file
        def _task() -> str:
            ca = __import__("core.chord_analyzer", fromlist=["analyze"])
            pa = __import__("core.pitch_analyzer", fromlist=["analyze"])
            chord_result = ca.analyze(path)
            tab_result = pa.analyze(
                path, "guitar",
                chords=chord_result.chord_per_measure,
                key=chord_result.key,
            )
            return tab_result.tab_text
        self._launch("Guitar TAB 生成", _task)

    def _run_bass(self) -> None:
        path = self._selected_file
        def _task() -> str:
            ca = __import__("core.chord_analyzer", fromlist=["analyze"])
            pa = __import__("core.pitch_analyzer", fromlist=["analyze"])
            chord_result = ca.analyze(path)
            tab_result = pa.analyze(
                path, "bass",
                chords=chord_result.chord_per_measure,
                key=chord_result.key,
            )
            return tab_result.tab_text
        self._launch("Bass TAB 生成", _task)

    def _run_drum(self) -> None:
        path = self._selected_file
        def _task() -> str:
            ca = __import__("core.chord_analyzer", fromlist=["analyze"])
            da = __import__("core.drum_analyzer", fromlist=["analyze", "to_text"])
            chord_result = ca.analyze(path)
            return da.to_text(
                da.analyze(path),
                chords=chord_result.chord_per_measure,
                key=chord_result.key,
            )
        self._launch("Drum 解析", _task)

    # ── 汎用バックグラウンド実行 ────────────────────────────────────────────────
    def _launch(self, label: str, fn: Callable[[], str]) -> None:
        if not self._selected_file:
            self.statusBar().showMessage("ファイルを選択してください")
            return
        if self._worker and self._worker.isRunning():
            self.statusBar().showMessage("解析中です。完了をお待ちください")
            return

        self._set_analysis_enabled(False)
        self._display.setPlainText(f"{label} を実行中…\n（解析には数秒〜数十秒かかることがあります）")
        self.statusBar().showMessage(f"{label} 中…")

        self._worker = _Worker(fn)
        self._worker.finished.connect(self._on_done)
        self._worker.error.connect(self._on_error)
        self._worker.start()

    # ── ワーカーコールバック ────────────────────────────────────────────────────
    def _on_done(self, result: str) -> None:
        self._display.setPlainText(result)
        self._set_analysis_enabled(True)
        self.statusBar().showMessage("完了")

    def _on_error(self, message: str) -> None:
        self._display.setPlainText(f"エラーが発生しました:\n\n{message}")
        self._set_analysis_enabled(True)
        self.statusBar().showMessage("エラー発生")

    # ── PDF エクスポート ────────────────────────────────────────────────────────
    def _export_pdf(self) -> None:
        text = self._display.toPlainText()
        if not text:
            self.statusBar().showMessage("エクスポートするデータがありません")
            return

        save_path, _ = QFileDialog.getSaveFileName(
            self, "エクスポート先を選択", _DOWNLOADS, "PDF Files (*.pdf)"
        )
        if not save_path:
            return

        try:
            from core.exporter import export_pdf
            export_pdf(text, save_path)
            self.statusBar().showMessage(f"エクスポート完了: {save_path}")
        except Exception as exc:
            self.statusBar().showMessage(f"エクスポートエラー: {exc}")

    # ── ヘルパー ────────────────────────────────────────────────────────────────
    def _set_analysis_enabled(self, enabled: bool) -> None:
        for btn in (self._guitar_btn, self._bass_btn, self._drum_btn, self._export_btn):
            btn.setEnabled(enabled)
