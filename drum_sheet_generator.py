import librosa
import matplotlib.pyplot as plt
import matplotlib.pyplot as plt
from matplotlib import font_manager

# 日本語フォントの設定
font_path = '/System/Library/Fonts/ヒラギノ丸ゴ ProN W4.ttc'  # Mac標準のヒラギノフォント
font_prop = font_manager.FontProperties(fname=font_path)
plt.rcParams['font.family'] = font_prop.get_name()


def generate_drum_sheet(drum_file):
    # 音源の読み込み
    y, sr = librosa.load(drum_file, sr=None)
    
    # ドラムのトランジェント（打撃音）の検出
    onset_frames = librosa.onset.onset_detect(y=y, sr=sr, backtrack=True)
    onset_times = librosa.frames_to_time(onset_frames, sr=sr)

    # 仮のドラムの種類（Kick, Snare, Hi-Hat）を割り当て
    drum_types = ["Kick", "Snare", "Hi-Hat"]
    detected_drums = [drum_types[i % 3] for i in range(len(onset_times))]

    # 譜面の描画
    plt.eventplot(onset_times, orientation='horizontal')
    plt.title("ドラム譜面")
    plt.xlabel("時間 (秒)")
    plt.yticks([1, 2, 3], ["Kick", "Snare", "Hi-Hat"])
    plt.grid(axis='x', linestyle='--')
    plt.show()

    print(f"検出されたドラム音のタイミング: {onset_times}")
    print(f"ドラムの種類: {detected_drums}")

# テスト実行用
if __name__ == "__main__":
    drum_file = "separated/金木犀 feat.Ado (Official Video)/drums.wav"
    generate_drum_sheet(drum_file)
