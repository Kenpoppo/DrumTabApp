"""
core/gp5_exporter.py
─────────────────────────────────────────────────────────────────────────────
解析結果を Guitar Pro 5 (.gp5) 形式でエクスポートする。

TuxGuitar / Guitar Pro / OpenSong など GP5 対応ソフトで
弦番号・フレット番号・ドラム譜として完全に表示・再生可能。

設計方針:
  - PyGuitarPro (guitarpro) ライブラリを使用
  - Guitar / Bass: timed_notes → BPM グリッドに量子化してフレット/弦に変換
  - Drum: DrumHit → General MIDI Percussion ノート番号にマッピング
  - 拍子: 4/4 固定, 音価: 16 分音符単位でグリッド量子化
  - 複数小節を自動生成（解析結果の全長をカバー）
  - BeatStatus.normal / NoteType.normal を明示 (デフォルトが empty/rest のため)

依存: PyGuitarPro >= 0.10 (requirements.txt に追加済み)
"""
from __future__ import annotations

import copy
import math
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import guitarpro
from guitarpro import models as gpm

from core.drum_analyzer import DrumAnalysisResult
from core.pitch_analyzer import TabResult, _TUNINGS

# ── 定数 ─────────────────────────────────────────────────────────────────────

# GP の内部 tick 単位
_QT = gpm.Duration.quarterTime      # = 960 ticks per quarter note

# 楽器別 GM Program 番号 (0-indexed)
_PROGRAM = {
    "guitar": 25,   # Acoustic Guitar (steel)
    "bass":   33,   # Electric Bass (finger)
}

# ドラム: MIDI Percussion ノート番号
_DRUM_MIDI: Dict[str, int] = {
    "Kick":   36,   # Bass Drum 1
    "Snare":  38,   # Acoustic Snare
    "Hi-Hat": 42,   # Closed Hi-Hat
}

# ドラム種別 → GP string 番号 (1-indexed, 別々にすることでwriteNotesの競合を回避)
_DRUM_STRING: Dict[str, int] = {
    "Kick":   1,    # string 1 → Bass Drum
    "Snare":  2,    # string 2 → Snare
    "Hi-Hat": 3,    # string 3 → Hi-Hat
    "Unknown": 2,   # Unknown → Snare 扱い
}

# 各 string に対応する開放弦 MIDI 値 (TuxGuitar が参照する)
_DRUM_STRINGS = [
    gpm.GuitarString(1, 36),   # string 1 = Bass Drum (36)
    gpm.GuitarString(2, 38),   # string 2 = Snare (38)
    gpm.GuitarString(3, 42),   # string 3 = Hi-Hat Closed (42)
]

# ギター弦チューニング (高弦→低弦, MIDI note)
_GP_TUNINGS: Dict[str, List[int]] = {
    "guitar": [64, 59, 55, 50, 45, 40],   # e4 B3 G3 D3 A2 E2
    "bass":   [43, 38, 33, 28],            # G2 D2 A1 E1
}

# 16 分音符 = 240 ticks
_SIXTEENTH_TICKS = _QT // 4

# ── データクラス ──────────────────────────────────────────────────────────────

@dataclass
class Gp5ExportResult:
    saved_path: str
    n_tracks: int
    n_measures: int


# ── 公開 API ──────────────────────────────────────────────────────────────────

def export_gp5(
    save_path:     str,
    bpm:           float,
    drum_result:   Optional[DrumAnalysisResult] = None,
    bass_result:   Optional[TabResult]          = None,
    guitar_result: Optional[TabResult]          = None,
    title:         str = "DrumTabApp",
    artist:        str = "",
) -> Gp5ExportResult:
    """
    解析結果を .gp5 ファイルとして保存する。

    GP5 の read/write オーダーバグ (gp5.writeBeat vs gp5.readBeat) を回避するため
    GP4 互換フォーマット (.gp5 拡張子) で保存する。
    TuxGuitar はどちらのバイナリ順序でも読み込み可能。

    引数:
        save_path:     保存先パス (.gp5 拡張子を推奨)
        bpm:           テンポ
        drum_result:   DrumAnalysisResult (省略可)
        bass_result:   TabResult for bass (省略可)
        guitar_result: TabResult for guitar (省略可)
        title:         曲タイトル
        artist:        アーティスト名

    戻り値:
        Gp5ExportResult
    """
    if not any([drum_result, bass_result, guitar_result]):
        raise ValueError("エクスポートする解析結果がありません。先に解析を実行してください。")

    # BPM から曲の総長を算出 (最長トラックに合わせる)
    total_sec = _calc_total_seconds(bpm, drum_result, bass_result, guitar_result)
    beats_per_bar = 4
    beat_sec = 60.0 / bpm
    n_measures = max(1, math.ceil(total_sec / (beat_sec * beats_per_bar)))

    # ── Song オブジェクト構築 ────────────────────────────────────────────────
    song = gpm.Song()
    song.tempo = int(round(bpm))
    # GP5 は cp1252 エンコーディング → ASCII のみ使用
    song.title  = title.encode("ascii", errors="replace").decode("ascii")
    song.artist = artist.encode("ascii", errors="replace").decode("ascii")

    # MeasureHeader を必要数生成
    _build_measure_headers(song, n_measures)

    # ── デフォルトトラック (track 1 は Song に含まれる) を作業に使う ──────────
    # 最初の有効トラックとして上書き。不要なら後で差し替え。
    track_number = 1

    # Guitar / Bass / Drum の順でトラック追加
    built_tracks: List[gpm.Track] = []

    if guitar_result is not None:
        t = _build_pitch_track(song, track_number, "guitar", guitar_result, bpm)
        built_tracks.append(t)
        track_number += 1

    if bass_result is not None:
        t = _build_pitch_track(song, track_number, "bass", bass_result, bpm)
        built_tracks.append(t)
        track_number += 1

    if drum_result is not None:
        t = _build_drum_track(song, track_number, drum_result, bpm)
        built_tracks.append(t)
        track_number += 1

    # デフォルトトラックを最初のビルト済みトラックで置き換え
    song.tracks[0] = built_tracks[0]
    for t in built_tracks[1:]:
        song.tracks.append(t)

    # ── ファイルに書き込み ────────────────────────────────────────────────────
    guitarpro.write(song, save_path)

    return Gp5ExportResult(
        saved_path=save_path,
        n_tracks=len(built_tracks),
        n_measures=n_measures,
    )


