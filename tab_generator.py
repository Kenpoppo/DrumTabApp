import librosa

# 音源からピッチ（音階）を検出してMIDIノートに変換
def detect_pitches(audio_file):
    y, sr = librosa.load(audio_file, sr=None)
    pitches, magnitudes = librosa.piptrack(y=y, sr=sr)
    notes = []

    for t in range(pitches.shape[1]):
        index = pitches[:, t].argmax()
        pitch = pitches[index, t]
        if pitch > 0:
            midi_note = librosa.hz_to_midi(pitch)
            notes.append(int(midi_note))

    print(f"検出された音階 (MIDIノート): {notes}")
    return notes

# MIDIノートからギターやベースのTABを生成
def generate_tab(notes, instrument='guitar'):
    string_tunings = {
        'guitar': [64, 59, 55, 50, 45, 40],   # EADGBE
        'bass': [40, 45, 50, 55]               # EADG
    }
    tuning = string_tunings[instrument]
    tab = [[] for _ in tuning]

    for note in notes:
        for string, open_note in enumerate(tuning):
            fret = note - open_note
            if 0 <= fret <= 24:
                tab[string].append(fret)
                break
        else:
            for string in tab:
                string.append("-")

    # TAB譜の表示
    print(f"\n--- {instrument.capitalize()} TAB ---")
    for i, string in enumerate(tab[::-1]):
        print(f"弦{i+1}: " + "".join(f"{fret if fret != '-' else '-'}-" for fret in string))
    return tab

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
