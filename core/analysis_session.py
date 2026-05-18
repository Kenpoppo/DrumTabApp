"""
core/analysis_session.py
─────────────────────────────────────────────────────────────────────────────
解析セッション — 1 ファイルに対する高コスト前処理を
Lazy Evaluation + joblib ディスクキャッシュで共有する。

## 解消する重複

Guitar TAB 生成だけで以下が走っていた:
  chord_analyzer : load + chroma + beat_track
  pitch_analyzer : load + HPSS + _estimate_bpm (×6 beat_track)

AnalysisSession を挟むと:
  load  → 1 回（joblib ディスクキャッシュ）
  HPSS  → 1 回（joblib ディスクキャッシュ）
  BPM   → 1 回（joblib ディスクキャッシュ）

2 回目以降（同じ曲を再解析）は全て即座に返る。

## スレッドセーフ

Double-checked locking で並列 analyze() 呼び出しでも前処理は 1 回のみ。
"""
from __future__ import annotations

import os
import threading
from typing import Any, Dict, Tuple, Union

import numpy as np

# ── joblib ディスクキャッシュ（requirements.txt に joblib==1.5.3 記載済み）──────
from joblib import Memory as _Memory

_CACHE_DIR = os.path.join(os.path.expanduser("~"), ".cache", "DrumTabApp")
_mem = _Memory(_CACHE_DIR, verbose=0)

_SR_DRUM = 22_050  # ドラム解析用固定 SR

# ─────────────────────────────────────────────────────────────────────────────
# joblib でキャッシュする純関数（引数はすべてスカラー → ハッシュが高速）
# ─────────────────────────────────────────────────────────────────────────────

@_mem.cache
def _cached_load(path: str, sr_key: str, mtime: float) -> Tuple[np.ndarray, int]:
    """
    音声ファイルをロードしてディスクキャッシュに保存する。
    sr_key : "None" → ネイティブ SR, "22050" → リサンプリング
    mtime  : ファイル更新日時（キャッシュ無効化キー）
    """
    import librosa
    sr = None if sr_key == "None" else int(sr_key)
    return librosa.load(path, sr=sr, mono=True, dtype=np.float32)


@_mem.cache
def _cached_hpss(path: str, sr_key: str, mtime: float) -> Tuple[np.ndarray, np.ndarray]:
    """HPSS をディスクキャッシュ付きで計算する（margin=3.0 固定）。"""
    import librosa
    y, _ = _cached_load(path, sr_key, mtime)
    return librosa.effects.hpss(y, margin=3.0)


@_mem.cache
def _cached_bpm(path: str, mtime: float) -> float:
    """
    全モジュール共通の BPM をディスクキャッシュ付きで推定する。

    優先順位:
      1. 同ディレクトリの drums.wav（最も安定）
      2. 22050 Hz パーカッシブ成分 + 複数 start_bpm 候補
    """
    import librosa

    # ── drums.wav 優先 ─────────────────────────────────────────────────────
    drums_path = os.path.join(os.path.dirname(path), "drums.wav")
    if os.path.isfile(drums_path) and drums_path != path:
        try:
            d_mtime = os.path.getmtime(drums_path)
            y_d, sr_d = _cached_load(drums_path, "None", d_mtime)
            t, _ = librosa.beat.beat_track(y=y_d, sr=sr_d, start_bpm=120.0)
            bpm = float(np.atleast_1d(t)[0])
            if 60.0 <= bpm <= 200.0:
                return bpm
        except Exception:
            pass

    # ── パーカッシブ成分から多候補推定（フォールバック）─────────────────────
    _, y_perc = _cached_hpss(path, "22050", mtime)
    onset_env = librosa.onset.onset_strength(y=y_perc, sr=_SR_DRUM, hop_length=512)
    candidates = []
    for start in [60, 75, 90, 100, 120, 140]:
        t, beats = librosa.beat.beat_track(
            onset_envelope=onset_env, sr=_SR_DRUM, hop_length=512,
            start_bpm=float(start),
        )
        bpm_c = float(np.atleast_1d(t)[0])
        if 60.0 <= bpm_c <= 200.0 and len(beats):
            candidates.append((bpm_c, float(onset_env[beats].mean())))
    if not candidates:
        return 120.0
    return max(candidates, key=lambda x: x[1])[0]


# ─────────────────────────────────────────────────────────────────────────────
# AnalysisSession
# ─────────────────────────────────────────────────────────────────────────────

class AnalysisSession:
    """
    1 つの音源ファイルに対する前処理を Lazy Evaluation + ディスクキャッシュで共有。

    使い方:
        session = AnalysisSession(path)
        chord_result  = chord_analyzer.analyze(session)
        drum_result   = drum_analyzer.analyze(session)
        guitar_result = pitch_analyzer.analyze(session, "guitar",
                            chords=chord_result.chord_per_measure,
                            key=chord_result.key)

    各 analyze() は session.audio_native / session.hpss_22k / session.bpm を
    共有するため、HPSS と BPM 推定はファイル全体を通じて 1 回だけ実行される。
    """

    def __init__(self, path: str) -> None:
        if not os.path.isfile(path):
            raise FileNotFoundError(f"音源ファイルが見つかりません: {path}")
        self.path   = path
        self._mtime = os.path.getmtime(path)
        self._lock  = threading.Lock()
        self._mem:  Dict[str, Any] = {}

    # ── 内部 Lazy Evaluation ──────────────────────────────────────────────────

    def _lazy(self, key: str, fn) -> Any:
        """Double-checked locking による Lazy Evaluation。"""
        if key in self._mem:
            return self._mem[key]
        with self._lock:
            if key not in self._mem:
                self._mem[key] = fn()
        return self._mem[key]

    # ── 音声ロード ────────────────────────────────────────────────────────────

    @property
    def audio_native(self) -> Tuple[np.ndarray, int]:
        """ネイティブ SR で読み込んだ (y, sr)。ピッチ解析・コード解析に使用。"""
        return self._lazy("audio_native",
            lambda: _cached_load(self.path, "None", self._mtime))

    @property
    def audio_22k(self) -> Tuple[np.ndarray, int]:
        """22050 Hz にリサンプリングした (y, 22050)。ドラム解析に使用。"""
        return self._lazy("audio_22k",
            lambda: _cached_load(self.path, "22050", self._mtime))

    # ── HPSS ─────────────────────────────────────────────────────────────────

    @property
    def hpss_native(self) -> Tuple[np.ndarray, np.ndarray]:
        """ネイティブ SR での (y_harm, y_perc)。ギター/ベース piptrack に使用。"""
        return self._lazy("hpss_native",
            lambda: _cached_hpss(self.path, "None", self._mtime))

    @property
    def hpss_22k(self) -> Tuple[np.ndarray, np.ndarray]:
        """22050 Hz での (y_harm_22k, y_perc_22k)。ドラムオンセット検出に使用。"""
        return self._lazy("hpss_22k",
            lambda: _cached_hpss(self.path, "22050", self._mtime))

    # ── BPM ──────────────────────────────────────────────────────────────────

    @property
    def bpm(self) -> float:
        """
        全モジュール共通の BPM。drums.wav 優先、次いでパーカッシブ成分から推定。
        ディスクキャッシュ済みのため 2 回目以降は即座に返る。
        """
        return self._lazy("bpm",
            lambda: _cached_bpm(self.path, self._mtime))
