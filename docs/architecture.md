# Architecture — DrumTabApp

> **更新ルール**: パッケージ構成・依存関係・データフローを変更したら必ずこのファイルを更新する。

---

## 1. 概要

音源ファイル（MP3 / WAV）を入力として、ドラム・ギター・ベースのタブ譜を
自動生成するデスクトップアプリ（Python + PyQt5）。

---

## 2. パッケージ構成

```
DrumTabApp/
├── core/                    # ビジネスロジック層（UI 依存ゼロ）
│   ├── __init__.py
│   ├── drum_analyzer.py     # ドラム解析
│   ├── pitch_analyzer.py    # ギター / ベース TAB 生成
│   └── exporter.py          # PDF 出力
├── ui/                      # プレゼンテーション層
│   ├── __init__.py
│   └── main_window.py       # PyQt5 メインウィンドウ
├── main.py                  # エントリポイント
├── docs/                    # 設計ドキュメント（本ファイル含む）
│   ├── architecture.md      # ← 本ファイル
│   ├── core/
│   │   ├── drum_analyzer.md
│   │   ├── pitch_analyzer.md
│   │   └── exporter.md
│   └── ui/
│       └── main_window.md
└── .github/
    └── copilot-instructions.md  # Copilot 自動読み込み指示
```

### 旧ファイル（削除不可・修正不可）
| ファイル | 状態 |
|---|---|
| `drum_analyzer.py` | 旧実装。後方互換のため残存。新規修正禁止 |
| `tab_generator.py` | 旧実装。後方互換のため残存。新規修正禁止 |
| `attack_time_analysis.py` | 旧実装。後方互換のため残存。新規修正禁止 |
| `drum_sheet_generator.py` | 旧実装。後方互換のため残存。新規修正禁止 |
| `main_gui.py` | 旧 GUI。後方互換のため残存。新規修正禁止 |

---

## 3. 依存方向（厳守）

```
[main.py]
    └── ui/main_window.py
            └── core/drum_analyzer.py
            └── core/pitch_analyzer.py
            └── core/exporter.py
```

- `ui/ → core/` のみ許可
- `core/ → ui/` 禁止
- `core/` 内クロス依存 禁止

---

## 4. データフロー

### 4-1. ドラム解析

```
音源ファイル (mp3/wav)
  │
  ▼ librosa.load (sr=22050, mono, float32)
  │
  ▼ librosa.effects.hpss → y_perc（打楽器成分）
  │
  ├── librosa.beat.beat_track(y_perc)    → BPM
  │
  ▼ librosa.onset.onset_detect(y_perc)  → onset_frames[]
  │
  ▼ _classify_hit(y_full, frame)        → "Kick" | "Snare" | "Hi-Hat"
      └── 判定: spectral_centroid + low_ratio + high_ratio
  │
  ▼ DrumAnalysisResult(bpm, hits[], zcr, centroid, mean_interval)
  │
  ▼ to_text()                            → GUI 表示文字列
```

### 4-2. ピッチ解析 / TAB 生成

```
音源ファイル (mp3/wav)
  │
  ▼ librosa.load (sr=None, mono, float32)
  │
  ├── _estimate_bpm(y, sr, audio_path)
  │     → drums.wav が同ディレクトリにあれば drums.wav で BPM 推定（最精度）
  │     → なければ複数 start_bpm 候補でフォールバック
  │
  ┌─────────────────────────────────────────────────────────────────┐
  │ basic-pitch モード (core/basic_pitch_analyzer.py)               │
  │   basic_pitch.inference.predict(onset_threshold, frame_threshold)│
  │     → note_events[(start, end, midi, velocity, bends)]          │
  │   [bass のみ] _correct_bass_octaves()                           │
  │     → Spleeter 倍音補正: e_low/e_high >= 0.15 ならオクターブ下  │
  │   [bass のみ] _mono_filter(window_sec=0.08)                     │
  │     → ポリフォニー解消: 80ms 窓内の最低音のみ残す               │
  └─────────────────────────────────────────────────────────────────┘
  │
  ▼ BPM グリッドに量子化                  → col_map
  │
  ▼ _choose_string(midi, tuning, prev_string, prev_fret, instrument)
  │   → ギター: フレット最小 + ポジション連続性
  │   → ベース: E/A弦優先バイアス(string_depth×1.5) + 開放弦ペナルティ
  │
  ▼ _render_tab()                        → 小節単位 TAB テキスト
  │
  ▼ TabResult(instrument, tab_text, note_count, bpm, timed_notes)
```

---

## 5. スレッドモデル

| スレッド | 役割 |
|---|---|
| メイン (Qt イベントループ) | UI 描画・ユーザー操作 |
| `_Worker(QThread)` | 全解析処理（`core.*` の呼び出し）|

- 解析中はメインスレッドから `setEnabled(False)` でボタンを無効化
- 結果は `finished` シグナル、エラーは `error` シグナルで通知

---

## 6. 技術スタック

| 用途 | ライブラリ | バージョン目安 |
|---|---|---|
| 音声読み込み | `librosa` | 0.10+ |
| HPSS / オンセット / ピッチ / BPM | `librosa` | 同上 |
| 音源分離（5 stems） | `spleeter` | 2.x |
| GUI | `PyQt5` | 5.15+ |
| PDF 出力 | `fpdf` | 1.7+ |
| 数値計算 | `numpy` | 1.24+ |

---

## 7. 変更履歴

| 日付 | 変更内容 |
|---|---|
| 2026-04-26 | `core/` + `ui/` パッケージ構成に再設計。旧ファイル群は残存 |
| 2025-07-xx | ベースTAB精度改善: basic_pitch_analyzer に `_correct_bass_octaves` 追加、`_estimate_bpm` (drums.wav優先)・`_mono_filter`・`_choose_string` bass拡張を pitch_analyzer に追加 |
