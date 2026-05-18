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
from typing import TYPE_CHECKING, Any, Dict, List, Tuple, Union

import numpy as np
import librosa

if TYPE_CHECKING:
    from core.analysis_session import AnalysisSession

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
# 全テンプレートを行列にまとめて保持（_match_chord でのループを行列積に置換）
_CHORD_TEMPLATE_MATRIX = np.stack(_CHORD_TEMPLATES)  # (84, 12)

# _detect_key 用: 全 24 キープロファイルを事前構築（12 major + 12 minor）
# 行順: (root=0,Major), (root=0,Minor), (root=1,Major), (root=1,Minor), ...
_ALL_PROFILES = np.array([
    np.roll(p, r)
    for r in range(12)
    for p in (_KS_MAJOR, _KS_MINOR)
])  # (24, 12)


# ── データモデル ───────────────────────────────────────────────────────────────
@dataclass
class ChordAnalysisResult:
    """analyze() の戻り値。"""
    key:               str         # e.g. "A Minor", "C Major"
    key_confidence:    float       # 0.0 〜 1.0
    chord_per_measure: List[str]   # インデックス = 小節番号 (0-based)
    bpm:               float


# ── 公開 API ───────────────────────────────────────────────────────────────────
def analyze(source: Union[str, AnalysisSession]) -> ChordAnalysisResult:
    """
    音源のキーとコード進行（小節別）を解析する。

    source には str (ファイルパス) または AnalysisSession を渡せる。

    処理フロー:
      1. audio_native → AnalysisSession（joblib ディスクキャッシュ）から取得
      2. chroma_cqt   → クロマ特徴量（12次元ピッチクラス分布）
      3. Krumhansl-Schmuckler → 全24キーとの相関でキー推定
      4. beat_track   → ビートグリッド取得（小節境界算出に必要）
      5. 小節ごとに chroma 平均 → コードテンプレートとコサイン類似度照合
    """
    if isinstance(source, str):
        from core.analysis_session import AnalysisSession as _AS
        source = _AS(source)

    y, sr = source.audio_native
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
    24 回の np.corrcoef 呼び出しをベクトル演算1回に集約。
    """
    # _ALL_PROFILES shape: (24, 12)
    x = chroma_sum - chroma_sum.mean()
    y_c = _ALL_PROFILES - _ALL_PROFILES.mean(axis=1, keepdims=True)

    x_std = x.std() + 1e-10
    y_std = _ALL_PROFILES.std(axis=1) + 1e-10         # (24,)

    # Pearson r = dot(x, y_centered[i]) / (n * std_x * std_y[i])
    corrs = (y_c @ x) / (len(chroma_sum) * x_std * y_std)  # (24,)

    best_idx = int(np.argmax(corrs))
    best_score = corrs[best_idx]
    root = best_idx // 2
    mode = "Major" if best_idx % 2 == 0 else "Minor"
    best_key = f"{_NOTE_NAMES[root]} {mode}"

    confidence = float(
        (best_score - corrs.min()) / (corrs.max() - corrs.min() + 1e-10)
    )
    return best_key, confidence


def _detect_chords_per_measure(
    chroma: np.ndarray,
    beat_frames: np.ndarray,
    beats_per_measure: int,
) -> List[str]:
    """
    各小節の平均クロマをコードテンプレートと照合してコード名を返す。

    小節境界はビートフレームを beats_per_measure おきに間引いて算出。
    全小節の照合を1回の行列積にまとめて高速化。
    """
    n_frames = chroma.shape[1]
    measure_starts = beat_frames[::beats_per_measure]
    n_measures = len(measure_starts)

    # 各小節のクロマ平均を一括計算
    chroma_means = np.zeros((n_measures, 12), dtype=np.float32)
    empty = np.zeros(n_measures, dtype=bool)
    for i, start in enumerate(measure_starts):
        end = int(measure_starts[i + 1]) if i + 1 < n_measures else n_frames
        seg = chroma[:, int(start):end]
        if seg.shape[1] == 0:
            empty[i] = True
        else:
            chroma_means[i] = seg.mean(axis=1)

    # 正規化 + 有効小節マスク
    norms  = np.linalg.norm(chroma_means, axis=1, keepdims=True)     # (n_measures, 1)
    valid  = (~empty) & (norms.squeeze(1) >= 1e-6)

    chords = ["-"] * n_measures
    if valid.any():
        normed     = chroma_means[valid] / norms[valid]               # (n_valid, 12)
        # 一括コサイン類似度: (n_valid, 12) @ (12, 84) → (n_valid, 84)
        scores     = normed @ _CHORD_TEMPLATE_MATRIX.T
        best_idxs  = np.argmax(scores, axis=1)
        vi = np.where(valid)[0]
        for j, idx in zip(vi, best_idxs):
            chords[j] = _CHORD_NAMES[int(idx)]

    return chords


def _match_chord(chroma_vec: np.ndarray) -> str:
    """コサイン類似度でコードテンプレートと照合し、最適なコード名を返す。"""
    norm = float(np.linalg.norm(chroma_vec))
    if norm < 1e-6:
        return "-"
    chroma_norm = chroma_vec / norm
    # 行列積で84テンプレートを一括照合（Python ループを排除）
    scores = _CHORD_TEMPLATE_MATRIX @ chroma_norm     # (84,)
    return _CHORD_NAMES[int(np.argmax(scores))]
