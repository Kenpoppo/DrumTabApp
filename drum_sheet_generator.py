import numpy as np
import librosa
import matplotlib
import matplotlib.pyplot as plt

matplotlib.rcParams['axes.unicode_minus'] = False


def _classify_hit(y, sr, frame_idx, hop_length):
    """
    スペクトル重心と周波数帯エネルギーでドラム種別を分類する。
    - Kick  : 低域 (20–200 Hz) 優勢
    - Snare : 中高域 (200–8000 Hz) 優勢
    - Hi-Hat: 高域 (8000 Hz+) 優勢
    """
    center = frame_idx * hop_length
    window = y[max(0, center - hop_length): center + hop_length]
    if len(window) == 0:
        return "Unknown"

    fft   = np.abs(np.fft.rfft(window, n=2048))
    freqs = np.fft.rfftfreq(2048, d=1.0 / sr)

    def band_energy(lo, hi):
        mask = (freqs >= lo) & (freqs < hi)
        return float(np.sum(fft[mask] ** 2))

    kick_e  = band_energy(20, 200)
    snare_e = band_energy(200, 8000)
    hihat_e = band_energy(8000, sr / 2)

    return ["Kick", "Snare", "Hi-Hat"][np.argmax([kick_e, snare_e, hihat_e])]


def generate_drum_sheet(drum_file):
    # 音源の読み込み
    y, sr = librosa.load(drum_file, sr=22050, mono=True, dtype=np.float32)

    hop_length = 512

    # オンセット検出
    onset_frames = librosa.onset.onset_detect(
        y=y, sr=sr, hop_length=hop_length,
        units='frames', backtrack=True,
        pre_max=3, post_max=3, pre_avg=5, post_avg=5, delta=0.07, wait=10
    )
    onset_times = librosa.frames_to_time(onset_frames, sr=sr, hop_length=hop_length)

    # スペクトル解析によるドラム種別分類
    detected_drums = [_classify_hit(y, sr, f, hop_length) for f in onset_frames]

    # 種別ごとの時刻リスト
    kick_times  = [t for t, d in zip(onset_times, detected_drums) if d == "Kick"]
    snare_times = [t for t, d in zip(onset_times, detected_drums) if d == "Snare"]
    hihat_times = [t for t, d in zip(onset_times, detected_drums) if d == "Hi-Hat"]

    # 譜面の描画
    fig, ax = plt.subplots(figsize=(14, 4))
    for times, y_pos, label, color in [
        (kick_times,  1, "Kick",   "steelblue"),
        (snare_times, 2, "Snare",  "tomato"),
        (hihat_times, 3, "Hi-Hat", "seagreen"),
    ]:
        if times:
            ax.eventplot(times, lineoffsets=y_pos, linelengths=0.6, colors=color, label=label)

    ax.set_title("ドラム譜面")
    ax.set_xlabel("時間 (秒)")
    ax.set_yticks([1, 2, 3])
    ax.set_yticklabels(["Kick", "Snare", "Hi-Hat"])
    ax.grid(axis='x', linestyle='--', alpha=0.5)
    ax.legend(loc='upper right')
    plt.tight_layout()
    plt.show()

    print(f"検出オンセット数: {len(onset_times)}")
    print(f"Kick: {len(kick_times)}  Snare: {len(snare_times)}  Hi-Hat: {len(hihat_times)}")
    print(f"ドラムの種類一覧: {detected_drums}")


# テスト実行用
if __name__ == "__main__":
    drum_file = "separated/金木犀 feat.Ado (Official Video)/drums.wav"
    generate_drum_sheet(drum_file)

