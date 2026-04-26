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
from typing import List, Optional

import numpy as np
import librosa

# ── 共通定数 ──────────────────────────────────────────────────────────────────
SR         = 22_050   # リサンプリング後のサンプリングレート
HOP_LENGTH = 512
N_FFT      = 2_048


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
def _band_power(power: np.ndarray, freqs: np.ndarray, lo: float, hi: float) -> float:
    mask = (freqs >= lo) & (freqs < hi)
    return float(power[mask].sum())


def _classify_hit(y: np.ndarray, sr: int, frame: int, hop: int) -> str:
    """
    1 オンセットを Kick / Snare / Hi-Hat に分類する。

    実データ診断に基づく閾値設計（金木犀 feat.Ado 解析結果より）:
      - centroid median=367 Hz, 76% が < 1500 Hz → Kick は低重心が支配的
      - Hi-Hat: centroid > 5000 Hz が最も信頼性の高い指標
      - Snare : 中間帯（1500-5000 Hz）でかつ低域比率が低いもの

    特徴量:
      1. spectral_centroid : スペクトル重心 [Hz] — 主判定
      2. low_r             : 20-200 Hz エネルギー比 — Kick 補助判定
      3. high_r            : 5 kHz+ エネルギー比   — Hi-Hat 補助判定
    """
    center = frame * hop
    window = y[max(0, center - hop): center + hop]
    if len(window) < 64:
        return "Unknown"

    # 無音ウィンドウはスキップ（RMS が極小の場合）
    if float(np.sqrt(np.mean(window ** 2))) < 1e-4:
        return "Unknown"

    power = np.abs(np.fft.rfft(window, n=N_FFT)) ** 2
    freqs = np.fft.rfftfreq(N_FFT, d=1.0 / sr)
    total = power.sum() + 1e-10

    centroid = float((freqs * power).sum() / total)
    low_r    = _band_power(power, freqs, 20.0,    200.0)  / total
    high_r   = _band_power(power, freqs, 5_000.0, sr / 2.0) / total

    # 判定ルール（優先度順）
    # Hi-Hat: 重心が 5 kHz を超えれば確定。高域比率が十分なら 4 kHz でも判定
    if centroid > 5_000 or (centroid > 4_000 and high_r > 0.20):
        return "Hi-Hat"
    # Kick: 重心が 1500 Hz 未満なら確定。中域重心でも低域比率が高ければ Kick
    if centroid < 1_500 or (centroid < 2_500 and low_r > 0.45):
        return "Kick"
    return "Snare"


# ── 公開 API ───────────────────────────────────────────────────────────────────
def analyze(audio_path: str) -> DrumAnalysisResult:
    """
    音源ファイルを解析して DrumAnalysisResult を返す。

    処理フロー:
      1. librosa.load  → モノラル float32 に統一
      2. HPSS          → パーカッシブ成分のみ抽出（オンセット検出精度向上）
      3. beat_track    → BPM 推定
      4. onset_detect  → パーカッシブ成分上でオンセット検出
      5. _classify_hit → 元の信号（フル帯域）でドラム種別を分類
    """
    y, sr = librosa.load(audio_path, sr=SR, mono=True, dtype=np.float32)

    # HPSS: パーカッシブ成分でオンセット検出 → ノイズによる誤検出を抑制
    _, y_perc = librosa.effects.hpss(y, margin=3.0)

    # BPM
    tempo, _ = librosa.beat.beat_track(y=y_perc, sr=sr, hop_length=HOP_LENGTH)
    bpm = float(np.atleast_1d(tempo)[0])

    # オンセット検出（パーカッシブ成分で実施）
    onset_frames = librosa.onset.onset_detect(
        y=y_perc, sr=sr, hop_length=HOP_LENGTH,
        units="frames", backtrack=True,
        pre_max=3, post_max=3, pre_avg=5, post_avg=5,
        delta=0.05,  # 0.07 → 0.05: 弱いHi-Hatオンセットを捉えるため感度向上
        wait=5,      # 0.07 → 5: 16分音符Hi-Hat間隔(~5.4 frames@123BPM)を検出
    )
    onset_times = librosa.frames_to_time(onset_frames, sr=sr, hop_length=HOP_LENGTH)

    # 分類は元信号（フル帯域）で行う → 周波数特性を正確に反映
    hits = [
        DrumHit(time=float(t), label=_classify_hit(y, sr, int(f), HOP_LENGTH))
        for t, f in zip(onset_times, onset_frames)
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
