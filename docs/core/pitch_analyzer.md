# core/pitch_analyzer.py — 仕様書

> **更新ルール**: `core/pitch_analyzer.py` を変更したら必ずこのファイルと `docs/architecture.md` を同時に更新する。

---

## 1. 責務

音源ファイルを受け取り、ギター / ベースのビートアライン TAB を生成する **唯一** のピッチ解析モジュール。

旧 `tab_generator.py` の機能をここに置き換え。

---

## 2. 公開 API

### `analyze(audio_path: str, instrument: str) -> TabResult`

| 引数 | 型 | 説明 |
|---|---|---|
| `audio_path` | `str` | 解析対象の音源ファイルパス |
| `instrument` | `str` | `"guitar"` または `"bass"` |
| `chords` | `list[str] \| None` | 小節別コードリスト（省略可） |
| `key` | `str` | キー文字列（空文字列で指定展算展可） |

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
librosa.load(sr=None, mono=True, float32)
  ↓
librosa.effects.hpss(margin=3.0)  → y_harm（倍音成分）
  ↓
beat_track(y_full) → BPM / 分割グリッド (subdiv_sec)
  ↓
piptrack(y_harm, hop_length=512, fmin=_FMIN[instrument])  → pitches, magnitudes
  ↓
適応閾値: np.percentile(magnitudes[magnitudes>0], 80)
  ↓
フィルタ: mag >= mag_threshold & pitch > 0 & MIDI 音域内 & 連続同一音除去
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
| bass | G D A E | 43 38 33 28 | MIDI 28–67 (E1–G4) |

> **bassチューニング修正済み**: 旧定義 [55,50,45,40] (ギター下4弦=1オクターブ高)はバグ。正しい標準ベースチューニング [43,38,33,28] に修正。

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

---

## 9. 依存ライブラリ

- `librosa` — 音声処理全般
- `numpy` — 数値計算

**禁止**: `matplotlib`, `PyQt5` など UI 系ライブラリの import

---

## 10. 変更履歴

| 日付 | 変更内容 |
|---|---|
| 2026-04-26 | 初版。HPSS + マグニチュード閾値 + BPM グリッド量子化 + データクラス戻り値 || 2026-04-27 | ブラッシュアップ: bassチューニング修正[55,50,45,40]→[43,38,33,28], fmin追加(基音確実捕捉), MIDI音域フィルタ, 適応的mag閾値(80th pct), SUBDIVISIONS=4(16分音符), MEASURES_PER_LINE=2, `||`小節区切り修正 (Bass配置: 405→562) |
| 2026-04-27 | `_render_tab()` スロット幅を 2 文字→ 3 文字固定幅に変更（`-5-`/`10-`/`---`）、隔接ノートの読み舊り問題を解沈 |