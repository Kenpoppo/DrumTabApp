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

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple
import os

import numpy as np
import librosa

# ── 定数 ──────────────────────────────────────────────────────────────────────
_MAG_THRESHOLD = 8.0    # piptrack マグニチュード閾値のフォールバック値
_SUBDIVISIONS  = 4      # 1 拍あたりの分割数（16th note）
_MEASURES_PER_LINE = 2  # TAB 1 行あたりの小節数
_COLS_PER_MEASURE  = 4 * _SUBDIVISIONS   # 小節あたりの列数 (4/4 拍子)

# 弦チューニング: 各弦の開放弦 MIDI ノート番号（高弦→低弦順）
_TUNINGS: Dict[str, List[int]] = {
    "guitar": [64, 59, 55, 50, 45, 40],   # e4 B3 G3 D3 A2 E2
    "bass":   [43, 38, 33, 28],           # G2 D2 A1 E1 (標準ベースチューニング)
}
_STRING_NAMES: Dict[str, List[str]] = {
    "guitar": ["e", "B", "G", "D", "A", "E"],
    "bass":   ["G", "D", "A", "E"],
}

# 楽器別 MIDI 音域
# ベース: G3(55)以上はほぼ倍音誤検出のため 28-55 に絞る
_MIDI_RANGE: Dict[str, Tuple[int, int]] = {
    "guitar": (40, 88),   # E2 〜 E6
    "bass":   (28, 55),   # E1 〜 G3 (実用ベース音域)
}

# 楽器別 piptrack fmin
_FMIN: Dict[str, float] = {
    "guitar": librosa.note_to_hz("D2"),
    "bass":   librosa.note_to_hz("C1"),
}

# BPM 候補探索範囲: 複数の start_bpm で推定し最も確信度が高いものを選ぶ
_BPM_CANDIDATES = [60, 75, 90, 100, 120, 140]
# 許容 BPM 範囲（ほとんどのポップス曲は 60-200 BPM）
_BPM_MIN, _BPM_MAX = 60.0, 200.0


# ── データモデル ───────────────────────────────────────────────────────────────
@dataclass
class TabResult:
    """analyze() の戻り値。"""
    instrument:  str
    tab_text:    str
    note_count:  int
    bpm:         float
    timed_notes: List[Tuple[float, int]] = field(default_factory=list)
    """(time_sec, midi_note) のリスト。MIDI エクスポート等で利用。"""


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

    # BPM 推定: 複数の start_bpm で候補を出し onset 相関が最大のものを採用
    bpm = _estimate_bpm(y, sr, audio_path=audio_path)

    # ピッチ検出（倍音成分で実施）
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

    # モノフォニック化: ベースは単音楽器なので近接ノートを間引く
    if instrument == "bass":
        timed_notes = _mono_filter(timed_notes, window_sec=0.08)

    tab_text = _render_tab(timed_notes, instrument, bpm, chords=chords, key=key)
    return TabResult(
        instrument=instrument,
        tab_text=tab_text,
        note_count=len(timed_notes),
        bpm=bpm,
        timed_notes=timed_notes,
    )


# ── 内部ヘルパー ───────────────────────────────────────────────────────────────

def _estimate_bpm(y: np.ndarray, sr: int, audio_path: str = "") -> float:
    """
    BPM を推定する。

    優先順位:
      1. 同ディレクトリに drums.wav があればそれで推定（最も安定）
      2. 渡された y（ベース/ギターステム）で推定
         複数の start_bpm で beat_track を実行し、平均ビート強度が最高の BPM を選択。
    """
    # ── drums.wav 優先パス ─────────────────────────────────────────────────
    if audio_path:
        drums_path = os.path.join(os.path.dirname(audio_path), "drums.wav")
        if os.path.isfile(drums_path) and drums_path != audio_path:
            try:
                y_d, sr_d = librosa.load(drums_path, sr=None, mono=True, dtype=np.float32)
                t, _ = librosa.beat.beat_track(y=y_d, sr=sr_d, start_bpm=120.0)
                bpm_d = float(np.atleast_1d(t)[0])
                if _BPM_MIN <= bpm_d <= _BPM_MAX:
                    return bpm_d
            except Exception:
                pass  # フォールバックへ

    # ── ステム単体での推定（フォールバック） ──────────────────────────────
    onset_env = librosa.onset.onset_strength(y=y, sr=sr)
    candidates: List[Tuple[float, float]] = []  # (bpm, score)
    for start in _BPM_CANDIDATES:
        t, beats = librosa.beat.beat_track(
            y=y, sr=sr, start_bpm=float(start)
        )
        bpm_cand = float(np.atleast_1d(t)[0])
        if not (_BPM_MIN <= bpm_cand <= _BPM_MAX) or len(beats) == 0:
            continue
        # 平均ビート強度 (onset合計 / ビート数) → ビート数に依らず比較可能
        score = float(onset_env[beats].mean())
        candidates.append((bpm_cand, score))

    if not candidates:
        return 120.0

    best_bpm = max(candidates, key=lambda x: x[1])[0]
    return best_bpm if _BPM_MIN <= best_bpm <= _BPM_MAX else 120.0


