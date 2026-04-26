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
    _estimate_bpm,
    _mono_filter,
)

# TensorFlow の INFO ログを抑制
os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "2")
warnings.filterwarnings("ignore", category=UserWarning)

# 楽器別 basic-pitch デフォルトパラメータ
# ベースは低域(58 Hz付近)の基音を捉えるため onset/frame 閾値を低く設定する
_BP_PARAMS = {
    "guitar": {"onset_threshold": 0.50, "frame_threshold": 0.30, "minimum_note_length": 58},
    "bass":   {"onset_threshold": 0.35, "frame_threshold": 0.25, "minimum_note_length": 100},
}


# ── ベース倍音補正 ─────────────────────────────────────────────────────────────
def _correct_bass_octaves(
    timed_notes: List[Tuple[float, int]],
    y: np.ndarray,
    sr: int,
    midi_min: int,
    hop_length: int = 512,
    n_fft: int = 4096,
    ratio_threshold: float = 0.15,
    apply_above_midi: int = 43,  # G2 以上のノートのみ補正対象
) -> List[Tuple[float, int]]:
    """
    Spleeter の bass.wav では低域の基音が弱くなる問題を補正する。

    basic-pitch が倍音 (1オクターブ上) を検出した場合、
    スペクトルで基音のエネルギーが ratio_threshold 以上あれば
    1オクターブ下に修正する。

    例: Bb2(46, 116 Hz) を検出 → Bb1(34, 58 Hz) のエネルギーが
        Bb2 の 15% 以上 → Bb1 に修正 ✓
    """
    S = np.abs(librosa.stft(y, n_fft=n_fft, hop_length=hop_length))
    freqs = librosa.fft_frequencies(sr=sr, n_fft=n_fft)
    total_frames = S.shape[1]

    result: List[Tuple[float, int]] = []
    for t_sec, midi in timed_notes:
        if midi < apply_above_midi:
            result.append((t_sec, midi))
            continue

        candidate = midi - 12  # 1オクターブ下の基音候補
        if candidate < midi_min:
            result.append((t_sec, midi))
            continue

        frame = min(int(t_sec * sr / hop_length), total_frames - 1)
        window = max(1, int(0.1 * sr / hop_length))  # ±100ms 窓
        f_start = max(0, frame - window)
        f_end   = min(total_frames, frame + window)

        hz_high = float(librosa.midi_to_hz(midi))
        hz_low  = float(librosa.midi_to_hz(candidate))
        bin_high = int(np.argmin(np.abs(freqs - hz_high)))
        bin_low  = int(np.argmin(np.abs(freqs - hz_low)))

        if bin_high == bin_low:
            # FFT 解像度不足で区別できない → そのまま
            result.append((t_sec, midi))
            continue

        e_high = float(S[bin_high, f_start:f_end].max())
        e_low  = float(S[bin_low,  f_start:f_end].max())

        if e_high > 0 and (e_low / e_high) >= ratio_threshold:
            # 基音のエネルギーが十分 → オクターブ下が正しいと判断
            result.append((t_sec, candidate))
        else:
            result.append((t_sec, midi))

    return result


# ── 公開 API ───────────────────────────────────────────────────────────────────
def analyze(
    audio_path:  str,
    instrument:  str,
    chords:      Optional[List[str]] = None,
    key:         str = "",
    onset_threshold:   Optional[float] = None,   # None → 楽器別デフォルトを使用
    frame_threshold:   Optional[float] = None,
    minimum_note_length: Optional[float] = None,
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

    # 楽器別デフォルトパラメータ（呼び出し側が None で渡した場合に適用）
    defaults = _BP_PARAMS[instrument]
    ot = onset_threshold   if onset_threshold   is not None else defaults["onset_threshold"]
    ft = frame_threshold   if frame_threshold   is not None else defaults["frame_threshold"]

    # BPM は既存の librosa で取得（beat_track は basic-pitch 非依存）
    y, sr = librosa.load(audio_path, sr=None, mono=True, dtype=np.float32)
    bpm = _estimate_bpm(y, sr, audio_path=audio_path)

    # BPM 連動 minimum_note_length: 16分音符の83%を最小単位とする
    # (BPM=123時: 0.83×121≈100ms / フル16分より短いと_correct_bass_octavesの補正源音符が失われる)
    # 呼び出し側が明示した場合はその値を使う
    if minimum_note_length is not None:
        ml = minimum_note_length
    elif instrument == "bass":
        # 16分音符の 83% [ms] をベースの最小ノート長に設定 (下限 80 ms)
        ml = max(80, int(60.0 / bpm / 4 * 1000 * 0.83))
    else:
        ml = defaults["minimum_note_length"]

    # ── ニューラルネットワーク推論 ────────────────────────────────────────────
    midi_min, midi_max = _MIDI_RANGE[instrument]

    _, _, note_events = predict(
        audio_path,
        onset_threshold=ot,
        frame_threshold=ft,
        minimum_note_length=ml,
        minimum_frequency=librosa.midi_to_hz(midi_min),
        maximum_frequency=librosa.midi_to_hz(midi_max),
    )

    # note_events: List[Tuple] 各要素は
    #   (start_time_s, end_time_s, pitch_midi, velocity, pitch_bends)
    # basic-pitch の velocity は 0 固定のため音域フィルタのみ適用
    timed_notes: List[Tuple[float, int]] = [
        (float(ev[0]), int(ev[2]))
        for ev in note_events
        if midi_min <= ev[2] <= midi_max
    ]
    timed_notes.sort(key=lambda x: x[0])

    # モノフォニック化: ベースは単音楽器なので近傍ノートを間引く
    # 倍音補正を先に行い、その後モノフォニック化する
    # window = 16分音符の半分 (BPM連動) — 近すぎるノートを基音に集約
    if instrument == "bass":
        subdiv_sec = 60.0 / bpm / 4
        timed_notes = _correct_bass_octaves(timed_notes, y, sr, midi_min)
        timed_notes = _mono_filter(timed_notes, window_sec=subdiv_sec * 0.5)

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
