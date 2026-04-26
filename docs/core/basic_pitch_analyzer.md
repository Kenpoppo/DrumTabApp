# core/basic_pitch_analyzer.py — 仕様書

> **更新ルール**: `core/basic_pitch_analyzer.py` を変更したら必ずこのファイルと `docs/architecture.md` を同時に更新する。

---

## 1. 責務

Spotify「Basic Pitch」ニューラルネットワークを用いた高精度ピッチ検出でギター / ベース TAB を生成する。  
`core/pitch_analyzer.py` の DSP (piptrack) ベース実装の上位互換として機能する。

---

## 2. 公開 API

### `analyze(audio_path, instrument, chords, key, onset_threshold, frame_threshold, minimum_note_length) -> TabResult`

| 引数 | 型 | デフォルト | 説明 |
|---|---|---|---|
| `audio_path` | `str` | — | 解析対象ファイルパス (.mp3/.wav/.flac/.m4a等) |
| `instrument` | `str` | — | `"guitar"` または `"bass"` |
| `chords` | `list[str] \| None` | `None` | 小節別コードリスト（省略可） |
| `key` | `str` | `""` | キー文字列（省略可） |
| `onset_threshold` | `float \| None` | `None` → 楽器別デフォルト | onsetの検出感度 |
| `frame_threshold` | `float \| None` | `None` → 楽器別デフォルト | フレームレベル閾値 |
| `minimum_note_length` | `float \| None` | `None` → 楽器別デフォルト | 最小ノート長 [ms] |

**戻り値**: `TabResult` (`core/pitch_analyzer.py` の `TabResult` と互換)  
**例外**:
- `ImportError` — `basic-pitch` 未インストール
- `ValueError` — 未対応の楽器

---

## 3. 楽器別デフォルトパラメータ (`_BP_PARAMS`)

| 楽器 | `onset_threshold` | `frame_threshold` | `minimum_note_length` | 理由 |
|---|---|---|---|---|
| guitar | `0.50` | `0.30` | `58` ms | 標準的な検出感度 |
| bass | `0.25` | `0.18` | `_BP_PARAMS` 未使用 | 低域(49-58 Hz)の G1/A1/Bb1 基音の recall 向上のため閾値を大幅に低く設定 |

> **bass の minimum_note_length は BPM 連動**: `max(80, int(16分音符ms × 0.83))`  
> BPM=123 時: 0.83 × 121ms = **101ms** を自動設定。  
> Spleeter 倍音補正の源音符 (Bb2 等) が ~100ms と短いため、フルの 16th より短い係数を使用。

---

## 4. 処理フロー

```
librosa.load(sr=None, mono=True, float32)
  ↓
_estimate_bpm(y, sr, audio_path)
  → drums.wav が同ディレクトリにあれば drums.wav でBPM推定
  → なければ複数 start_bpm 候補でフォールバック
  ↓
[bass only] BPM連動 minimum_note_length 算出
  → max(80, int(16th_note_ms × 0.83))  BPM=123時: 101ms
  ↓
basic_pitch.inference.predict(audio_path, onset_threshold, frame_threshold, minimum_note_length,
                               minimum_frequency=30Hz(bass)/Hz(midi_min), maximum_frequency=Hz(midi_max))
  ↓
音域フィルタ: midi_min <= midi <= midi_max のみ通過
  ↓
[bass only] _merge_sustained_notes(gap_ms=100)
  → 持続音を分割した複数 events を統合 (gap ≤ 100ms の同ピッチを結合)
  ↓
[bass only] _correct_bass_octaves(ratio_threshold=0.12, apply_above_midi=43)
  → Spleeter が低域の基音を落とした場合、倍音 → 基音にオクターブ補正
  ↓
[bass only] post-correction MIDI cap (m ≤ 48: C3 超えを除去)
  ↓
[bass only] _dedup_runs(min_gap_sec=beat_sec/2)
  → 倍音補正後の重複除去: 8分音符未満間隔の同ピッチは最初のみ残す
  ↓
[bass only] _mono_filter(window_sec=subdiv_sec×0.5)
  → ポリフォニー解消: 16分音符/2 窓内の複数音符 → 最低音のみ残す
  ↓
_render_tab(timed_notes, instrument, bpm, chords, key)
  ↓
TabResult(...)
```

