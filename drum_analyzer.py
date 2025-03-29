import os
import sys
import numpy as np
import librosa
import librosa.display
import matplotlib.pyplot as plt
import scipy.signal as signal
from attack_time_analysis import analyze_attack_time  # ✅ attack_time_analysisをインポート
import matplotlib.font_manager as fm
import matplotlib

# ✅ Unicodeフォントエラー対策
matplotlib.rcParams['axes.unicode_minus'] = False

# ✅ 日本語フォント設定
plt.rcParams['font.family'] = 'AppleGothic'  # MacならこれでOK

# 📂 ダウンロードディレクトリのパス
downloads_dir = "/Users/fujimakikenji/DrumTabApp/downloads"

# 📂 最新の音源ファイルを取得する関数
def get_latest_audio_file(directory):
    files = [f for f in os.listdir(directory) if f.endswith(('.mp3', '.wav'))]
    if not files:
        print("❌ 音源ファイルが見つかりません。")
        exit()
    latest_file = max(files, key=lambda x: os.path.getmtime(os.path.join(directory, x)))
    return latest_file

# ✅ analyze_drum 関数の追加
def analyze_drum(audio_path):
    # 📥 音源の読み込み (モノラル & float32でメモリ節約)
    y, sr = librosa.load(audio_path, sr=22050, mono=True, dtype=np.float32)

    # 🔍 アタックタイムの解析 (ピーク検出)
    peaks, _ = signal.find_peaks(y, height=0.05, distance=sr // 10)
    attack_times = np.diff(peaks) / sr

    # 🥁 ドラム譜の生成 (仮)
    drum_tab = ""
    for i, peak in enumerate(peaks[:50]):  # 最初の50個だけ表示
        drum_tab += f"音符 {i+1}: 時間 {peak / sr:.2f} 秒\n"

    # 🔍 特徴量の計算
    zero_crossings = librosa.feature.zero_crossing_rate(y)
    spectral_centroid = librosa.feature.spectral_centroid(y=y, sr=sr)

    # 🖊 結果表示 (GUI用に返す)
    result = (
        f"📊 ドラム解析結果:\n"
        f"サンプリングレート: {sr} Hz\n"
        f"平均ゼロ交差率: {np.mean(zero_crossings):.4f}\n"
        f"平均スペクトルセントロイド: {np.mean(spectral_centroid):.2f} Hz\n"
        f"ピーク数: {len(peaks)}\n"
        f"平均アタックタイム: {np.mean(attack_times):.4f} 秒\n\n"
        f"{drum_tab}"
    )

    # 📊 attack_time_analysis を使った解析
    # 🚫 plt.show() を使わないように変更 (保存のみにする)
    analyze_attack_time(audio_path)
    plt.close()  # ✅ plt.show() を使わない代わりに plt.close() でメモリ開放

    # 🥁 ドラム譜を返す (GUIで使う用)
    return result if drum_tab else "🥁 ドラム譜が生成されませんでした"

# ✅ メイン処理: コマンドラインから直接実行された場合
if __name__ == "__main__":
    # 🔄 コマンドライン引数からファイルを取得 (指定がなければ最新ファイル)
    audio_file = sys.argv[1] if len(sys.argv) > 1 else get_latest_audio_file(downloads_dir)
    audio_path = os.path.join(downloads_dir, audio_file)

    # 🔍 ファイルが存在するかチェック
    if not os.path.exists(audio_path):
        print(f"❌ ファイルが見つかりません: {audio_path}")
        exit()

    print(analyze_drum(audio_path))
