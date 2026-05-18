# Architecture — DrumTabApp

> **更新ルール**: パッケージ構成・依存関係・データフローを変更したら必ずこのファイルを更新する。

---

## 1. 概要

音源ファイル（MP3 / WAV）を入力として、ドラム・ギター・ベースのタブ譜を
自動生成するデスクトップアプリ（Python + PyQt5）。

---

## 2. パッケージ構成

```text
DrumTabApp/
├── core/                         # ビジネスロジック層（UI 依存ゼロ）
│   ├── __init__.py
│   ├── analysis_session.py       # Lazy Eval + joblib ディスクキャッシュ共有セッション
│   ├── _audio_cache.py           # スレッドセーフ LRU 音声キャッシュ（内部用）
│   ├── drum_analyzer.py          # ドラム解析
│   ├── pitch_analyzer.py         # ギター / ベース TAB 生成 (piptrack DSP)
│   ├── basic_pitch_analyzer.py   # ギター / ベース TAB 生成 (basic-pitch NN)
│   ├── chord_analyzer.py         # キー検出・コード進行解析
│   ├── midi_exporter.py          # MIDI (.mid) エクスポート
│   ├── gp5_exporter.py           # Guitar Pro (.gp5) エクスポート
│   └── exporter.py               # PDF 出力
├── ui/                           # プレゼンテーション層
│   ├── __init__.py
│   └── main_window.py            # PyQt5 メインウィンドウ
├── main.py                       # エントリポイント
├── docs/                         # 設計ドキュメント（本ファイル含む）
│   ├── architecture.md           # ← 本ファイル
│   ├── core/
│   │   ├── _audio_cache.md
│   │   ├── drum_analyzer.md
│   │   ├── pitch_analyzer.md
│   │   ├── basic_pitch_analyzer.md
│   │   ├── gp5_exporter.md
│   │   └── exporter.md
│   └── ui/
│       └── main_window.md
└── .github/
    └── copilot-instructions.md   # Copilot 自動読み込み指示
```

### 旧ファイル（削除不可・修正不可）

| ファイル | 状態 |
| --- | --- |
| `drum_analyzer.py` | 旧実装。後方互換のため残存。新規修正禁止 |
| `tab_generator.py` | 旧実装。後方互換のため残存。新規修正禁止 |
| `attack_time_analysis.py` | 旧実装。後方互換のため残存。新規修正禁止 |
| `drum_sheet_generator.py` | 旧実装。後方互換のため残存。新規修正禁止 |
| `main_gui.py` | 旧 GUI。後方互換のため残存。新規修正禁止 |

---

## 3. 依存方向（厳守）

```text
[main.py]
    └── ui/main_window.py
            ├── core/_audio_cache.py   (ファイル切替時にキャッシュクリア)
            ├── core/drum_analyzer.py
            ├── core/pitch_analyzer.py
            ├── core/basic_pitch_analyzer.py
            ├── core/chord_analyzer.py
            ├── core/midi_exporter.py
            ├── core/gp5_exporter.py
            └── core/exporter.py
```

- `ui/ → core/` のみ許可
- `core/ → ui/` 禁止
- `core/` 内クロス依存: `analysis_session` / `_audio_cache` は `chord_analyzer` / `pitch_analyzer` / `basic_pitch_analyzer` / `drum_analyzer` から参照可。それ以外は禁止

---

## 4. データフロー

### 4-0. AnalysisSession — 前処理共有レイヤー

```text
AnalysisSession(path)
  │  joblib ディスクキャッシュ (~/.cache/DrumTabApp)
  ├── .audio_native  → _cached_load(path, "None", mtime)     librosa.load(sr=None)
  ├── .audio_22k     → _cached_load(path, "22050", mtime)    librosa.load(sr=22050)
  ├── .hpss_native   → _cached_hpss(path, "None", mtime)     hpss(audio_native)
  ├── .hpss_22k      → _cached_hpss(path, "22050", mtime)    hpss(audio_22k)
  └── .bpm           → _cached_bpm(path, mtime)
        → drums.wav 優先 → パーカッシブ多候補フォールバック
```

全 analyzer は `analyze(session)` で同一 session を共有する。
「全解析」ボタン実行時は 1 session で 4 analyzer が全共有するため、
load + HPSS + BPM は各 1 回のみ実行される（joblib ディスクキャッシュで 2 回目以降は即座）。

### 4-1. ドラム解析