---

## 5. ベース固有の後処理

### `_correct_bass_octaves(timed_notes, y, sr, midi_min, ...)`

Spleeter の bass.wav では低域の基音エネルギーが失われ、2nd harmonic(1オクターブ上)が
誤検出される問題を補正する。

**アルゴリズム**:
1. MIDI 43 (G2) 以上のノートに対してのみ補正を適用
2. 候補 = 検出ノート - 12 (1オクターブ下) が midi_min 以上か確認
3. STFT (n_fft=4096) で ±100ms 窓の周波数スペクトルを取得
4. `e_low / e_high >= 0.15` (基音エネルギーが倍音の15%以上) なら、1オクターブ下に修正

**例**: Bb2(46, 116 Hz) 検出時 → Bb1(34, 58 Hz) の比率確認
- e_high(116 Hz) = 4.75、e_low(58 Hz) = 0.87 → 0.87/4.75 = 0.18 ≥ 0.12 → Bb1 に修正 ✓

---

## 6. piptrack との比較

| 特性 | piptrack (core/pitch_analyzer.py) | basic-pitch (本モジュール) |
|---|---|---|
| アルゴリズム | DSP / STFT | 軽量 CNN (ニューラルネットワーク) |
| 多声音対応 | ✗ モノフォニック | ✓ ポリフォニック |
| onset/offset 精度 | △ 近似 | ✓ フレーム単位 |
| ベロシティ検出 | ✗ | ✓ 0–127 |
| 処理速度 | ◎ 高速 | △ 初回ロード数秒 |
| 低域(58 Hz)の検出 | △ 閾値依存 | △ 基音欠落問題あり → 倍音補正で対処 |

---

## 7. 既知の制限

- **Spleeter 音源分離の限界**: Spleeter 5-stems で分離した bass.wav は高密度な繰り返し音符
  (例: 16分音符 ×12 の F2 連打) で多くのノートが失われる。これは Spleeter の設計的制限。
- **G1(49 Hz) の検出数不足**: basic-pitch CNN は G1 の onset を全数検出できない。
  onset=0.25/frame=0.18 で recall は改善されるが GT の 50-60% に留まる。
- **イントロの検出ゼロ**: 曲の冒頭 (m.1-9) は音量が小さく basic-pitch が onset を
  検出できない。これは Spleeter + basic-pitch 構造的制限として許容する。
- **key 検出精度**: `chord_analyzer.analyze()` のキー検出が相対調 (例: Gm vs Dm) を
  混同することがある。これは chord_analyzer 側の制限。

---

## 8. 変更履歴

| 日付 | 変更内容 |
|---|---|
| 2025-07-xx | 初版。basic-pitch ニューラルネットワーク統合 |
| 2025-07-xx | ベースTAB精度改善: `_BP_PARAMS` 楽器別デフォルト追加, `_correct_bass_octaves()` 実装 (Spleeter倍音補正), BPM推定を drums.wav 優先方式に変更, `_mono_filter` 適用 |
| 2025-07-xx | BPM連動 minimum_note_length (× 0.83係数) 追加, `_mono_filter` window を BPM連動 (subdiv × 0.5) に変更, velocity は常に0のためフィルタ無効化 |
| 2025-07-xx | `_merge_sustained_notes(gap_ms=100)` 追加: D2/D3 の持続音再分割を統合; `_dedup_runs(beat_sec/2)` 追加: 倍音補正後の重複除去; `_correct_bass_octaves` ratio_threshold 0.15→0.12 で補正を積極化; post-correction MIDI cap (m≤48) 追加; minimum_frequency=30Hz でモデルコンテキスト拡張; bass onset/frame 閾値 0.35/0.25→0.25/0.18 で G1/Bb1 recall 向上 |
