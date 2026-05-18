# core/pitch_analyzer.py — 仕様書

> **更新ルール**: `core/pitch_analyzer.py` を変更したら必ずこのファイルと `docs/architecture.md` を同時に更新する。

---

## 1. 責務

音源ファイルを受け取り、ギター / ベースのビートアライン TAB を生成する **唯一** のピッチ解析モジュール。

旧 `tab_generator.py` の機能をここに置き換え。

---

## 2. 公開 API

### `analyze(source: Union[str, AnalysisSession], instrument: str) -> TabResult`

| 引数 | 型 | 説明 |
| --- | --- | --- |
| `source` | `str` または `AnalysisSession` | 解析対象ファイルパス、または共有セッション |
| `instrument` | `str` | `"guitar"` または `"bass"` |
| `chords` | `list[str] \| None` | 小節別コードリスト（省略可） |
| `key` | `str` | キー文字列（省略可） |

`str` を渡した場合は内部で `AnalysisSession(source)` を生成する（後方互換）。  
`AnalysisSession` を渡すと `audio_native / hpss_native / bpm` を他モジュールと共有してゼロコストで再利用する。

**TAB スロット幅**: 2 文字固定（標準 ASCII TAB 形式）
- 1 桁フレット (0–9): `"-5"` 形式
- 2 桁フレット (10+): `"15"` 形式
- レスト: `"--"`
- 小節内ビート区切り: `"|"`, 小節区切り: `"||"` |

**コード行形式** (主行 prefix `" G |"` = 4 文字と列整列):
```
   |Gm7                                ||Cm7                                |
 G |--------|--------|--------|--------||--------|--------|--------|--------|
```

**戻り値**: `TabResult`  
**例外**: `ValueError` — 未対応の楽器が指定された場合

---

## 3. データクラス

### `TabResult`

```python
@dataclass
class TabResult:
    instrument: str    # "guitar" | "bass"
    tab_text:   str    # 表示用テキスト TAB
    note_count: int    # 配置できたノート数
    bpm:        float  # 推定 BPM
```

---

## 4. 処理フロー

```
AnalysisSession.audio_native → y, sr  (joblib ディスクキャッシュ)
  ↓
AnalysisSession.hpss_native  → y_harm（倍音成分、キャッシュ共有）
  ↓
AnalysisSession.bpm          → BPM（drums.wav 優先、キャッシュ共有）
  ↓
piptrack(y_harm, hop_length=512, fmin=_FMIN[instrument]) → pitches, magnitudes
  ↓
適応閾値: np.percentile(magnitudes[magnitudes>0], 80)
  ↓
numpy ベクトル演算で一括フィルタ（Python ループを排除）:
  magnitudes.argmax(axis=0) → best_bin[]
  mask: mag >= threshold & pitch > 0 & MIDI 音域内
  dedup: (midi != prev_midi) | (frame_gap > 1)
  ↓
BPM グリッドに量子化 (col = round(t / subdiv_sec))
  ↓
_render_tab() → 小節単位 TAB テキスト
  ↓
TabResult(...)
```

---

## 5. ピッチフィルタリング

| 条件 | 処理 |
|---|---|
| `magnitudes[mag_idx, t] < mag_threshold` | ノイズとして捨てる |
| `pitch <= 0` | 無音フレームとして捨てる |
| MIDI 音域外 (`midi < midi_min` または `> midi_max`) | 倍音・ノイズ誤検出として除去 |
| 前フレームと同一 MIDI ノート | 連続同一音として捨てる（デデュプ）|

**適応的マグニチュード閾値**: `np.percentile(magnitudes[magnitudes>0], 80)`
音源レベルにかかわらず常に上位 20% のマグニチュードを持つ標柄みのピッチのみを有効とする。

---

## 6. ビートアライン TAB 形式

- 1 列 = `60 / BPM / _SUBDIVISIONS` 秒（デフォルト: 16th note）
- `_MEASURES_PER_LINE` 小節ごとに改行
- ビート内サブ分割区切りは `|`、小節間は `||`
- **フレット番号は 3 文字固定幅**: `-5-`（1 桁）/ `10-`（2 桁）/ `---`（空白）
  - 隣接ノートが混在しても読み舊りない

**例（guitar, BPM=120, 2小節）:**
```
 e |-0---------|-0---------|-0---------|...|
 B |-----------|-----------|...|
 G |-----------|-----------|...|
 D |-----------|-----------|...|
 A |-----------|-----------|...|
 E |-----------|-----------|...|```
