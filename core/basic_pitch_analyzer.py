"""
core/basic_pitch_analyzer.py
─────────────────────────────────────────────────────────────────────────────
Spotify「Basic Pitch」ニューラルネットワークを用いた高精度ピッチ検出モジュール。

References:
  • Bittner et al., "A Lightweight Instrument-Agnostic Model for Polyphonic
    Note Transcription and Multipitch Estimation", ICASSP 2022
    https://github.com/spotify/basic-pitch

piptrack (DSP) との比較:
  ┌───────────────────┬──────────────────┬───────────────────────┐
  │                   │ piptrack (従来)  │ basic-pitch (高精度)  │
  ├───────────────────┼──────────────────┼───────────────────────┤
  │ アルゴリズム      │ DSP / stFT       │ 軽量 CNN (神経網)     │
  │ 多声音対応        │ ✗ モノフォニック │ ✓ ポリフォニック      │
  │ onset/offset 精度 │ △ 近似           │ ✓ フレーム単位        │
  │ ベロシティ検出    │ ✗               │ ✓ 0–127              │
  │ ピッチベンド      │ ✗               │ ✓                    │
  │ 処理速度          │ ◎ 高速           │ △ 初回ロード数秒      │
  └───────────────────┴──────────────────┴───────────────────────┘
"""
from __future__ import annotations

import os
import warnings
from typing import List, Optional, Tuple

import librosa
import numpy as np

from core.pitch_analyzer import (
    TabResult,
    _TUNINGS,
    _STRING_NAMES,
    _MIDI_RANGE,
    _MEASURES_PER_LINE,
    _COLS_PER_MEASURE,
    _SUBDIVISIONS,
    _render_tab,
)

# TensorFlow の INFO ログを抑制
os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "2")
warnings.filterwarnings("ignore", category=UserWarning)


# ── 公開 API ───────────────────────────────────────────────────────────────────
def analyze(
    audio_path:  str,
    instrument:  str,
    chords:      Optional[List[str]] = None,
    key:         str = "",
    onset_threshold:   float = 0.5,   # onset 検出感度 (0–1, 高いほど保守的)
    frame_threshold:   float = 0.3,   # ピッチフレーム閾値 (0–1)
    minimum_note_length: float = 58,  # ノート最小長 [ms]
) -> TabResult:
    """
    basic-pitch ニューラルネットワークで高精度ピッチ検出 → TAB 生成。

    引数:
        audio_path:           解析対象ファイルパス (.mp3/.wav/.flac/.m4a等)
        instrument:           "guitar" または "bass"
        chords:               小節別コードリスト (省略可)
        key:                  キー文字列 (省略可)
        onset_threshold:      onsetの検出感度。低くすると検出数増、高くすると精度重視。
        frame_threshold:      フレームレベルピッチ閾値。低いと多声音検出が増える。
        minimum_note_length:  最小ノート長 [ms]。短すぎるノイズ的ノートを除去。

    戻り値:
        TabResult (pitch_analyzer.TabResult と互換)

    例外:
        ImportError  — basic-pitch 未インストール
        ValueError   — 未対応楽器
    """
    try:
        from basic_pitch.inference import predict
        from basic_pitch import ICASSP_2022_MODEL_PATH
    except ImportError as e:
        raise ImportError(
            "basic-pitch が見つかりません。\n"
            "  pip install basic-pitch\n"
            "を実行してください。"
        ) from e

    if instrument not in _TUNINGS:
        raise ValueError(f"未対応の楽器です: {instrument}  (guitar / bass のみ対応)")

    # BPM は既存の librosa で取得（beat_track は basic-pitch 非依存）
    y, sr = librosa.load(audio_path, sr=None, mono=True, dtype=np.float32)
    tempo, _ = librosa.beat.beat_track(y=y, sr=sr)
    bpm = float(np.atleast_1d(tempo)[0])
    if bpm < 40.0:
        bpm = 120.0

    # ── ニューラルネットワーク推論 ────────────────────────────────────────────
    midi_min, midi_max = _MIDI_RANGE[instrument]

    _, _, note_events = predict(
        audio_path,
        onset_threshold=onset_threshold,
        frame_threshold=frame_threshold,
        minimum_note_length=minimum_note_length,
        minimum_frequency=librosa.midi_to_hz(midi_min),
        maximum_frequency=librosa.midi_to_hz(midi_max),
    )

    # note_events: List[Tuple] 各要素は
    #   (start_time_s, end_time_s, pitch_midi, velocity, pitch_bends)
    timed_notes: List[Tuple[float, int]] = [
        (float(ev[0]), int(ev[2]))
        for ev in note_events
        if midi_min <= ev[2] <= midi_max
    ]
    timed_notes.sort(key=lambda x: x[0])

    if not timed_notes:
        return TabResult(
            instrument=instrument,
            tab_text=(
                "音符が検出されませんでした。\n"
                "onset_threshold/frame_threshold を下げると検出数が増えます。"
            ),
            note_count=0,
            bpm=bpm,
        )

    tab_text = _render_tab(timed_notes, instrument, bpm, chords=chords, key=key)
    return TabResult(
        instrument=instrument,
        tab_text=tab_text,
        note_count=len(timed_notes),
        bpm=bpm,
        timed_notes=timed_notes,
    )
