"""
core/pitch_analyzer.py
─────────────────────────────────────────────────────────────────────────────
ギター / ベース ピッチ解析 & TAB 生成モジュール。
旧 tab_generator.py を完全に置き換える。

改善点:
  - HPSS で倍音成分のみ抽出してから piptrack を実行（ノイズ誤検出を大幅削減）
  - マグニチュード閾値 + 連続同一音符のデデュプリケーション
  - BPM グリッドに量子化したビートアライン TAB（音楽的に意味のある表示）
  - TabResult データクラスで結果を型安全に管理
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import numpy as np
import librosa

# ── 定数 ──────────────────────────────────────────────────────────────────────
_MAG_THRESHOLD = 8.0    # piptrack マグニチュード閾値のフォールバック値（適応閾値が使えない場合に使用）
_SUBDIVISIONS  = 4      # 1 拍あたりの分割数（16th note = 4 で高解像度TAB）
_MEASURES_PER_LINE = 2  # TAB 1 行あたりの小節数（SUBDIVISIONS=4 時に行長を適切に保つ）
_COLS_PER_MEASURE  = 4 * _SUBDIVISIONS   # 小節あたりの列数 (4/4 拍子)

# 弦チューニング: 各弦の開放弦 MIDI ノート番号（高弦→低弦順）
# ベース: E1=28, A1=33, D2=38, G2=43 が標準4弦ベースチューニング
_TUNINGS: Dict[str, List[int]] = {
    "guitar": [64, 59, 55, 50, 45, 40],   # e4 B3 G3 D3 A2 E2
    "bass":   [43, 38, 33, 28],           # G2 D2 A1 E1 (標準ベースチューニング)
}
_STRING_NAMES: Dict[str, List[str]] = {
    "guitar": ["e", "B", "G", "D", "A", "E"],
    "bass":   ["G", "D", "A", "E"],
}

# 楽器別 MIDI 音域: 音域外の誤検出(倍音など)を除去
_MIDI_RANGE: Dict[str, Tuple[int, int]] = {
    "guitar": (40, 88),   # E2 〜 E6
    "bass":   (28, 67),   # E1 〜 G4 (G弦24フレット=43+24=67)
}

# 楽器別 piptrack fmin: 開放弦最低音より下から検索して基音を確実に捉える
_FMIN: Dict[str, float] = {
    "guitar": librosa.note_to_hz("D2"),   # ~73 Hz (ギター低E=82 Hzより少し下)
    "bass":   librosa.note_to_hz("C1"),   # ~33 Hz (ベース低E=41 Hzより下)
}


# ── データモデル ───────────────────────────────────────────────────────────────
@dataclass
class TabResult:
    """analyze() の戻り値。"""
    instrument: str
    tab_text:   str
    note_count: int
    bpm:        float


# ── 公開 API ───────────────────────────────────────────────────────────────────
def analyze(audio_path: str, instrument: str,
            chords: Optional[List[str]] = None,
            key: str = "") -> TabResult:
    """
    音源を解析してビートアライン TAB を生成する。

    処理フロー:
      1. librosa.load    → モノラル
      2. HPSS            → 倍音成分（ハーモニック）のみ抽出
      3. beat_track      → BPM / ビートグリッド取得
      4. piptrack        → 倍音成分上でフレーム毎ピッチ検出
      5. 閾値 + dedup    → ノイズ / 連続同一音のフィルタ
      6. 量子化          → BPM グリッドに最近傍スナップ
      7. _render_tab     → 小節単位の TAB テキスト生成
    """
    if instrument not in _TUNINGS:
        raise ValueError(f"未対応の楽器です: {instrument}  (guitar / bass のみ対応)")

    y, sr = librosa.load(audio_path, sr=None, mono=True, dtype=np.float32)

    # HPSS: 倍音成分でピッチ検出 → ドラムや打音によるピッチ誤検出を抑制
    y_harm, _ = librosa.effects.hpss(y, margin=3.0)

    # BPM 推定（元信号で行うほうが安定）
    tempo, _ = librosa.beat.beat_track(y=y, sr=sr)
    bpm = float(np.atleast_1d(tempo)[0])
    if bpm < 40.0:
        bpm = 120.0   # 非音楽的な推定値のフォールバック

    # ピッチ検出（倍音成分で実施）
    # fmin で楽器の最低音付近から探索して基音を確実に捉える
    hop_length = 512
    fmin = _FMIN[instrument]
    pitches, magnitudes = librosa.piptrack(
        y=y_harm, sr=sr, hop_length=hop_length, fmin=fmin
    )

    # 適応的マグニチュード閾値: 非ゼロ値の上位 20% のみを有効とする
    # 音源レベルに依らず安定した検出を保証（固定値 8.0 は音源によって不適切になる）
    mag_flat = magnitudes[magnitudes > 0]
    mag_threshold = (
        float(np.percentile(mag_flat, 80)) if len(mag_flat) > 0 else _MAG_THRESHOLD
    )

    midi_min, midi_max = _MIDI_RANGE[instrument]

    # フレームごとに最大マグニチュードのビンを採用 + 閾値フィルタ + 連続 dedup
    timed_notes: List[Tuple[float, int]] = []   # (time_sec, midi_note)
    prev_midi: Optional[int] = None
    for t in range(pitches.shape[1]):
        mag_idx = int(magnitudes[:, t].argmax())
        mag     = magnitudes[mag_idx, t]
        pitch   = pitches[mag_idx, t]

        if mag < mag_threshold or pitch <= 0.0:
            prev_midi = None   # 無音区間でリセット
            continue

        midi = int(round(librosa.hz_to_midi(pitch)))

        # 楽器音域外（倍音・ノイズ誤検出）を除去
        if midi < midi_min or midi > midi_max:
            prev_midi = None
            continue

        if midi == prev_midi:
            continue   # 連続同一音は 1 回だけ記録

        timed_notes.append((t * hop_length / sr, midi))
        prev_midi = midi

    if not timed_notes:
        return TabResult(
            instrument=instrument,
            tab_text="音符が検出されませんでした。\n音源に十分な旋律が含まれているか確認してください。",
            note_count=0,
            bpm=bpm,
        )

    tab_text = _render_tab(timed_notes, instrument, bpm, chords=chords, key=key)
    return TabResult(instrument=instrument, tab_text=tab_text, note_count=len(timed_notes), bpm=bpm)


# ── 内部ヘルパー ───────────────────────────────────────────────────────────────
def _render_tab(
    timed_notes: List[Tuple[float, int]],
    instrument:  str,
    bpm:         float,
    chords:      Optional[List[str]] = None,
    key:         str = "",
) -> str:
    """
    (time_sec, midi_note) リストをビートアライン TAB テキストに変換する。

    各列 = 1 分割音価（デフォルト 16th note）
    ビート区切りは '|'、小節区切りは '||' で表示。
    chords が指定された場合、各行の上に小節コード行を挿入する。
    """
    tuning = _TUNINGS[instrument]
    names  = _STRING_NAMES[instrument]

    subdiv_sec     = 60.0 / bpm / _SUBDIVISIONS
    cols_per_line  = _MEASURES_PER_LINE * _COLS_PER_MEASURE

    # 列インデックス → (弦インデックス, フレット番号)
    col_map: Dict[int, Tuple[int, int]] = {}
    placed = 0
    for t_sec, midi in timed_notes:
        col = int(round(t_sec / subdiv_sec))
        if col in col_map:
            continue   # 同一グリッド位置は先着優先
        for s, open_note in enumerate(tuning):
            fret = midi - open_note
            if 0 <= fret <= 24:
                col_map[col] = (s, fret)
                placed += 1
                break

    if not col_map:
        return "弾ける音域の音符が検出されませんでした。"

    max_col = max(col_map)

    header = (
        f"{'─' * 50}\n"
        f" {instrument.capitalize()} TAB"
        f"  |  BPM: {bpm:.1f}"
        + (f"  |  Key: {key}" if key else "")
        + f"  |  Placed notes: {placed}\n"
        f"{'─' * 50}\n"
    )
    output = [header]

    for line_start in range(0, max_col + 1, cols_per_line):
        line_end = line_start + cols_per_line

        # コード行: 小節ごとにコード名を表示（chords が指定された場合）
        # 各小節の表示幅 = 16列×2文字 + 3ビート区切り = 35文字
        _MEASURE_DISP_WIDTH = _COLS_PER_MEASURE * 2 + (_COLS_PER_MEASURE // _SUBDIVISIONS - 1)
        if chords is not None:
            chord_parts = []
            for m in range(_MEASURES_PER_LINE):
                midx = line_start // _COLS_PER_MEASURE + m
                chord = chords[midx] if midx < len(chords) else ""
                chord_parts.append(f"{chord:<{_MEASURE_DISP_WIDTH}}")
            chord_row = "   |" + "||".join(chord_parts) + "|"  # prefix 4文字で弦行と列整列
            output.append(chord_row)

        for si, name in enumerate(names):
            row = f" {name} |"
            for col in range(line_start, line_end):
                # 小節区切り: '||' で視認性向上
                if col != line_start and (col - line_start) % _COLS_PER_MEASURE == 0:
                    row += "||"
                # ビート区切り: '|'
                elif col != line_start and (col - line_start) % _SUBDIVISIONS == 0:
                    row += "|"

                if col in col_map and col_map[col][0] == si:
                    fret = col_map[col][1]
                    # 2文字固定幅: "-5" (1桁) / "10" (2桁) — 標準ASCII TAB記法
                    row += f"-{fret}" if fret < 10 else f"{fret}"
                else:
                    row += "--"
            row += "|"
            output.append(row)

        output.append("")   # 行間スペース

    return "\n".join(output)