# ── 内部ヘルパー ──────────────────────────────────────────────────────────────

def _calc_total_seconds(
    bpm:           float,
    drum_result:   Optional[DrumAnalysisResult],
    bass_result:   Optional[TabResult],
    guitar_result: Optional[TabResult],
) -> float:
    """有効なトラックのうち最も長い演奏時間 (秒) を返す。"""
    times: List[float] = []

    if drum_result is not None and drum_result.hits:
        times.append(max(h.time for h in drum_result.hits))

    for result in [bass_result, guitar_result]:
        if result is not None and result.timed_notes:
            times.append(max(t for t, _ in result.timed_notes))

    return max(times) if times else 4 * 60.0 / bpm  # 最低 1 小節


def _build_measure_headers(song: gpm.Song, n_measures: int) -> None:
    """song.measureHeaders を n_measures 分に拡張する。"""
    # デフォルトで measureHeaders に 1 つ存在する
    mh0 = song.measureHeaders[0]
    bar_ticks = mh0.length  # 4/4 = 4 * 960 = 3840

    for i in range(1, n_measures):
        mh = gpm.MeasureHeader(
            number=i + 1,
            start=mh0.start + bar_ticks * i,
        )
        song.measureHeaders.append(mh)


def _new_track(
    song:     gpm.Song,
    number:   int,
    name:     str,
    channel:  int,
    program:  int,
    strings:  List[gpm.GuitarString],
    is_perc:  bool = False,
) -> gpm.Track:
    """テンプレートトラックを deepcopy して設定を上書きする。"""
    t = copy.deepcopy(song.tracks[0])
    t.number = number
    t.name   = name
    t.isPercussionTrack = is_perc
    t.strings = strings

    # Channel 設定
    t.channel = copy.deepcopy(song.tracks[0].channel)
    t.channel.channel       = channel
    t.channel.effectChannel = channel + 1 if channel < 15 else channel
    t.channel.instrument    = program

    # Measure を song の MeasureHeader 分だけ確保
    t.measures = [gpm.Measure(t, mh) for mh in song.measureHeaders]

    return t


def _build_pitch_track(
    song:       gpm.Song,
    number:     int,
    instrument: str,
    result:     TabResult,
    bpm:        float,
) -> gpm.Track:
    """ギター / ベースの TAB トラックを生成する。"""
    tuning  = _GP_TUNINGS[instrument]
    channel = 0 if instrument == "guitar" else 1

    gp_strings = [gpm.GuitarString(i + 1, v) for i, v in enumerate(tuning)]
    t = _new_track(song, number, instrument.capitalize(), channel,
                   _PROGRAM[instrument], gp_strings)

    # BPM グリッドに量子化してノートを配置
    beat_sec = 60.0 / bpm
    subdiv_sec = beat_sec / 4  # 16 分音符

    for mh, measure in zip(song.measureHeaders, t.measures):
        _fill_pitch_measure(measure, mh, result.timed_notes, tuning, subdiv_sec)

    return t


