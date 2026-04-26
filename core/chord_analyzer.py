"""
core/chord_analyzer.py
─────────────────────────────────────────────────────────────────────────────
キー検出 & 小節別コード進行解析モジュール。

アルゴリズム:
  - キー検出  : Krumhansl-Schmuckler プロファイル相関法
  - コード検出: chroma_cqt + コサイン類似度テンプレートマッチング
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Tuple

import numpy as np
import librosa

# ── Krumhansl-Schmuckler キープロファイル ─────────────────────────────────────
# 各ピッチクラスが Major / Minor スケールでどれだけ重要かを表す重み
_KS_MAJOR = np.array([6.35, 2.23, 3.48, 2.33, 4.38, 4.09,
                       2.52, 5.19, 2.39, 3.66, 2.29, 2.88])
_KS_MINOR = np.array([6.33, 2.68, 3.52, 5.38, 2.60, 3.53,
                       2.54, 4.75, 3.98, 2.69, 3.34, 3.17])

_NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]

# ── コードテンプレート（ルート音からの半音インターバル） ────────────────────────
_CHORD_TYPES: Dict[str, List[int]] = {
    "":    [0, 4, 7],          # Major (3和音)
    "m":   [0, 3, 7],          # minor (3和音)
    "7":   [0, 4, 7, 10],      # dominant 7th
    "m7":  [0, 3, 7, 10],      # minor 7th
    "M7":  [0, 4, 7, 11],      # major 7th
    "dim": [0, 3, 6],          # diminished
    "sus4":[0, 5, 7],          # sus4
}


def _build_chord_templates() -> Tuple[List[np.ndarray], List[str]]:
    """全ルート × 全コードタイプの正規化済みテンプレートを生成する。"""
    templates: List[np.ndarray] = []
    names: List[str] = []
    for root in range(12):
        for suffix, intervals in _CHORD_TYPES.items():
            tmpl = np.zeros(12)
            for i in intervals:
                tmpl[(root + i) % 12] = 1.0
            templates.append(tmpl / np.linalg.norm(tmpl))
            names.append(f"{_NOTE_NAMES[root]}{suffix}")
    return templates, names


_CHORD_TEMPLATES, _CHORD_NAMES = _build_chord_templates()


# ── データモデル ───────────────────────────────────────────────────────────────
@dataclass
class ChordAnalysisResult:
    """analyze() の戻り値。"""
    key:               str         # e.g. "A Minor", "C Major"
    key_confidence:    float       # 0.0 〜 1.0
    chord_per_measure: List[str]   # インデックス = 小節番号 (0-based)
    bpm:               float


# ── 公開 API ───────────────────────────────────────────────────────────────────
def analyze(audio_path: str) -> ChordAnalysisResult:
    """
    音源のキーとコード進行（小節別）を解析する。

    処理フロー:
      1. librosa.load         → モノラル float32
      2. chroma_cqt           → クロマ特徴量（12次元ピッチクラス分布）
      3. Krumhansl-Schmuckler → 全24キーとの相関でキー推定
      4. beat_track           → ビートグリッド取得
      5. 小節ごとに chroma 平均 → コードテンプレートとコサイン類似度照合
    """
    y, sr = librosa.load(audio_path, sr=None, mono=True, dtype=np.float32)
    hop = 512

    # chroma_cqt: CQT ベースのクロマ（ピッチ精度が chroma_stft より高い）
    chroma = librosa.feature.chroma_cqt(y=y, sr=sr, hop_length=hop)

    # BPM & ビートフレーム（全信号から推定）
    tempo, beat_frames = librosa.beat.beat_track(y=y, sr=sr, hop_length=hop)
    bpm = float(np.atleast_1d(tempo)[0])
    if bpm < 40.0:
        bpm = 120.0

    # キー検出
    chroma_sum = chroma.sum(axis=1)
    key, key_conf = _detect_key(chroma_sum)

    # 小節ごとのコード検出（4/4 拍子を仮定）
    chords = _detect_chords_per_measure(chroma, beat_frames, beats_per_measure=4)

    return ChordAnalysisResult(
        key=key,
        key_confidence=key_conf,
        chord_per_measure=chords,
        bpm=bpm,
    )


# ── 内部ヘルパー ───────────────────────────────────────────────────────────────
def _detect_key(chroma_sum: np.ndarray) -> Tuple[str, float]:
    """
    Krumhansl-Schmuckler アルゴリズムでキーを推定する。

    曲全体のクロマ分布と 24 キー（12 Major + 12 minor）のプロファイルを
    Pearson 相関係数で比較し、最も相関の高いキーを返す。
    """
    best_score = -np.inf
    best_key = "C Major"
    all_scores: List[float] = []

    for root in range(12):
        for profile, mode in [(_KS_MAJOR, "Major"), (_KS_MINOR, "Minor")]:
            rotated = np.roll(profile, root)
            # corrcoef は 2x2 行列を返すので [0,1] が相関係数
            corr = float(np.corrcoef(chroma_sum, rotated)[0, 1])
            all_scores.append(corr)
            if corr > best_score:
                best_score = corr
                best_key = f"{_NOTE_NAMES[root]} {mode}"

    arr = np.array(all_scores)
    confidence = float((best_score - arr.min()) / (arr.max() - arr.min() + 1e-10))
    return best_key, confidence


def _detect_chords_per_measure(
    chroma: np.ndarray,
    beat_frames: np.ndarray,
    beats_per_measure: int,
) -> List[str]:
    """
    各小節の平均クロマをコードテンプレートと照合してコード名を返す。

    小節境界はビートフレームを beats_per_measure おきに間引いて算出。
    """
    n_frames = chroma.shape[1]
    chords: List[str] = []

    measure_starts = beat_frames[::beats_per_measure]

    for i, start in enumerate(measure_starts):
        end = int(measure_starts[i + 1]) if i + 1 < len(measure_starts) else n_frames
        segment = chroma[:, int(start):end]
        if segment.shape[1] == 0:
            chords.append("-")
            continue
        chords.append(_match_chord(segment.mean(axis=1)))

    return chords


def _match_chord(chroma_vec: np.ndarray) -> str:
    """コサイン類似度でコードテンプレートと照合し、最適なコード名を返す。"""
    norm = float(np.linalg.norm(chroma_vec))
    if norm < 1e-6:
        return "-"
    chroma_norm = chroma_vec / norm
    scores = [float(np.dot(chroma_norm, tmpl)) for tmpl in _CHORD_TEMPLATES]
    return _CHORD_NAMES[int(np.argmax(scores))]
