import os
from spleeter.separator import Separator

def separate_instruments(audio_file):
    output_dir = "separated"
    os.makedirs(output_dir, exist_ok=True)

    # Spleeterの5stemsモデルで音源を分離
    separator = Separator('spleeter:5stems')
    separator.separate_to_file(audio_file, output_dir)

    # 分離された音源ファイルのパス
    drum_file = os.path.join(output_dir, os.path.basename(audio_file).replace(".wav", "/drums.wav"))
    bass_file = os.path.join(output_dir, os.path.basename(audio_file).replace(".wav", "/bass.wav"))
    guitar_file = os.path.join(output_dir, os.path.basename(audio_file).replace(".wav", "/other.wav"))

    print(f"ドラム音源: {drum_file}")
    print(f"ベース音源: {bass_file}")
    print(f"ギター音源: {guitar_file}")

    return drum_file, bass_file, guitar_file

# テスト実行用
if __name__ == "__main__":
    # さっきダウンロードしたファイルを指定
    audio_file = "downloads/金木犀 feat.Ado (Official Video).wav"
    separate_instruments(audio_file)
