# core/chord_analyzer.py — 仕様書

> **更新ルール**: `core/chord_analyzer.py` を変更したら必ずこのファイルと `docs/architecture.md` を同時に更新する。

---

## 1. 責務

音源ファイルのキー（調性）と小節別コード進行を解析する。  
出力結果は `ui/main_window.py` 経由で各 TAB 生成モジュールに渡され、TAB 表示にコード情報を付記するために使用する。

---

## 2. 公開 API

### `analyze(source: Union[str, AnalysisSession]) -> ChordAnalysisResult`

| 引数 | 型 | 説明 |
|---|---|---|
| `source` | `str` または `AnalysisSession` | 解析対象のファイルパス、または共有セッション |

`str` を渡した場合は内部で `AnalysisSession(source)` を生成する（後方互換）。  
`AnalysisSession` を渡すと `audio_native` を他モジュールと共有してゼロコストで再利用する。

**戻り値**: `ChordAnalysisResult`  
**例外**: なし（librosa が対応するフォーマットを受け付ける）

---

## 3. データクラス

### `ChordAnalysisResult`

```python
@dataclass
class ChordAnalysisResult:
    key:               str         # 例: "A Minor", "C Major"
    key_confidence:    float       # 0.0 〜 1.0 (Pearson 相関の正規化スコア)
    chord_per_measure: List[str]   # インデックス = 小節番号 (0-based)
    bpm:               float       # chord_analyzer 独自推定 BPM
```

> **注意**: `bpm` は `librosa.beat.beat_track(y=y, sr=sr)` で独自推定する。
> `AnalysisSession.bpm`（drums.wav 優先）と異なる場合があるため、
> ドラム/ピッチ TAB と BPM を統一したい場合は `AnalysisSession.bpm` を使用すること。

---

## 4. 処理フロー

```
AnalysisSession.audio_native → y, sr（joblib ディスクキャッシュ）
  ↓
librosa.feature.chroma_cqt(y, sr, hop_length=512) → chroma (12, T)
  ↓
librosa.beat.beat_track(y, sr, hop_length=512) → bpm, beat_frames
  ↓
_detect_key(chroma.sum(axis=1))
  → Krumhansl-Schmuckler 法: chroma_sum × 24 キープロファイルを Pearson 相関で比較
  → 最大相関のキーを返す（e.g. "A Minor"）
  ↓
_detect_chords_per_measure(chroma, beat_frames, beats_per_measure=4)
  → 小節境界 = beat_frames[::4]
  → 各小節の chroma 平均 → 正規化 → コサイン類似度 (n_valid, 12) @ (12, 84)
  → argmax でコード名を決定（84 テンプレート: 12 ルート × 7 コードタイプ）
  ↓
ChordAnalysisResult(key, key_confidence, chord_per_measure, bpm)
```

---

## 5. キー検出アルゴリズム (`_detect_key`)

**Krumhansl-Schmuckler プロファイル法**:

1. 曲全体の chroma 総和 `chroma_sum` (12,) を計算
2. 24 キープロファイル (`_ALL_PROFILES`: 12 Major + 12 Minor) と Pearson 相関を一括計算
3. 相関が最大のキーを採用
4. `confidence = (max_corr - min_corr) / (range + ε)` で 0〜1 に正規化

> 24 回の `np.corrcoef` ループを `_ALL_PROFILES @ x` の行列積1回に集約。

---

## 6. コード検出アルゴリズム (`_detect_chords_per_measure`)

**コードテンプレートマッチング**:

| テンプレート数 | 構成 |
|---|---|
| 84 | 12 ルート × 7 コードタイプ (`"", "m", "7", "m7", "M7", "dim", "sus4"`) |

各小節の平均クロマを正規化し、`(n_valid, 12) @ (12, 84)` の行列積でコサイン類似度を一括計算。

---

## 7. 定数

| 定数 | 値 | 説明 |
|---|---|---|
| `_KS_MAJOR` | Krumhansl-Schmuckler Major プロファイル (12 値) | キー検出用重み |
| `_KS_MINOR` | Krumhansl-Schmuckler Minor プロファイル (12 値) | キー検出用重み |
| `_CHORD_TYPES` | 7 種類のコードタイプ定義 | コードテンプレート生成用 |
| `_CHORD_TEMPLATE_MATRIX` | shape `(84, 12)` | 全コードテンプレートを事前構築 |
| `_ALL_PROFILES` | shape `(24, 12)` | 全キープロファイルを事前構築 |

---

## 8. 依存ライブラリ

- `librosa` — 音声処理全般 (chroma_cqt, beat_track)
- `numpy` — 数値計算

**禁止**: `matplotlib`, `PyQt5` など UI 系ライブラリの import

---

## 9. 変更履歴

| 日付 | 変更内容 |
|---|---|
| 2026-04-28 | 初版。Krumhansl-Schmuckler キー検出 + コサイン類似度コード検出 + データクラス戻り値 |
| 2026-05-13 | `analyze(audio_path: str)` → `analyze(source: Union[str, AnalysisSession])` に変更。`_audio_cache.load()` を `AnalysisSession.audio_native` に置換。`beat_track` は小節境界算出に必要なため残存 |
| 2026-05-19 | 仕様書を新規作成（ドキュメント漏れを修正） |