def _mono_filter(
    notes: List[Tuple[float, int]],
    window_sec: float = 0.08,
) -> List[Tuple[float, int]]:
    """
    モノフォニック化フィルター。
    window_sec 以内に複数ノートがある場合:
      1. オクターブ重複 → より低い音（基音）を残す
      2. 同時多声音 → 最も低い音を残す（ベースは最低音が基音）
    """
    if not notes:
        return notes

    # 時刻でグループ化
    groups: List[List[Tuple[float, int]]] = []
    current: List[Tuple[float, int]] = [notes[0]]
    for t, m in notes[1:]:
        if abs(t - current[0][0]) <= window_sec:
            current.append((t, m))
        else:
            groups.append(current)
            current = [(t, m)]
    groups.append(current)

    result: List[Tuple[float, int]] = []
    for grp in groups:
        midis = [m for _, m in grp]
        times = [t for t, _ in grp]
        # オクターブ関係を除去: 低い音を優先
        keep_midis: List[int] = []
        for m in sorted(set(midis)):
            if not any(abs(m - k) == 12 or abs(m - k) == 24 for k in keep_midis):
                keep_midis.append(m)
        # 最低音のみ残す
        chosen = min(keep_midis)
        avg_t  = float(np.mean([t for t, m in grp if m == chosen or
                                 any(abs(m - k) == 12 or abs(m - k) == 24
                                     for k in [chosen])]))
        result.append((times[0], chosen))

    return result


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
    prev_string: Optional[int] = None   # ポジション連続性のため直前の弦を記憶
    prev_fret:   Optional[int] = None
    for t_sec, midi in timed_notes:
        col = int(round(t_sec / subdiv_sec))
        if col in col_map:
            continue   # 同一グリッド位置は先着優先
        best = _choose_string(midi, tuning, prev_string, prev_fret, instrument=instrument)
        if best is not None:
            s, fret = best
            col_map[col] = (s, fret)
            placed += 1
            prev_string, prev_fret = s, fret

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

        # 小節番号行: 行の先頭に何小節目かを表示
        mnum_parts = []
        for m in range(_MEASURES_PER_LINE):
            midx = line_start // _COLS_PER_MEASURE + m
            mnum = f"m.{midx + 1}"
            mnum_parts.append(f"{mnum:<{_MEASURE_DISP_WIDTH}}")
        mnum_row = "   |" + "||".join(mnum_parts) + "|"
        output.append(mnum_row)

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


def _choose_string(
    midi: int,
    tuning: List[int],
    prev_string: Optional[int],
    prev_fret:   Optional[int],
    instrument:  str = "guitar",
) -> Optional[Tuple[int, int]]:
    """
    MIDI ノートを弦・フレットに割り当てる。

    優先順位:
      1. フレット範囲 0-24 に収まる弦のみ候補とする
      2. 前のノートと同じ弦で隣接フレット（差 ≤ 5）ならポジション加点 (−10)
      3. ベースの場合: 低弦(E/A)優先バイアス + 中間フレット(3-9)優先
      4. 残りはフレット番号最小の弦を選択
    """
    n_strings = len(tuning)
    candidates: List[Tuple[float, int, int]] = []  # (score, fret, string_idx)
    for s, open_note in enumerate(tuning):
        fret = midi - open_note
        if not (0 <= fret <= 24):
            continue
        score: float = float(fret)

        # ── ポジション連続性ボーナス ─────────────────────
        if prev_string is not None and prev_fret is not None:
            if s == prev_string and abs(fret - prev_fret) <= 5:
                score -= 10   # 同弦近傍ポジション = 大きなボーナス

        # ── ベース固有: 低弦(E/A)優先バイアス ────────────
        # tuning は高弦→低弦順 (index 0=G, 1=D, 2=A, 3=E)
        # 低弦ほど index が大きい → index を使って低弦優先バイアスを付ける
        if instrument == "bass":
            # E/A弦(index 2-3)を D/G弦より優先 (ベーシストはE/A弦を好む)
            string_depth = s  # 0=G(最高), n-1=E(最低)
            score -= string_depth * 1.5   # E弦は最大 -4.5 ボーナス

            # 中間フレット(3-9)優先: 開放弦・低フレットは実奏では少ない
            if fret <= 2:
                score += 4.0   # 開放弦〜2フレットのペナルティ

        candidates.append((score, fret, s))
    if not candidates:
        return None
    candidates.sort()
    _, fret, s = candidates[0]
    return s, fret
