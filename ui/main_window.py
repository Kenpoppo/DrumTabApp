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
from typing import Callable, Optional

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
        # 解析結果を保持（MIDI 書き出しに利用）
        self._last_drum_result   = None
        self._last_bass_result   = None
        self._last_guitar_result = None
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
        self._midi_btn   = QPushButton("MIDI 書き出し")

        self._guitar_btn.clicked.connect(self._run_guitar)
        self._bass_btn.clicked.connect(self._run_bass)
        self._drum_btn.clicked.connect(self._run_drum)
        self._export_btn.clicked.connect(self._export_pdf)
        self._midi_btn.clicked.connect(self._export_midi)

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
        for btn in (self._guitar_btn, self._bass_btn, self._drum_btn,
                    self._export_btn, self._midi_btn):
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
        self._midi_btn.setEnabled(False)  # 解析完了後に有効化

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
            pa = __import__("core.pitch_analyzer",  fromlist=["analyze"])
            chord_result = ca.analyze(path)
            tab_result = pa.analyze(
                path, "guitar",
                chords=chord_result.chord_per_measure,
                key=chord_result.key,
            )
            self._last_guitar_result = tab_result  # MIDI 書き出し用に保持
            return tab_result.tab_text
        self._launch("Guitar TAB 生成", _task)

    def _run_bass(self) -> None:
        path = self._selected_file
        def _task() -> str:
            ca = __import__("core.chord_analyzer", fromlist=["analyze"])
            pa = __import__("core.pitch_analyzer",  fromlist=["analyze"])
            chord_result = ca.analyze(path)
            tab_result = pa.analyze(
                path, "bass",
                chords=chord_result.chord_per_measure,
                key=chord_result.key,
            )
            self._last_bass_result = tab_result  # MIDI 書き出し用に保持
            return tab_result.tab_text
        self._launch("Bass TAB 生成", _task)

    def _run_drum(self) -> None:
        path = self._selected_file
        def _task() -> str:
            ca = __import__("core.chord_analyzer", fromlist=["analyze"])
            da = __import__("core.drum_analyzer",   fromlist=["analyze", "to_text"])
            chord_result = ca.analyze(path)
            drum_result  = da.analyze(path)
            self._last_drum_result = drum_result  # MIDI 書き出し用に保持
            return da.to_text(
                drum_result,
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
        # 解析結果があれば MIDI 書き出しボタンを有効化
        if any([self._last_drum_result, self._last_bass_result, self._last_guitar_result]):
            self._midi_btn.setEnabled(True)
        self.statusBar().showMessage("完了")

    def _on_error(self, message: str) -> None:
        self._display.setPlainText(f"エラーが発生しました:\n\n{message}")
        self._set_analysis_enabled(True)
        self.statusBar().showMessage("エラー発生")

    # ── MIDI 書き出し ─────────────────────────────────────────────────────────
    def _export_midi(self) -> None:
        has_result = any([self._last_drum_result,
                          self._last_bass_result,
                          self._last_guitar_result])
        if not has_result:
            self.statusBar().showMessage("MIDI 書き出し: 先に解析を実行してください")
            return

        save_path, _ = QFileDialog.getSaveFileName(
            self, "MIDI 保存先を選択", _DOWNLOADS, "MIDI Files (*.mid)"
        )
        if not save_path:
            return

        try:
            from core.midi_exporter import export_midi
            # BPM はドラム → ベース → ギターの優先順位で取得
            bpm = (
                self._last_drum_result.bpm   if self._last_drum_result   else
                self._last_bass_result.bpm   if self._last_bass_result   else
                self._last_guitar_result.bpm
            )
            result = export_midi(
                save_path, bpm,
                drum_result=self._last_drum_result,
                bass_result=self._last_bass_result,
                guitar_result=self._last_guitar_result,
            )
            self.statusBar().showMessage(
                f"MIDI 書き出し完了: {result.n_tracks} トラック → {os.path.basename(save_path)}"
            )
        except Exception as exc:
            self.statusBar().showMessage(f"MIDI 書き出しエラー: {exc}")

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
        # MIDI ボタンは解析結果があるかどうかで連動
        # （解析中は禁止、完了後は _on_done 内で再判定）
        if not enabled:
            self._midi_btn.setEnabled(False)