```

---

## 7. チューニング定義

| 楽器 | 弦（高→低） | MIDI ノート番号 | 音域 |
|---|---|---|---|
| guitar | e B G D A E | 64 59 55 50 45 40 | MIDI 40–88 (E2–E6) |
| bass | G D A E | 43 38 33 28 | MIDI 28–55 (E1–G3) |

> **bass MIDI音域**: 旧 (28, 67) を (28, 55) に絞り込み。G3 より高い音はベースの一般的な演奏域から外れるため。

**fmin 設定**:

| 楽器 | fmin | 理由 |
|---|---|---|
| guitar | `librosa.note_to_hz("D2")` ≈ 73 Hz | 低E=82 Hzより少し下から探索 |
| bass | `librosa.note_to_hz("C1")` ≈ 33 Hz | 低E=41 Hzより下から探索 |

---

## 8. 定数

| 定数 | 値 | 説明 |
|---|---|---|
| `_MAG_THRESHOLD` | `8.0` | 適応閾値が使えない場合のフォールバック値 |
| `_SUBDIVISIONS` | `4` | 1 拍あたりの分割数（16th note）|
| `_MEASURES_PER_LINE` | `2` | 1 行あたりの小節数（SUBDIVISIONS=4時に行長適切化）|
| `_COLS_PER_MEASURE` | `16` | 1 小節あたりの列数（4/4拍子）|
| `_MIDI_RANGE["bass"]` | `(28, 55)` | ベース音域 E1–G3 に絞り込み (旧: 28-67) |
| `_BPM_MIN`, `_BPM_MAX` | `60.0`, `200.0` | BPM 推定の有効範囲 |
| `_BPM_CANDIDATES` | `[60, 75, 90, 100, 120, 140]` | フォールバック BPM 推定の初期値候補 |

---

## 9. 補助関数（内部）

### `_estimate_bpm(y, sr, audio_path) -> float`

同ディレクトリに `drums.wav` があれば drums.wav でBPM推定（最精度）。
なければ `onset_strength` を **1回だけ計算**し、6つの `start_bpm` 候補で
`beat_track(onset_envelope=onset_env, ...)` を実行して onset 強度スコアが
最大の候補を採用する。（旧実装では `beat_track(y=y, ...)` を6回呼び出し、
`onset_strength` が内部で6回再計算されていた問題を修正）

### `_mono_filter(notes, window_sec) -> List`

80ms 以内の複数ノートをグループ化し、オクターブ重複を除去した上で最低音
（基音）のみを残す。ベース TAB のポリフォニー問題を解消する。

### `_choose_string(midi, tuning, prev_string, prev_fret, instrument) -> (s, fret) | None`

最適な弦・フレットを選択する。  
優先順位:
1. フレット 0–24 に収まる弦のみ候補
2. 前ノートと同弦・近傍フレット（差≤5）でポジション加点 (−10)
3. ベース用: 低弦(E/A)優先バイアス `string_depth × 1.5`
4. ベース用: フレット 0–2 にペナルティ (+4.0)
5. フレット番号最小

---

## 10. 依存ライブラリ

- `librosa` — 音声処理全般
- `numpy` — 数値計算
- `os` — drums.wav パス解決

**禁止**: `matplotlib`, `PyQt5` など UI 系ライブラリの import

---

## 11. 変更履歴

| 日付 | 変更内容 |
|---|---|
| 2026-04-26 | 初版。HPSS + マグニチュード閾値 + BPM グリッド量子化 + データクラス戻り値 |
| 2026-04-27 | ブラッシュアップ: bassチューニング修正, fmin追加, MIDI音域フィルタ, 適応的mag閾値, SUBDIVISIONS=4, MEASURES_PER_LINE=2 |
| 2026-04-27 | `_render_tab()` スロット幅を 3 文字固定幅に変更 |
| 2025-07-xx | ベースTAB精度改善: `_estimate_bpm`(drums.wav優先), `_mono_filter`(ポリフォニー解消), `_choose_string` に bass用 E/A 弦バイアス追加, `_MIDI_RANGE["bass"]`=(28,55) に絞り込み |
| 2026-04-28 | 性能改善: `_estimate_bpm()` の `onset_strength` 再計算を排除（`onset_envelope=` を明示渡し）。フレームループを numpy ベクトル演算に全置換（`magnitudes.argmax(axis=0)` で全フレーム一括処理、dedup も `np.diff` で実現）。`librosa.load()` を `_audio_cache.load()` に変更して chord_analyzer との音声キャッシュ共有を実現 |
| 2026-05-13 | `analyze(audio_path, ...)` → `analyze(source: Union[str, AnalysisSession], ...)` に変更。`_audio_cache.load()` + `hpss` + `_estimate_bpm()` を `AnalysisSession.audio_native` / `.hpss_native` / `.bpm` に置換し、全モジュール間でゼロコスト共有を実現 |
