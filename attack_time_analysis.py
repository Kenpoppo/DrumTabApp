import os
import numpy as np
import librosa
import librosa.display
import matplotlib.pyplot as plt
import scipy.signal as signal
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm

# 日本語フォント設定
plt.rcParams['font.family'] = 'AppleGothic'  # MacならこれでOK


def analyze_attack_time(audio_path):
    # 📥 音源の読み込み (モノラル & float32でメモリ節約)
    y, sr = librosa.load(audio_path, sr=22050, mono=True, dtype=np.float32)

    # 🔍 アタックタイムの解析 (ピーク検出)
    peaks, _ = signal.find_peaks(y, height=0.05, distance=sr//10)
    attack_times = np.diff(peaks) / sr

    # 🔍 特徴量の計算
    zero_crossings = librosa.feature.zero_crossing_rate(y)
    mfcc = librosa.feature.mfcc(y=y, sr=sr, n_mfcc=13)
    spectral_centroid = librosa.feature.spectral_centroid(y=y, sr=sr)

    # 🖊 結果表示
    print("📊 attack_time_analysis 解析結果:")
    print(f"サンプリングレート: {sr} Hz")
    print(f"平均ゼロ交差率: {np.mean(zero_crossings):.4f}")
    print(f"平均スペクトルセントロイド: {np.mean(spectral_centroid):.2f} Hz")
    print(f"ピーク数: {len(peaks)}")
    print(f"平均アタックタイム: {np.mean(attack_times):.4f} 秒" if len(attack_times) > 0 else "アタックタイムは検出されませんでした")

    # 🖊 MFCCの表示
    #plt.figure(figsize=(12, 6))
    #librosa.display.specshow(mfcc, sr=sr, x_axis='time')
    #plt.colorbar()
    #plt.title("MFCC (attack_time_analysis)")
    #plt.tight_layout()
    #plt.show()
