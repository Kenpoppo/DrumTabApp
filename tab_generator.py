import numpy as np
import librosa

# マグニチュード閾値: これ未満のフレームはノイズとして無視
_MAG_THRESHOLD = 10.0


def detect_pitches(audio_file):
    """
    音源からピッチを検出してMIDIノート番号リストを返す。
    piptrack の各フレームで最大マグニチュードのビンだけを採用し、
    閾値以下のフレームは捨てることでノイズ誤検出を抑制する。
    """
    y, sr = librosa.load(audio_file, sr=None)
    pitches, magnitudes = librosa.piptrack(y=y, sr=sr)

    notes = []
    for t in range(pitches.shape[1]):
        # マグニチュードが最大のビンを選ぶ
        mag_idx = magnitudes[:, t].argmax()
        mag     = magnitudes[mag_idx, t]
        pitch   = pitches[mag_idx, t]

        # 閾値未満 or ピッチ 0 のフレームは無視
        if mag < _MAG_THRESHOLD or pitch <= 0:
            continue

        midi_note = librosa.hz_to_midi(pitch)
        notes.append(int(round(midi_note)))

    print(f"検出された音階 (MIDIノート): {notes}")
    return notes


def generate_tab(notes, instrument='guitar'):
    """
    MIDIノートリストからTAB譜文字列を生成して返す。
    """
    string_tunings = {
        'guitar': [64, 59, 55, 50, 45, 40],   # e B G D A E (高→低)
        'bass':   [55, 50, 45, 40],            # G D A E
    }
    if instrument not in string_tunings:
        raise ValueError(f"未対応の楽器: {instrument}")

    tuning = string_tunings[instrument]
    tab    = [[] for _ in tuning]

    for note in notes:
        placed = False
        for string_idx, open_note in enumerate(tuning):
            fret = note - open_note
            if 0 <= fret <= 24:
                tab[string_idx].append(str(fret))
                placed = True
                break
        if not placed:
            for string in tab:
                string.append("-")

    # 文字列として組み立てる
    lines = []
    for i, string in enumerate(tab):
        frets_str = "-".join(f"{f:>2}" if f != "-" else " -" for f in string)
        lines.append(f"弦{i+1}: {frets_str}")

    tab_str = f"\n--- {instrument.capitalize()} TAB ---\n" + "\n".join(lines)
    print(tab_str)
    return tab_str


# テスト実行用
if __name__ == "__main__":
    # ギター用
    guitar_file = "separated/金木犀 feat.Ado (Official Video)/other.wav"
    print("\n🌟 ギターの解析開始！")
    guitar_notes = detect_pitches(guitar_file)
    generate_tab(guitar_notes, instrument='guitar')

    # ベース用
    bass_file = "separated/金木犀 feat.Ado (Official Video)/bass.wav"
    print("\n🌟 ベースの解析開始！")
    bass_notes = detect_pitches(bass_file)
    generate_tab(bass_notes, instrument='bass')

