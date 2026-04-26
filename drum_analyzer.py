import os
import sys
import numpy as np
import librosa
import matplotlib
import matplotlib.pyplot as plt
from attack_time_analysis import analyze_attack_time

matplotlib.rcParams['axes.unicode_minus'] = False

# 📂 ダウンロードディレクトリのパス (実行ファイル基準)
downloads_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "downloads")


# 📂 最新の音源ファイルを取得する関数
def get_latest_audio_file(directory):
    files = [f for f in os.listdir(directory) if f.endswith(('.mp3', '.wav'))]
    if not files:
        print("❌ 音源ファイルが見つかりません。")
        exit()
    latest_file = max(files, key=lambda x: os.path.getmtime(os.path.join(directory, x)))
    return latest_file


def _classify_drum_hit(y, sr, frame_idx, hop_length):
    """
    オンセットフレームの周波数特性でドラム種別を分類する。
    - Kick  : 低域エネルギー (20–200 Hz) が支配的
    - Snare : 中高域エネルギー (200–8000 Hz) が支配的
    - Hi-Hat: 高域エネルギー (8000 Hz+) が支配的
    """
    center = frame_idx * hop_length
    window = y[max(0, center - hop_length): center + hop_length]
    if len(window) == 0:
        return "Unknown"

    fft = np.abs(np.fft.rfft(window, n=2048))
    freqs = np.fft.rfftfreq(2048, d=1.0 / sr)

    def band_energy(lo, hi):
        mask = (freqs >= lo) & (freqs < hi)
        return float(np.sum(fft[mask] ** 2))

    kick_e  = band_energy(20, 200)
    snare_e = band_energy(200, 8000)
    hihat_e = band_energy(8000, sr / 2)

    idx = np.argmax([kick_e, snare_e, hihat_e])
    return ["Kick", "Snare", "Hi-Hat"][idx]


def analyze_drum(audio_path):
    # 📥 音源の読み込み
    y, sr = librosa.load(audio_path, sr=22050, mono=True, dtype=np.float32)

    hop_length = 512

    # 🔍 BPM・ビート検出
    tempo, beat_frames = librosa.beat.beat_track(y=y, sr=sr, hop_length=hop_length)
    beat_times = librosa.frames_to_time(beat_frames, sr=sr, hop_length=hop_length)

    # 🔍 オンセット検出 (生波形ピーク検出より高精度)
    onset_frames = librosa.onset.onset_detect(
        y=y, sr=sr, hop_length=hop_length,
        units='frames', backtrack=True,
        pre_max=3, post_max=3, pre_avg=5, post_avg=5, delta=0.07, wait=10
    )
    onset_times = librosa.frames_to_time(onset_frames, sr=sr, hop_length=hop_length)

    # 🥁 ドラム種別分類 + タブ生成
    labels = [_classify_drum_hit(y, sr, f, hop_length) for f in onset_frames]
    attack_times = np.diff(onset_times)

    drum_tab_lines = []
    for i, (t, label) in enumerate(zip(onset_times[:60], labels[:60])):
        drum_tab_lines.append(f"  [{i+1:3d}] {t:6.2f}s  {label}")
    drum_tab = "\n".join(drum_tab_lines)

    # 🔍 特徴量
    zero_crossings    = librosa.feature.zero_crossing_rate(y)
    spectral_centroid = librosa.feature.spectral_centroid(y=y, sr=sr)

    tempo_val = float(np.atleast_1d(tempo)[0])
    result = (
        f"📊 ドラム解析結果:\n"
        f"サンプリングレート: {sr} Hz\n"
        f"推定BPM: {tempo_val:.1f}\n"
        f"平均ゼロ交差率: {np.mean(zero_crossings):.4f}\n"
        f"平均スペクトルセントロイド: {np.mean(spectral_centroid):.2f} Hz\n"
        f"検出オンセット数: {len(onset_frames)}\n"
        f"平均アタックタイム: {np.mean(attack_times):.4f} 秒\n\n"
        f"--- ドラムヒット一覧 (先頭60件) ---\n"
        f"{drum_tab}\n"
    )

    analyze_attack_time(audio_path)
    plt.close()

    return result if drum_tab else "🥁 ドラム譜が生成されませんでした"


# ✅ メイン処理
if __name__ == "__main__":
    audio_file = sys.argv[1] if len(sys.argv) > 1 else get_latest_audio_file(downloads_dir)
    audio_path = audio_file if os.path.isabs(audio_file) else os.path.join(downloads_dir, audio_file)

    if not os.path.exists(audio_path):
        print(f"❌ ファイルが見つかりません: {audio_path}")
        exit()

    print(analyze_drum(audio_path))
