"""
core/midi_exporter.py
─────────────────────────────────────────────────────────────────────────────
解析結果を Standard MIDI File (.mid) としてエクスポートする。

TuxGuitar / DAW 等で読み込み・再生可能。
  - ドラムトラック: MIDI ch.10 (General MIDI Percussion)
  - ベーストラック: MIDI ch.2  / program 33 (Electric Bass finger)
  - ギタートラック: MIDI ch.3  / program 26 (Acoustic Guitar steel)

依存: MIDIUtil >= 1.2 (requirements.txt に記載済み)
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import List, Optional, Tuple

from midiutil import MIDIFile

from core.drum_analyzer import DrumAnalysisResult
from core.pitch_analyzer import TabResult

# ── MIDI 定数 ─────────────────────────────────────────────────────────────────

# General MIDI Percussion (ch.10 = channel index 9) のノート番号
_DRUM_MIDI = {
    "Kick":   36,   # Bass Drum 1
    "Snare":  38,   # Acoustic Snare
    "Hi-Hat": 42,   # Closed Hi-Hat
}

# General MIDI プログラム番号 (0-indexed)
_PROGRAM_BASS   = 33   # Electric Bass (finger)
_PROGRAM_GUITAR = 25   # Acoustic Guitar (steel)

# 16 分音符の長さ (拍数 = 0.25 beat)
_SIXTEENTH_BEAT = 0.25


# ── データクラス ───────────────────────────────────────────────────────────────
@dataclass
class MidiExportResult:
    saved_path: str
    n_tracks:   int


# ── 公開 API ───────────────────────────────────────────────────────────────────
def export_midi(
    save_path:     str,
    bpm:           float,
    drum_result:   Optional[DrumAnalysisResult] = None,
    bass_result:   Optional[TabResult]          = None,
    guitar_result: Optional[TabResult]          = None,
) -> MidiExportResult:
    """
    解析結果を Standard MIDI File (.mid) としてエクスポートする。

    引数:
        save_path:     保存先パス (.mid)
        bpm:           テンポ (BPM)
        drum_result:   DrumAnalysisResult (省略可)
        bass_result:   TabResult for bass (省略可)
        guitar_result: TabResult for guitar (省略可)

    戻り値:
        MidiExportResult
    """
    # 有効なトラックのみ収集
    tracks: List[tuple] = []
    if drum_result   is not None: tracks.append(("drum",   drum_result))
    if bass_result   is not None: tracks.append(("bass",   bass_result))
    if guitar_result is not None: tracks.append(("guitar", guitar_result))

    if not tracks:
        raise ValueError("エクスポートする解析結果がありません。先に解析を実行してください。")

    n = len(tracks)
    midi = MIDIFile(numTracks=n, ticks_per_quarternote=480, eventtime_is_ticks=False)

    for i, (kind, result) in enumerate(tracks):
        # テンポ・拍子を各トラックに記録
        midi.addTempo(i, 0, bpm)
        midi.addTimeSignature(
            i, time=0, numerator=4, denominator=4,
            clocks_per_tick=24, notes_per_quarter=8,
        )

        if kind == "drum":
            _write_drum_track(midi, i, result, bpm)
        else:
            channel = 2 if kind == "bass" else 3
            program = _PROGRAM_BASS if kind == "bass" else _PROGRAM_GUITAR
            name    = "Bass"        if kind == "bass" else "Guitar"
            midi.addTrackName(i, 0, name)
            midi.addProgramChange(i, channel, 0, program)
            _write_note_track(midi, i, channel, result, bpm)

    with open(save_path, "wb") as f:
        midi.writeFile(f)

    return MidiExportResult(saved_path=save_path, n_tracks=n)


# ── 内部ヘルパー ───────────────────────────────────────────────────────────────
def _sec_to_beats(sec: float, bpm: float) -> float:
    """秒数を拍数（quarter note 基準）に変換する。"""
    return sec * bpm / 60.0


def _write_drum_track(
    midi:   MIDIFile,
    track:  int,
    result: DrumAnalysisResult,
    bpm:    float,
) -> None:
    """ドラムヒットを MIDI ch.10 (index 9) に書き込む。"""
    midi.addTrackName(track, 0, "Drums")
    for hit in result.hits:
        midi_note  = _DRUM_MIDI.get(hit.label, 38)
        time_beats = _sec_to_beats(hit.time, bpm)
        midi.addNote(
            track, channel=9, pitch=midi_note,
            time=time_beats, duration=_SIXTEENTH_BEAT, volume=100,
        )


def _write_note_track(
    midi:    MIDIFile,
    track:   int,
    channel: int,
    result:  TabResult,
    bpm:     float,
) -> None:
    """ピッチノートを指定チャンネルに書き込む。

    ノート長は次の音符との間隔から算出（最小=16th、最大=4th）。
    これにより音楽的に自然なデュレーションになる。
    """
    notes = result.timed_notes
    if not notes:
        return

    for i, (t_sec, midi_note) in enumerate(notes):
        time_beats = _sec_to_beats(t_sec, bpm)

        # 次の音符との間隔でデュレーションを決定
        if i + 1 < len(notes):
            gap = _sec_to_beats(notes[i + 1][0] - t_sec, bpm)
            dur = max(_SIXTEENTH_BEAT, min(gap, 1.0))  # [0.25, 1.0] beats
        else:
            dur = _SIXTEENTH_BEAT

        midi.addNote(
            track, channel=channel, pitch=midi_note,
            time=time_beats, duration=dur, volume=100,
        )
