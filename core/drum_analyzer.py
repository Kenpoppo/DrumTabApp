"""
core/drum_analyzer.py
─────────────────────────────────────────────────────────────────────────────
ドラム解析モジュール。
attack_time_analysis.py / drum_sheet_generator.py / (旧)drum_analyzer.py
の機能をここに一本化し、重複ロジックを排除する。

改善点:
  - HPSS でパーカッシブ成分を分離してからオンセット検出（精度大幅向上）
  - スペクトル重心 + 低域比率 + 高域比率 の 3 特徴量による分類（誤分類削減）
  - DrumHit / DrumAnalysisResult データクラスで結果を型安全に管理
  - to_text() で GUI 表示用テキストを生成（ビジネスロジックと表示を分離）
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, List, Optional, Union

import numpy as np
import librosa

if TYPE_CHECKING:
    from core.analysis_session import AnalysisSession

# ── 共通定数 ──────────────────────────────────────────────────────────────────
SR         = 22_050   # リサンプリング後のサンプリングレート
HOP_LENGTH = 512
N_FFT      = 2_048

# モジュール初期化時に1回だけ計算（per-onset 計算を排除）
_FREQS_DRUM = np.fft.rfftfreq(N_FFT, d=1.0 / SR)   # (N_FFT//2+1,)
_LO_MASK    = (_FREQS_DRUM >= 20.0)  & (_FREQS_DRUM < 200.0)
_HI_MASK    = _FREQS_DRUM >= 5_000.0


# ── データモデル ───────────────────────────────────────────────────────────────
@dataclass
class DrumHit:
    """1 回のドラムヒットを表す。"""
    time:  float   # onset time (seconds)
    label: str     # "Kick" | "Snare" | "Hi-Hat" | "Unknown"


@dataclass
class DrumAnalysisResult:
    """analyze() の戻り値。"""
    bpm:                  float
    hits:                 List[DrumHit]
    zero_crossing_rate:   float
    spectral_centroid_hz: float
    mean_attack_interval: float    # seconds

    @property
    def onset_count(self) -> int:
        return len(self.hits)

    @property
    def kick_count(self) -> int:
        return sum(1 for h in self.hits if h.label == "Kick")

    @property
    def snare_count(self) -> int:
        return sum(1 for h in self.hits if h.label == "Snare")

    @property
    def hihat_count(self) -> int:
        return sum(1 for h in self.hits if h.label == "Hi-Hat")


# ── 内部ヘルパー ───────────────────────────────────────────────────────────────
def _classify_hits_batch(
    S: np.ndarray,
    onset_frames: np.ndarray,
) -> list:
    """
    STFT パワースペクトル S から全オンセットを一括で Kick/Snare/Hi-Hat に分類する。

    旧 _classify_hit() を per-onset FFT ループから numpy ベクトル演算に置き換え。
    特徴量はモジュール定数の _FREQS_DRUM / _LO_MASK / _HI_MASK を流用する。

    S shape: (freq_bins, n_frames)  — librosa.stft の |magnitude|^2
    onset_frames: 各オンセットのフレームインデックス
    """
    frames = np.clip(onset_frames, 0, S.shape[1] - 1)

    # 全オンセットのパワー行列: (freq_bins, n_onsets)
    powers = S[:, frames]
    total  = powers.sum(axis=0) + 1e-10          # (n_onsets,)

    # 無音判定: パーセバルの定理より total/N_FFT ≈ mean(x^2)
    rms_proxy = np.sqrt(total / N_FFT)
    silent    = rms_proxy < 1e-4

    # 3 特徴量を一括計算
    centroid = (_FREQS_DRUM[:, None] * powers).sum(axis=0) / total  # (n_onsets,)
    low_r    = powers[_LO_MASK].sum(axis=0) / total                 # (n_onsets,)
    high_r   = powers[_HI_MASK].sum(axis=0) / total                 # (n_onsets,)

    # 分類ルール（優先度順・ベクトル演算）
    is_hihat = (centroid > 5_000) | ((centroid > 4_000) & (high_r > 0.20))
    is_kick  = ~is_hihat & ((centroid < 1_500) | ((centroid < 2_500) & (low_r > 0.45)))

    labels = np.where(silent, "Unknown",
             np.where(is_hihat, "Hi-Hat",
             np.where(is_kick,  "Kick", "Snare")))
    return labels.tolist()


# ── 公開 API ───────────────────────────────────────────────────────────────────
def analyze(source: Union[str, AnalysisSession]) -> DrumAnalysisResult:
    """
    音源ファイルを解析して DrumAnalysisResult を返す。

    source には str (ファイルパス) または AnalysisSession を渡せる。
    AnalysisSession を渡すと audio/HPSS/BPM を他モジュールと共有してゼロコストで再利用する。

    処理フロー:
      1. audio_22k / hpss_22k / bpm  → AnalysisSession（joblib ディスクキャッシュ）から取得
      2. onset_detect  → パーカッシブ成分上でオンセット検出
      3. _classify_hits_batch → STFT 一括でドラム種別を分類
    """
    if isinstance(source, str):
        from core.analysis_session import AnalysisSession as _AS
        source = _AS(source)

    y, sr     = source.audio_22k    # 22050 Hz (ドラム解析用固定 SR)
    _, y_perc = source.hpss_22k    # パーカッシブ成分
    bpm       = source.bpm         # 全モジュール共通 BPM

    # オンセット検出（パーカッシブ成分で実施）
    onset_env_perc = librosa.onset.onset_strength(y=y_perc, sr=sr, hop_length=HOP_LENGTH)
    onset_frames = librosa.onset.onset_detect(
        onset_envelope=onset_env_perc, sr=sr, hop_length=HOP_LENGTH,
        units="frames", backtrack=True,
        pre_max=3, post_max=3, pre_avg=5, post_avg=5,
        delta=0.05,
        wait=5,
    )
    onset_times = librosa.frames_to_time(onset_frames, sr=sr, hop_length=HOP_LENGTH)

    # 元信号の STFT を1回だけ計算して全オンセットを一括分類
    S = np.abs(librosa.stft(y, n_fft=N_FFT, hop_length=HOP_LENGTH)) ** 2
    hit_labels = _classify_hits_batch(S, onset_frames)
    hits = [
        DrumHit(time=float(t), label=lb)
        for t, lb in zip(onset_times, hit_labels)
    ]

    # サマリー統計量
    intervals = np.diff(onset_times)
    zcr  = float(np.mean(librosa.feature.zero_crossing_rate(y)))
    cent = float(np.mean(librosa.feature.spectral_centroid(y=y, sr=sr)))

    return DrumAnalysisResult(
        bpm=bpm,
        hits=hits,
        zero_crossing_rate=zcr,
        spectral_centroid_hz=cent,
        mean_attack_interval=float(np.mean(intervals)) if len(intervals) else 0.0,
    )


def to_text(result: DrumAnalysisResult,
            chords: Optional[List[str]] = None,
            key: str = "") -> str:
    """
    DrumAnalysisResult をドラムタブ譜テキストに変換する。

    出力形式（16 分音符グリッド）:
      - 各列 = 1 つの 16 分音符
      - 行   = 楽器（HH / SN / BD）
      - x    = ヒット、- = 無音
      - |    = 拍区切り（4 分音符）、|| = 小節区切り、各 2 小節で折り返し
      - chords 指定時: 各行の上に小節コード行を挿入
    """
    bpm = result.bpm
    _DIV = 4                                     # 1 拍あたりの分割数（16th note）
    subdiv_sec = 60.0 / bpm / _DIV
    cols_per_measure = 4 * _DIV                  # = 16（4/4 拍子）
    measures_per_line = 2
    cols_per_line = measures_per_line * cols_per_measure   # = 32

    # ── ヒットをグリッドにマッピング ─────────────────────────────────────────
    hh_cols: set = set()
    sn_cols: set = set()
    bd_cols: set = set()
    for hit in result.hits:
        col = int(round(hit.time / subdiv_sec))
        if hit.label == "Hi-Hat":
            hh_cols.add(col)
        elif hit.label == "Snare":
            sn_cols.add(col)
        elif hit.label == "Kick":
            bd_cols.add(col)

    all_hits = hh_cols | sn_cols | bd_cols
    if not all_hits:
        return (
            "──────────────────────────────────────────────\n"
            " Drum Tab\n"
            "──────────────────────────────────────────────\n"
            " ヒットが検出されませんでした。\n"
        )

    max_col = max(all_hits)

    # ビートラベル: 1小節 = ドラム標準カウント表記 "1e+a|2e+a|3e+a|4e+a" (16 文字)
    # "1イーアンドアー" の第1・3拍目のサブ分割を直規
    _BEAT_LABEL = ["1","e","+","a","2","e","+","a",
                   "3","e","+","a","4","e","+","a"]

    header = (
        "─" * 58 + "\n"
        f" Drum Tab  |  BPM: {bpm:.1f}"
        + (f"  |  Key: {key}" if key else "")
        + f"  |  Kick:{result.kick_count}"
        f" / Snare:{result.snare_count}"
        f" / HH:{result.hihat_count}\n"
        + "─" * 58 + "\n"
    )
    output = [header]

    rows_def = [
        ("HH", hh_cols),
        ("SN", sn_cols),
        ("BD", bd_cols),
    ]

    for line_start in range(0, max_col + cols_per_line, cols_per_line):
        line_end = line_start + cols_per_line

        # コード行: 小節ごとにコード名を表示（chords が指定された場合）
        # 各小節の表示幅 = cols_per_measure列 × 1文字 + 3ビート区切り = 19文字
        _MEASURE_DISP_WIDTH = cols_per_measure + (cols_per_measure // _DIV - 1)

        # 小節番号行: 行の先頭に何小節目かを表示
        mnum_parts = []
        for m in range(measures_per_line):
            midx = line_start // cols_per_measure + m
            mnum = f"m.{midx + 1}"
            mnum_parts.append(f"{mnum:<{_MEASURE_DISP_WIDTH}}")
        mnum_row = "     |" + "||".join(mnum_parts) + "|"
        output.append(mnum_row)

        if chords is not None:
            chord_parts = []
            for m in range(measures_per_line):
                midx = line_start // cols_per_measure + m
                chord = chords[midx] if midx < len(chords) else ""
                chord_parts.append(f"{chord:<{_MEASURE_DISP_WIDTH}}")
            chord_row = "     |" + "||".join(chord_parts) + "|"
            output.append(chord_row)

        # カウンター行（拍番号）
        cnt = "     |"
        for col in range(line_start, line_end):
            rel = col - line_start
            if rel > 0 and rel % cols_per_measure == 0:
                cnt += "||"
            elif rel > 0 and rel % _DIV == 0:
                cnt += "|"
            cnt += _BEAT_LABEL[rel % cols_per_measure]
        cnt += "|"
        output.append(cnt)

        # 楽器行（HH / SN / BD）
        # 標準ASCIIドラムtab記号: HH=x(クローズドハイハット) / SN=o(スネアヒット) / BD=o(バスドラムヒット)
        for abbr, cols in rows_def:
            hit_char = "x" if abbr == "HH" else "o"
            row = f" {abbr:<3} |"
            for col in range(line_start, line_end):
                rel = col - line_start
                if rel > 0 and rel % cols_per_measure == 0:
                    row += "||"
                elif rel > 0 and rel % _DIV == 0:
                    row += "|"
                row += hit_char if col in cols else "-"
            row += "|"
            output.append(row)

        output.append("")   # 行間スペース

    return "\n".join(output)