```text
AnalysisSession.audio_22k  → y (22050 Hz)
AnalysisSession.hpss_22k   → y_perc（打楽器成分）
AnalysisSession.bpm        → BPM
  │
  ├── onset_strength(y_perc) once → onset_env_perc
  │     └── onset_detect(onset_envelope=onset_env_perc) → onset_frames[]
  │
  ▼ librosa.stft(y_full) ** 2 → S（1回だけ計算）
  │
  ▼ _classify_hits_batch(S, onset_frames) → labels[] （numpy 一括）
      └── 判定: spectral_centroid + low_ratio + high_ratio
  │
  ▼ DrumAnalysisResult(bpm, hits[], zcr, centroid, mean_interval)
  │
  ▼ to_text() → GUI 表示文字列
```

### 4-2. ピッチ解析 / TAB 生成

```text
AnalysisSession.audio_native → y, sr
AnalysisSession.hpss_native  → y_harm（倍音成分）
AnalysisSession.bpm          → BPM（drums.wav 優先）
  │
  ├── (旧: _audio_cache.load + hpss + _estimate_bpm を削除)
  │
  ┌─────────────────────────────────────────────────────────────────┐
  │ basic-pitch モード (core/basic_pitch_analyzer.py)               │
  │   basic_pitch.inference.predict(onset_threshold, frame_threshold)│
  │     → note_events[(start, end, midi, velocity, bends)]          │
  │   [bass のみ] _correct_bass_octaves()                           │
  │     → Spleeter 倍音補正: e_low/e_high >= 0.12 ならオクターブ下  │
  │   [bass のみ] _mono_filter(window_sec=subdiv×0.5)               │
  │     → ポリフォニー解消: 窓内の最低音のみ残す                    │
  └─────────────────────────────────────────────────────────────────┘
  │
  ▼ numpy ベクトル演算で一括フィルタ（piptrack モード）
      magnitudes.argmax(axis=0) → 全フレーム一括、dedup も np.diff で実現
  │
  ▼ BPM グリッドに量子化 → col_map
  │
  ▼ _choose_string(midi, tuning, prev_string, prev_fret, instrument)
  │   → ギター: フレット最小 + ポジション連続性
  │   → ベース: E/A弦優先バイアス(string_depth×1.5) + 開放弦ペナルティ
  │
  ▼ _render_tab() → 小節単位 TAB テキスト
  │
  ▼ TabResult(instrument, tab_text, note_count, bpm, timed_notes)
```

---

## 5. スレッドモデル

| スレッド | 役割 |
| --- | --- |
| メイン (Qt イベントループ) | UI 描画・ユーザー操作 |
| `_Worker(QThread)` | 全解析処理（`core.*` の呼び出し） |

- 解析中はメインスレッドから `setEnabled(False)` でボタンを無効化
- 結果は `finished` シグナル、エラーは `error` シグナルで通知

---

## 6. 技術スタック

| 用途 | ライブラリ | バージョン目安 |
| --- | --- | --- |
| 音声読み込み・キャッシュ | `librosa` + `core/_audio_cache` | 0.10+ |
| HPSS / オンセット / ピッチ / BPM | `librosa` | 同上 |
| 音源分離（5 stems） | `spleeter` | 2.x |
| 高精度ピッチ検出 | `basic-pitch` | 0.3+ |
| GUI | `PyQt5` | 5.15+ |
| PDF 出力 | `fpdf` | 1.7+ |
| MIDI 出力 | `MIDIUtil` | 1.2+ |
| 数値計算 | `numpy` | 1.24+ |

---

## 7. 変更履歴

| 日付 | 変更内容 |
| --- | --- |
| 2026-04-26 | `core/` + `ui/` パッケージ構成に再設計。旧ファイル群は残存 |
| 2025-07-xx | ベースTAB精度改善: basic_pitch_analyzer に `_correct_bass_octaves` 追加、`_estimate_bpm` (drums.wav優先)・`_mono_filter`・`_choose_string` bass拡張を pitch_analyzer に追加 |
| 2026-04-28 | 性能改善: `core/_audio_cache.py` 追加（スレッドセーフ LRU キャッシュ）。ドラム分類を per-onset FFT → STFT 一括に変更。`_estimate_bpm` の onset_strength 再計算を排除。piptrack フレームループを numpy ベクトル演算に置換。コード/キー検出を行列積に一括化 |
| 2026-05-13 | `core/analysis_session.py` 追加（Lazy Eval + joblib ディスクキャッシュ）。全 analyzer が `analyze(source: Union[str, AnalysisSession])` を受け付けるよう変更。`ui/main_window.py` に「全解析」ボタン追加 — 1 session で 4 analyzer を連鎖実行し、audio/HPSS/BPM の重複計算を完全排除 |
