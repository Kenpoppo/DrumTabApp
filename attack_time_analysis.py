import os
import numpy as np
import librosa
import matplotlib
import matplotlib.pyplot as plt

matplotlib.rcParams['axes.unicode_minus'] = False


def analyze_attack_time(audio_path):
    # 📥 音源の読み込み
    y, sr = librosa.load(audio_path, sr=22050, mono=True, dtype=np.float32)

    hop_length = 512

    # 🔍 オンセット検出 (生波形ピーク検出より高精度)
    onset_frames = librosa.onset.onset_detect(
        y=y, sr=sr, hop_length=hop_length,
        units='frames', backtrack=True,
        pre_max=3, post_max=3, pre_avg=5, post_avg=5, delta=0.07, wait=10
    )
    onset_times = librosa.frames_to_time(onset_frames, sr=sr, hop_length=hop_length)
    attack_times = np.diff(onset_times)

    # 🔍 特徴量の計算
    zero_crossings    = librosa.feature.zero_crossing_rate(y)
    mfcc              = librosa.feature.mfcc(y=y, sr=sr, n_mfcc=13)
    spectral_centroid = librosa.feature.spectral_centroid(y=y, sr=sr)

    print("📊 attack_time_analysis 解析結果:")
    print(f"サンプリングレート: {sr} Hz")
    print(f"平均ゼロ交差率: {np.mean(zero_crossings):.4f}")
    print(f"平均スペクトルセントロイド: {np.mean(spectral_centroid):.2f} Hz")
    print(f"検出オンセット数: {len(onset_frames)}")
    if len(attack_times) > 0:
        print(f"平均アタックタイム: {np.mean(attack_times):.4f} 秒")
    else:
        print("アタックタイムは検出されませんでした")

