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

import logging
import os
from typing import Callable, Optional

from PyQt5.QtCore import Qt, QThread, QTimer, pyqtSignal
from PyQt5.QtWidgets import (
    QCheckBox,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QSlider,
    QSpinBox,
    QStatusBar,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from core.player import AudioPlayer, make_click_sound as _make_click

_SR_CLICK = 22050   # クリック音のサンプルレート


def _fmt_time(sec: float) -> str:
    """秒を m:ss 形式に変換する。"""
    s = max(0, int(sec))
    return f"{s // 60}:{s % 60:02d}"

# プロジェクトルート基準のデフォルトディレクトリ
_ROOT_DIR     = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_DOWNLOADS    = os.path.join(_ROOT_DIR, "downloads")

log = logging.getLogger(__name__)


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
            logging.getLogger(__name__).error(
                "Worker error: %s: %s", type(exc).__name__, exc, exc_info=True)
            self.error.emit(f"{type(exc).__name__}: {exc}")


# ── メインウィンドウ ──────────────────────────────────────────────────────────
class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self._selected_file: str | None = None
        self._worker: _Worker | None = None
        self._player_worker: _Worker | None = None  # プレイヤー用ワーカー（GC防止用に保持）
        # 解析結果を保持
        self._last_drum_result   = None
        self._last_bass_result   = None
        self._last_guitar_result = None

        # ── プレイヤー ──────────────────────────────────────────────────────────
        self._player      = AudioPlayer()
        self._click_snd   = _make_click(_SR_CLICK)
        self._pos_timer   = QTimer(self)
        self._metro_timer = QTimer(self)
        self._prog_seeking = False
        self._loop_a_sec: Optional[float] = None
        self._loop_b_sec: Optional[float] = None
        self._was_playing  = False

        self._pos_timer.setInterval(100)          # 100ms ごとに位置更新
        self._pos_timer.timeout.connect(self._update_pos)
        self._pos_timer.start()
        self._metro_timer.timeout.connect(self._metro_tick)

        self._setup_ui()

    # ── UI 構築 ─────────────────────────────────────────────────────────────────
    def _setup_ui(self) -> None:
        self.setWindowTitle("Sonic Blue Tab Generator")
        self.setGeometry(200, 200, 960, 820)

        # ファイル選択
        self._file_btn   = QPushButton("音源ファイルを選択")
        self._file_label = QLabel("ファイル未選択")
        self._file_label.setStyleSheet("color: gray; padding-left: 6px;")
        self._file_btn.clicked.connect(self._select_file)

        # 解析ボタン
        self._all_btn    = QPushButton("⚡ 全解析")
        self._guitar_btn = QPushButton("Guitar TAB 生成")
        self._bass_btn   = QPushButton("Bass TAB 生成")
        self._drum_btn   = QPushButton("Drum 解析")
        self._export_btn = QPushButton("PDF エクスポート")
        self._midi_btn   = QPushButton("MIDI 書き出し")
        self._gp_btn     = QPushButton("🎸 GP書き出し (TuxGuitar)")
        self._all_btn.setToolTip(
            "Drum / Guitar / Bass を一括解析します。\n"
            "音声ロード・HPSS・BPM 推定を1回に集約するため、個別実行より高速です。"
        )

        # 高精度モード切替（basic-pitch 神経網 vs piptrack DSP）
        self._hq_check = QCheckBox("🧠 高精度モード (basic-pitch)")
        self._hq_check.setToolTip(
            "ONにすると Spotify basic-pitch 神経網で解析します。\n"
            "精度が大幅に向上しますが、処理に数十秒かかる場合があります。"
        )

        self._all_btn.clicked.connect(self._run_all)
        self._guitar_btn.clicked.connect(self._run_guitar)
        self._bass_btn.clicked.connect(self._run_bass)
        self._drum_btn.clicked.connect(self._run_drum)
        self._export_btn.clicked.connect(self._export_pdf)
        self._midi_btn.clicked.connect(self._export_midi)
        self._gp_btn.clicked.connect(self._export_gp)

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
        for btn in (self._all_btn, self._guitar_btn, self._bass_btn, self._drum_btn,
                    self._export_btn, self._midi_btn, self._gp_btn):
            btn_row.addWidget(btn)
        btn_row.addWidget(self._hq_check)

        layout = QVBoxLayout()
        layout.addLayout(file_row)
        layout.addLayout(btn_row)
        layout.addWidget(self._build_player_panel())
        layout.addWidget(self._display)

        container = QWidget()
        container.setLayout(layout)
        self.setCentralWidget(container)

        self.setStatusBar(QStatusBar())
        self.statusBar().showMessage("音源ファイルを選択してください")

        # 解析ボタンはファイル選択後に有効化
        self._set_analysis_enabled(False)
        self._midi_btn.setEnabled(False)  # 解析完了後に有効化
        self._gp_btn.setEnabled(False)    # 解析完了後に有効化

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
            log.info("file selected: %s", path)
            # 新ファイルに切り替え: 音声キャッシュをクリア
            try:
                from core import _audio_cache
                _audio_cache.clear()
            except Exception:
                pass
            # プレイヤーに音声をロード
            self._player.stop()
            self._play_btn.setText("▶")
            self._loop_a_sec = self._loop_b_sec = None
            self._player.clear_loop()
            self._loop_a_btn.setText("[ A 点 セット ]")
            self._loop_b_btn.setText("[ B 点 セット ]")
            self._load_audio()

    # ── 解析ランチャー ──────────────────────────────────────────────────────────
    def _run_all(self) -> None:
        """Drum / Guitar / Bass を1セッションで一括解析する（音声ロード・HPSS・BPM は1回）。"""
        path   = self._selected_file
        use_hq = self._hq_check.isChecked()
        def _task() -> str:
            from core.analysis_session import AnalysisSession
            session = AnalysisSession(path)

            ca = __import__("core.chord_analyzer", fromlist=["analyze"])
            da = __import__("core.drum_analyzer",   fromlist=["analyze", "to_text"])
            chord_result = ca.analyze(session)
            drum_result  = da.analyze(session)
            self._last_drum_result = drum_result

            if use_hq:
                bp = __import__("core.basic_pitch_analyzer", fromlist=["analyze"])
                guitar_result = bp.analyze(session, "guitar",
                                           chords=chord_result.chord_per_measure,
                                           key=chord_result.key)
                bass_result   = bp.analyze(session, "bass",
                                           chords=chord_result.chord_per_measure,
                                           key=chord_result.key)
            else:
                pa = __import__("core.pitch_analyzer", fromlist=["analyze"])
                guitar_result = pa.analyze(session, "guitar",
                                           chords=chord_result.chord_per_measure,
                                           key=chord_result.key)
                bass_result   = pa.analyze(session, "bass",
                                           chords=chord_result.chord_per_measure,
                                           key=chord_result.key)

            self._last_guitar_result = guitar_result
            self._last_bass_result   = bass_result

            sep = "=" * 58
            drum_text   = da.to_text(drum_result,
                                     chords=chord_result.chord_per_measure,
                                     key=chord_result.key)
            return (
                f"{sep}\n DRUM TAB\n{sep}\n{drum_text}\n\n"
                f"{sep}\n GUITAR TAB\n{sep}\n{guitar_result.tab_text}\n\n"
                f"{sep}\n BASS TAB\n{sep}\n{bass_result.tab_text}"
            )
        label = "全解析 (高精度)" if use_hq else "全解析"
        log.info("run_all: hq=%s path=%s", use_hq, self._selected_file)
        self._launch(label, _task)

    def _run_guitar(self) -> None:
        path   = self._selected_file
        use_hq = self._hq_check.isChecked()
        def _task() -> str:
            from core.analysis_session import AnalysisSession
            session      = AnalysisSession(path)
            ca           = __import__("core.chord_analyzer", fromlist=["analyze"])
            chord_result = ca.analyze(session)
            if use_hq:
                bp = __import__("core.basic_pitch_analyzer", fromlist=["analyze"])
                tab_result = bp.analyze(session, "guitar",
                                        chords=chord_result.chord_per_measure,
                                        key=chord_result.key)
            else:
                pa = __import__("core.pitch_analyzer", fromlist=["analyze"])
                tab_result = pa.analyze(session, "guitar",
                                        chords=chord_result.chord_per_measure,
                                        key=chord_result.key)
            self._last_guitar_result = tab_result
            return tab_result.tab_text
        label = "Guitar TAB 生成 (高精度)" if use_hq else "Guitar TAB 生成"
        log.info("run_guitar: hq=%s path=%s", use_hq, self._selected_file)
        self._launch(label, _task)

    def _run_bass(self) -> None:
        path   = self._selected_file
        use_hq = self._hq_check.isChecked()
        def _task() -> str:
            from core.analysis_session import AnalysisSession
            session      = AnalysisSession(path)
            ca           = __import__("core.chord_analyzer", fromlist=["analyze"])
            chord_result = ca.analyze(session)
            if use_hq:
                bp = __import__("core.basic_pitch_analyzer", fromlist=["analyze"])
                tab_result = bp.analyze(session, "bass",
                                        chords=chord_result.chord_per_measure,
                                        key=chord_result.key)
            else:
                pa = __import__("core.pitch_analyzer", fromlist=["analyze"])
                tab_result = pa.analyze(session, "bass",
                                        chords=chord_result.chord_per_measure,
                                        key=chord_result.key)
            self._last_bass_result = tab_result
            return tab_result.tab_text
        label = "Bass TAB 生成 (高精度)" if use_hq else "Bass TAB 生成"
        log.info("run_bass: hq=%s path=%s", use_hq, self._selected_file)
        self._launch(label, _task)

    def _run_drum(self) -> None:
        path = self._selected_file
        def _task() -> str:
            from core.analysis_session import AnalysisSession
            session      = AnalysisSession(path)
            ca           = __import__("core.chord_analyzer", fromlist=["analyze"])
            da           = __import__("core.drum_analyzer",   fromlist=["analyze", "to_text"])
            chord_result = ca.analyze(session)
            drum_result  = da.analyze(session)
            self._last_drum_result = drum_result
            return da.to_text(drum_result,
                              chords=chord_result.chord_per_measure,
                              key=chord_result.key)
        log.info("run_drum: path=%s", self._selected_file)
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
        log.info("launch: [%s]", label)

        self._worker = _Worker(fn)
        self._worker.finished.connect(self._on_done)
        self._worker.error.connect(self._on_error)
        self._worker.start()

    # ── ワーカーコールバック ────────────────────────────────────────────────────
    def _on_done(self, result: str) -> None:
        log.info("analysis done: %d chars", len(result))
        self._display.setPlainText(result)
        self._set_analysis_enabled(True)
        # 解析結果があれば MIDI / GP 書き出しボタンを有効化
        if any([self._last_drum_result, self._last_bass_result, self._last_guitar_result]):
            self._midi_btn.setEnabled(True)
            self._gp_btn.setEnabled(True)
        # BPM をメトロノームに反映
        bpm = self._get_bpm()
        if bpm:
            self._metro_bpm_lbl.setText(f"BPM: {bpm:.0f}")
            if self._metro_timer.isActive():
                self._metro_timer.setInterval(int(60000 / bpm))
        self.statusBar().showMessage("完了")

    def _on_error(self, message: str) -> None:
        log.error("analysis error: %s", message)
        self._display.setPlainText(f"エラーが発生しました:\n\n{message}")
        self._set_analysis_enabled(True)
        self.statusBar().showMessage("エラー発生")

    # ── GP 書き出し (TuxGuitar .gp4) ──────────────────────────────────────────
    def _export_gp(self) -> None:
        has_result = any([self._last_drum_result,
                          self._last_bass_result,
                          self._last_guitar_result])
        if not has_result:
            self.statusBar().showMessage("GP 書き出し: 先に解析を実行してください")
            return

        save_path, _ = QFileDialog.getSaveFileName(
            self, "GP ファイル保存先を選択", _DOWNLOADS,
            "Guitar Pro 4 (*.gp4);;Guitar Pro 5 (*.gp5)"
        )
        if not save_path:
            return

        base_name = os.path.splitext(os.path.basename(
            self._selected_file or "DrumTabApp"
        ))[0]

        try:
            from core.gp5_exporter import export_gp5
            bpm = (
                self._last_drum_result.bpm   if self._last_drum_result   else
                self._last_bass_result.bpm   if self._last_bass_result   else
                self._last_guitar_result.bpm
            )
            result = export_gp5(
                save_path, bpm,
                drum_result=self._last_drum_result,
                bass_result=self._last_bass_result,
                guitar_result=self._last_guitar_result,
                title=base_name[:40],
            )
            self.statusBar().showMessage(
                f"GP 書き出し完了: {result.n_tracks} トラック / "
                f"{result.n_measures} 小節 → {os.path.basename(save_path)}"
            )
        except Exception as exc:
            self.statusBar().showMessage(f"GP 書き出しエラー: {exc}")

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
        for btn in (self._all_btn, self._guitar_btn, self._bass_btn,
                    self._drum_btn, self._export_btn):
            btn.setEnabled(enabled)
        # MIDI / GP ボタンは解析結果があるかどうかで連動
        # （解析中は禁止、完了後は _on_done 内で再判定）
        if not enabled:
            self._midi_btn.setEnabled(False)
            self._gp_btn.setEnabled(False)

    # ── プレイヤーパネル構築 ────────────────────────────────────────────────────

    def _build_player_panel(self) -> QGroupBox:
        group = QGroupBox("🎵 プレイヤー  ( 速度変更 / 音程変更 / A-B ループ / メトロノーム )")

        # Row1: 再生コントロール + プログレスバー
        self._play_btn    = QPushButton("▶")
        self._stop_btn    = QPushButton("⏹")
        self._prog_slider = QSlider(Qt.Horizontal)
        self._prog_slider.setRange(0, 10000)
        self._time_lbl    = QLabel("0:00 / 0:00")

        self._play_btn.setFixedWidth(36)
        self._stop_btn.setFixedWidth(36)
        self._time_lbl.setFixedWidth(90)
        self._time_lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)

        self._play_btn.clicked.connect(self._toggle_play)
        self._stop_btn.clicked.connect(self._stop_playback)
        self._prog_slider.sliderPressed.connect(self._on_prog_press)
        self._prog_slider.sliderReleased.connect(self._on_prog_release)

        ctrl_row = QHBoxLayout()
        ctrl_row.addWidget(self._play_btn)
        ctrl_row.addWidget(self._stop_btn)
        ctrl_row.addWidget(self._prog_slider, stretch=1)
        ctrl_row.addWidget(self._time_lbl)

        # Row2: 速度・音程スライダー
        self._speed_slider = QSlider(Qt.Horizontal)
        self._speed_slider.setRange(25, 200)   # 0.25x ~ 2.0x (×100)
        self._speed_slider.setValue(100)
        self._speed_slider.setToolTip("再生速度: 0.25x ~ 2.0x（スライダーを離すと適用、librosa time_stretch）")
        self._speed_lbl = QLabel("1.00x")
        self._speed_lbl.setFixedWidth(42)

        self._pitch_slider = QSlider(Qt.Horizontal)
        self._pitch_slider.setRange(-12, 12)
        self._pitch_slider.setValue(0)
        self._pitch_slider.setToolTip("音程: -12 ~ +12 半音（スライダーを離すと適用、librosa pitch_shift）")
        self._pitch_lbl = QLabel("±0")
        self._pitch_lbl.setFixedWidth(32)

        self._speed_slider.valueChanged.connect(
            lambda v: self._speed_lbl.setText(f"{v / 100:.2f}x"))
        self._speed_slider.sliderReleased.connect(self._on_speed_released)
        self._pitch_slider.valueChanged.connect(
            lambda v: self._pitch_lbl.setText(
                f"+{v}" if v > 0 else ("±0" if v == 0 else str(v))))
        self._pitch_slider.sliderReleased.connect(self._on_pitch_released)

        fx_row = QHBoxLayout()
        fx_row.addWidget(QLabel("速度:"))
        fx_row.addWidget(self._speed_slider, stretch=1)
        fx_row.addWidget(self._speed_lbl)
        fx_row.addWidget(QLabel("   音程 (半音):"))
        fx_row.addWidget(self._pitch_slider, stretch=1)
        fx_row.addWidget(self._pitch_lbl)

        # Row3: A-B ループ + メトロノーム
        self._loop_a_btn   = QPushButton("[ A 点 セット ]")
        self._loop_b_btn   = QPushButton("[ B 点 セット ]")
        self._loop_clr_btn = QPushButton("ループ解除")
        self._metro_btn    = QPushButton("🥁 メトロノーム")
        self._metro_btn.setCheckable(True)
        self._metro_bpm_lbl = QLabel("BPM: -")

        self._loop_a_btn.clicked.connect(self._set_loop_a)
        self._loop_b_btn.clicked.connect(self._set_loop_b)
        self._loop_clr_btn.clicked.connect(self._clear_loop)
        self._metro_btn.toggled.connect(self._toggle_metro)

        loop_row = QHBoxLayout()
        loop_row.addWidget(self._loop_a_btn)
        loop_row.addWidget(self._loop_b_btn)
        loop_row.addWidget(self._loop_clr_btn)
        loop_row.addStretch()
        loop_row.addWidget(self._metro_btn)
        loop_row.addWidget(self._metro_bpm_lbl)

        vbox = QVBoxLayout()
        vbox.addLayout(ctrl_row)
        vbox.addLayout(fx_row)
        vbox.addLayout(loop_row)
        group.setLayout(vbox)

        # 初期状態: ファイルロード後に有効化
        for w in (self._play_btn, self._stop_btn, self._prog_slider,
                  self._speed_slider, self._pitch_slider,
                  self._loop_a_btn, self._loop_b_btn, self._loop_clr_btn,
                  self._metro_btn):
            w.setEnabled(False)

        return group

    # ── プレイヤー: 読み込み ────────────────────────────────────────────────────

    def _load_audio(self) -> None:
        """選択中ファイルをプレイヤーにバックグラウンドロードする。"""
        path = self._selected_file
        if not path:
            return
        self._set_player_enabled(False)
        self.statusBar().showMessage("音声ファイルを読み込み中...")

        def _task() -> str:
            self._player.load(path)
            return str(self._player.duration_sec)

        self._player_worker = _Worker(_task)
        self._player_worker.finished.connect(self._on_audio_loaded)
        self._player_worker.error.connect(
            lambda msg: self.statusBar().showMessage(f"読み込みエラー: {msg}"))
        self._player_worker.start()

    def _on_audio_loaded(self, dur_str: str) -> None:
        dur = float(dur_str)
        log.info("audio loaded: dur=%.1fs", dur)
        self._set_player_enabled(True)
        self._play_btn.setText("▶")
        self._time_lbl.setText(f"0:00 / {_fmt_time(dur)}")
        bpm = self._get_bpm()
        if bpm:
            self._metro_bpm_lbl.setText(f"BPM: {bpm:.0f}")
        self.statusBar().showMessage(f"音声読み込み完了 ({_fmt_time(dur)})")

    # ── プレイヤー: 再生制御 ────────────────────────────────────────────────────

    def _toggle_play(self) -> None:
        if not self._player.is_loaded:
            return
        if self._player.is_playing:
            self._player.pause()
            self._play_btn.setText("▶")
        else:
            self._player.play()
            self._play_btn.setText("⏸")

    def _stop_playback(self) -> None:
        self._player.stop()
        self._play_btn.setText("▶")
        dur = self._player.duration_sec
        self._prog_slider.setValue(0)
        self._time_lbl.setText(f"0:00 / {_fmt_time(dur)}")

    def _update_pos(self) -> None:
        """100ms ごとにプログレスバーと時刻ラベルを更新する。"""
        if not self._player.is_loaded or self._prog_seeking:
            return
        pos = self._player.position_sec
        dur = self._player.duration_sec
        if dur > 0:
            self._prog_slider.setValue(int(pos / dur * 10000))
        self._time_lbl.setText(f"{_fmt_time(pos)} / {_fmt_time(dur)}")
        # 再生終了チェック
        if not self._player.is_playing and self._play_btn.text() == "⏸":
            self._play_btn.setText("▶")

    def _on_prog_press(self) -> None:
        self._prog_seeking = True

    def _on_prog_release(self) -> None:
        dur = self._player.duration_sec
        if dur > 0:
            sec = self._prog_slider.value() / 10000.0 * dur
            self._player.seek(sec)
        self._prog_seeking = False

    # ── プレイヤー: 速度・音程 ──────────────────────────────────────────────────

    def _on_speed_released(self) -> None:
        speed = self._speed_slider.value() / 100.0
        self._player.set_speed(speed)
        self._was_playing = self._player.is_playing
        if self._was_playing:
            self._player.pause()
        self._set_player_enabled(False)
        self.statusBar().showMessage(f"速度 {speed:.2f}x に変更中... (librosa time_stretch 処理中)")
        self._start_fx_worker()

    def _on_pitch_released(self) -> None:
        pitch = self._pitch_slider.value()
        self._player.set_pitch(pitch)
        self._was_playing = self._player.is_playing
        if self._was_playing:
            self._player.pause()
        self._set_player_enabled(False)
        label = f"+{pitch}" if pitch > 0 else ("±0" if pitch == 0 else str(pitch))
        self.statusBar().showMessage(f"音程 {label} 半音 に変更中... (librosa pitch_shift 処理中)")
        self._start_fx_worker()

    def _start_fx_worker(self) -> None:
        def _task() -> str:
            self._player.rebuild()
            return "done"

        self._player_worker = _Worker(_task)
        self._player_worker.finished.connect(self._on_fx_ready)
        self._player_worker.error.connect(
            lambda msg: self.statusBar().showMessage(f"エフェクトエラー: {msg}"))
        self._player_worker.start()

    def _on_fx_ready(self, _: str) -> None:
        self._set_player_enabled(True)
        speed = self._player.speed
        pitch = self._player.pitch
        p_str = f"+{pitch}" if pitch > 0 else ("±0" if pitch == 0 else str(pitch))
        self.statusBar().showMessage(f"速度 {speed:.2f}x / 音程 {p_str} 半音 適用完了")
        if self._was_playing:
            self._player.play()
            self._play_btn.setText("⏸")

    # ── プレイヤー: A-B ループ ──────────────────────────────────────────────────

    def _set_loop_a(self) -> None:
        self._loop_a_sec = self._player.position_sec
        self._loop_a_btn.setText(f"[ A: {_fmt_time(self._loop_a_sec)} ]")
        self._try_apply_loop()

    def _set_loop_b(self) -> None:
        self._loop_b_sec = self._player.position_sec
        self._loop_b_btn.setText(f"[ B: {_fmt_time(self._loop_b_sec)} ]")
        self._try_apply_loop()

    def _try_apply_loop(self) -> None:
        a, b = self._loop_a_sec, self._loop_b_sec
        if a is not None and b is not None and abs(b - a) > 0.1:
            self._player.set_loop(min(a, b), max(a, b))

    def _clear_loop(self) -> None:
        self._loop_a_sec = self._loop_b_sec = None
        self._player.clear_loop()
        self._loop_a_btn.setText("[ A 点 セット ]")
        self._loop_b_btn.setText("[ B 点 セット ]")

    # ── プレイヤー: メトロノーム ────────────────────────────────────────────────

    def _toggle_metro(self, checked: bool) -> None:
        if checked:
            bpm = self._get_bpm() or 120.0
            self._metro_timer.start(int(60000 / bpm))
            self._metro_bpm_lbl.setText(f"BPM: {bpm:.0f}")
        else:
            self._metro_timer.stop()

    def _metro_tick(self) -> None:
        try:
            import sounddevice as _sd
            _sd.play(self._click_snd, samplerate=_SR_CLICK, blocking=False)
        except Exception:
            pass

    # ── プレイヤー: ユーティリティ ──────────────────────────────────────────────

    def _get_bpm(self) -> Optional[float]:
        if self._last_drum_result:
            return self._last_drum_result.bpm
        if self._last_bass_result:
            return self._last_bass_result.bpm
        if self._last_guitar_result:
            return self._last_guitar_result.bpm
        return None

    def _set_player_enabled(self, enabled: bool) -> None:
        for w in (self._play_btn, self._stop_btn, self._prog_slider,
                  self._speed_slider, self._pitch_slider,
                  self._loop_a_btn, self._loop_b_btn, self._loop_clr_btn,
                  self._metro_btn):
            w.setEnabled(enabled)

    # ── ウィンドウクローズ ─────────────────────────────────────────────────────────

    def closeEvent(self, event) -> None:  # type: ignore[override]
        """ウィンドウを閉じる前にプレイヤー・タイマーをクリーンアップする。"""
        log.info("closeEvent: stopping player and timers")
        self._pos_timer.stop()
        self._metro_timer.stop()
        self._player.stop()
        # 実行中ワーカーを待機成功が必須なら待機する
        for w in (self._worker, self._player_worker):
            if w is not None and w.isRunning():
                w.quit()
                w.wait(2000)
        event.accept()