def _fill_pitch_measure(
    measure:     gpm.Measure,
    mh:          gpm.MeasureHeader,
    timed_notes: List[Tuple[float, int]],
    tuning:      List[int],
    subdiv_sec:  float,
) -> None:
    """
    1 小節分の timed_notes を Voice に Beat として書き込む。
    空の列は16分音符の rest として記録する。
    """
    bar_ticks   = mh.length         # 3840
    beats_n     = 4                  # 4/4
    total_cols  = beats_n * 4        # 16 (16 分音符単位)
    col_ticks   = bar_ticks // total_cols   # 240

    # 小節の時間範囲 (秒) を算出
    # measureHeader.start は tick → 秒に変換
    # ここでは subdiv_sec ベースで列インデックスを使う
    # measure 番号 (0-indexed) を mh.number - 1 とする
    measure_idx = mh.number - 1
    bar_sec     = subdiv_sec * total_cols  # 1小節の長さ (秒)
    bar_start_sec = measure_idx * bar_sec
    bar_end_sec   = bar_start_sec + bar_sec

    # この小節に入る notes を抽出してグリッドにマッピング
    # col_index → (string, fret)
    col_map: Dict[int, Tuple[int, int]] = {}
    for t_sec, midi in timed_notes:
        if not (bar_start_sec <= t_sec < bar_end_sec):
            continue
        col = int(round((t_sec - bar_start_sec) / subdiv_sec))
        col = min(col, total_cols - 1)
        if col in col_map:
            continue  # 先着優先
        for s_idx, open_note in enumerate(tuning):
            fret = midi - open_note
            if 0 <= fret <= 24:
                col_map[col] = (s_idx + 1, fret)  # string: 1-indexed
                break

    voice = measure.voices[0]
    start_tick = mh.start

    for col in range(total_cols):
        d = gpm.Duration(value=16)  # 16 分音符
        tick = start_tick + col * col_ticks
        b = gpm.Beat(voice, start=tick, duration=d, status=gpm.BeatStatus.normal)

        if col in col_map:
            string_num, fret = col_map[col]
            n = gpm.Note(beat=b, value=fret, velocity=95,
                         string=string_num, type=gpm.NoteType.normal)
            b.notes.append(n)
        else:
            # 無音列: rest beat
            b.status = gpm.BeatStatus.rest

        voice.beats.append(b)


def _build_drum_track(
    song:   gpm.Song,
    number: int,
    result: DrumAnalysisResult,
    bpm:    float,
) -> gpm.Track:
    """
    ドラムトラックを生成する。

    各ドラム種別 (Kick/Snare/Hi-Hat) に異なる string 番号を割り当てることで
    writeNotes の stringFlags 競合 (同一 string 番号の複数 Note が書き出し時に
    1 フラグに潰れてバイト列がずれる問題) を回避する。
    """
    # ドラムは通常 MIDI ch.10 (0-indexed = 9)
    t = _new_track(
        song, number, "Drums", channel=9, program=0,
        strings=_DRUM_STRINGS,
        is_perc=True,
    )

    beat_sec    = 60.0 / bpm
    subdiv_sec  = beat_sec / 4
    bar_ticks   = song.measureHeaders[0].length
    total_cols  = 16  # 16 分音符単位
    col_ticks   = bar_ticks // total_cols

    for mh, measure in zip(song.measureHeaders, t.measures):
        measure_idx   = mh.number - 1
        bar_sec       = subdiv_sec * total_cols
        bar_start_sec = measure_idx * bar_sec
        bar_end_sec   = bar_start_sec + bar_sec

        # この小節内のヒットを列インデックスにマッピング
        # 同列に複数ヒット (kick+hh 同時打ち) → 各ヒットを異なる string 番号で保持
        col_hits: Dict[int, List[Tuple[int, int]]] = {}  # col → [(string, midi_note)]
        for hit in result.hits:
            if not (bar_start_sec <= hit.time < bar_end_sec):
                continue
            col        = int(round((hit.time - bar_start_sec) / subdiv_sec))
            col        = min(col, total_cols - 1)
            string_num = _DRUM_STRING.get(hit.label, 2)
            midi       = _DRUM_MIDI.get(hit.label, 38)
            # 同一列・同一 string は先着優先 (重複ヒット防止)
            key_set    = {s for s, _ in col_hits.get(col, [])}
            if string_num not in key_set:
                col_hits.setdefault(col, []).append((string_num, midi))

        voice      = measure.voices[0]
        start_tick = mh.start

        for col in range(total_cols):
            d    = gpm.Duration(value=16)
            tick = start_tick + col * col_ticks
            b    = gpm.Beat(voice, start=tick, duration=d, status=gpm.BeatStatus.normal)

            if col in col_hits:
                for (string_num, midi_note) in col_hits[col]:
                    # string: ドラム種別ごとに異なる番号 (1=Kick, 2=Snare, 3=HH)
                    # value:  GM Percussion MIDI ノート番号
                    n = gpm.Note(beat=b, value=midi_note, velocity=95,
                                 string=string_num, type=gpm.NoteType.normal)
                    b.notes.append(n)
            else:
                b.status = gpm.BeatStatus.rest

            voice.beats.append(b)

    return t
