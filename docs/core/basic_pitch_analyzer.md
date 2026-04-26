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
| bass | `0.35` | `0.25` | `50` ms | 低域(58 Hz以下)の基音検出向上のため閾値を下げる |

---

## 4. 処理フロー

```
librosa.load(sr=None, mono=True, float32)
  ↓
_estimate_bpm(y, sr, audio_path)
  → drums.wav が同ディレクトリにあれば drums.wav でBPM推定
  → なければ複数 start_bpm 候補でフォールバック
  ↓
basic_pitch.inference.predict(audio_path, onset_threshold, frame_threshold, minimum_note_length,
                               minimum_frequency=Hz(midi_min), maximum_frequency=Hz(midi_max))
  ↓
音域フィルタ: midi_min <= midi <= midi_max のみ通過
  ↓
[bass only] _correct_bass_octaves()
  → Spleeter が低域の基音を落とした場合、倍音 → 基音にオクターブ補正
  ↓
[bass only] _mono_filter(window_sec=0.08)
  → ポリフォニー解消: 80ms 窓内の複数音符 → 最低音のみ残す
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
- e_high(116 Hz) = 4.75、e_low(58 Hz) = 0.87 → 0.87/4.75 = 0.18 ≥ 0.15 → Bb1 に修正 ✓

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

- **Bb1 等の基音欠落**: Spleeter 5-stems で分離した bass.wav は 58 Hz 以下の基音が
  弱くなる場合がある。`_correct_bass_octaves()` である程度補正するが完全ではない。
- **イントロの検出感度**: 音量が小さい intro セクションで onset_threshold=0.35 だと
  検出漏れが発生することがある。
- **key 検出精度**: `chord_analyzer.analyze()` のキー検出が相対調 (例: Gm vs Dm) を
  混同することがある。これは chord_analyzer 側の制限。

---

## 8. 変更履歴

| 日付 | 変更内容 |
|---|---|
| 2025-07-xx | 初版。basic-pitch ニューラルネットワーク統合 |
| 2025-07-xx | ベースTAB精度改善: `_BP_PARAMS` 楽器別デフォルト追加, `_correct_bass_octaves()` 実装 (Spleeter倍音補正), BPM推定を drums.wav 優先方式に変更, `_mono_filter` 適用 |
