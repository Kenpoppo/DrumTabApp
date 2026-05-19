# core/drum_analyzer.py — 仕様書

> **更新ルール**: `core/drum_analyzer.py` を変更したら必ずこのファイルと `docs/architecture.md` を同時に更新する。

---

## 1. 責務

音源ファイルを受け取り、以下を返す **唯一** のドラム解析モジュール。

- BPM 推定
- オンセット（打撃タイミング）検出
- Kick / Snare / Hi-Hat の種別分類
- サマリー統計量（ZCR, スペクトル重心, 平均アタック間隔）

旧 `drum_analyzer.py`・`attack_time_analysis.py`・`drum_sheet_generator.py` の機能をここに一本化。

---

## 2. 公開 API

### `analyze(source: Union[str, AnalysisSession]) -> DrumAnalysisResult`

音源ファイルを解析して `DrumAnalysisResult` を返す。

| 引数     | 型                             | 説明                                           |
| -------- | ------------------------------ | ---------------------------------------------- |
| `source` | `str` または `AnalysisSession` | 解析対象の音源ファイルパス、または共有セッション |

`str` を渡した場合は内部で `AnalysisSession(source)` を生成する（後方互換）。  
`AnalysisSession` を渡すと `audio_22k / hpss_22k / bpm` を他モジュールと共有してゼロコストで再利用する。

**戻り値**: `DrumAnalysisResult`

---

### `to_text(result: DrumAnalysisResult, chords: List[str] | None = None, key: str = "") -> str`

`DrumAnalysisResult` を**ドラムタブ譜テキスト**に変換する。

| 引数 | 型 | デフォルト | 説明 |
|---|---|---|---|
| `result` | `DrumAnalysisResult` | — | `analyze()` の戻り値 |
| `chords` | `list[str] \| None` | `None` | 小節別コードリスト（`chord_analyzer.analyze()` の `chord_per_measure`） |
| `key` | `str` | `""` | キー文字列（例: `"A Minor"`）。コードヘッダ行に付記される |

出力形式（16 分音符グリッド）:
- 各列 = 16 分音符 1 つ
- 行 = 楽器（HH: Hi-Hat / SN: Snare / BD: Kick）
- `x` = Hi-Hat ヒット（標準 ASCII drum tab 記法）
- `o` = Snare / Kick ヒット（標準 ASCII drum tab 記法）
- `-` = 無音
- `|` = 拍区切り（4 分音符）、`||` = 小節区切り
- ビートカウント行: `1e+a` 形式（標準ドラムカウント: "1-e-and-a"）
- 2 小節ごとに折り返し

```
──────────────────────────────────────────────────────────
 Drum Tab  |  BPM: 123.0  |  Kick:298 / Snare:45 / HH:134
──────────────────────────────────────────────────────────

     |1e+a|2e+a|3e+a|4e+a||1e+a|2e+a|3e+a|4e+a|
 HH  |x-x-|x-x-|x-x-|x-x-||x-x-|x-x-|x-x-|x-x-|
 SN  |----|o---|----|o---||----|----|o---|----|  
 BD  |o---|----|----|----||o---|----|----|----| ```

---

## 3. データクラス

### `DrumHit`

```python
@dataclass
class DrumHit:
    time:  float   # オンセット時刻 (秒)
    label: str     # "Kick" | "Snare" | "Hi-Hat" | "Unknown"
```

### `DrumAnalysisResult`

```python
@dataclass
class DrumAnalysisResult:
    bpm:                  float
    hits:                 List[DrumHit]
    zero_crossing_rate:   float
    spectral_centroid_hz: float
    mean_attack_interval: float   # 秒
```

プロパティ: `onset_count`, `kick_count`, `snare_count`, `hihat_count`

---

## 4. 処理フロー

```
AnalysisSession.audio_22k   → y, sr  (22050 Hz, joblib ディスクキャッシュ)
  ↓
AnalysisSession.hpss_22k    → y_perc （打楽器成分、キャッシュ共有）
  ↓
AnalysisSession.bpm         → BPM   （drums.wav 優先、キャッシュ共有）
  ↓
onset_strength(y_perc) once → onset_env_perc
  ↓
onset_detect(onset_envelope=onset_env_perc, delta=0.05, wait=5) → onset_frames
  ↓
librosa.stft(y_full, n_fft=2048) ** 2                           → S（1回のみ計算）
  ↓
_classify_hits_batch(S, onset_frames)                           → labels[]（numpy 一括）
  ↓
DrumAnalysisResult(...)
  ↓
to_text() → ドラムタブ譜テキスト
```

---

## 5. ドラム種別分類ロジック (`_classify_hits_batch`)

STFT パワースペクトル `S` から全オンセットを **numpy ベクトル演算で一括分類** する。
旧 `_classify_hit()` (per-onset FFT ループ) を置き換え、数百回の個別 FFT を排除。

| 特徴量 | 計算方法 |
|---|---|
| `centroid` | スペクトル重心 Hz (`_FREQS_DRUM[:, None] * powers).sum(axis=0) / total`) |
| `low_r` | 20–200 Hz のパワー比 (`powers[_LO_MASK].sum(axis=0) / total`) |
| `high_r` | 5 kHz+ のパワー比 (`powers[_HI_MASK].sum(axis=0) / total`) |

**判定ルール（優先度順、ベクトル演算）:**

1. `rms_proxy = sqrt(total / N_FFT) < 1e-4` → **Unknown**（無音フレームを除外）
2. `centroid > 5000 Hz` または `centroid > 4000 Hz` と `high_r > 0.20` → **Hi-Hat**
3. `centroid < 1500 Hz` または `centroid < 2500 Hz` と `low_r > 0.45` → **Kick**
4. それ以外 → **Snare**

> 実データ診断（金木犀 feat.Ado drums.wav）に基づく閾値設計:
> centroid median=367 Hz、203/268 ヒットが 1500 Hz 未満 → Kick層はデータ的に多いことが確認済み

---

## 6. 定数

| 定数 | 値 | 説明 |
|---|---|---|
| `SR` | `22_050` | リサンプリングレート |
| `HOP_LENGTH` | `512` | STFTホップ長 |
| `N_FFT` | `2_048` | FFT窓サイズ |
| `_FREQS_DRUM` | `rfftfreq(N_FFT, 1/SR)` | モジュール初期化時1回計算・全分類で共用 |
| `_LO_MASK` | `freqs ∈ [20, 200) Hz` | 低域パワー比マスク（Kick 判定用） |
| `_HI_MASK` | `freqs ≥ 5000 Hz` | 高域パワー比マスク（Hi-Hat 判定用） |
| `onset_detect.delta` | `0.05` | オンセット検知感度（弱いHi-Hatも捕捉） |
| `onset_detect.wait` | `5` | 最小フレーム間隔（16分音符Hi-Hat検出用） |

---

## 7. 依存ライブラリ

- `librosa` — 音声処理全般
- `numpy` — 数値計算

**禁止**: `matplotlib`, `PyQt5` など UI 系ライブラリの import

---

## 8. 変更履歴

| 日付 | 変更内容 |
|---|---|
| 2026-04-26 | 初版。HPSS + 3特徴量分類 + データクラス戻り値 |
| 2026-04-27 | ブラッシュアップ: `wait=10→5` (Hi-Hatインターバル対応), `delta=0.07→0.05` (感度向上), 分類閾値を実データ診断結果に基づき再設計 (Hi-Hat: 13→134, 総検出: 268→480) |
| 2026-04-27 | `to_text()` をサマリーテキストからドラムタブ譜形式（16分音符グリッド、HH/SN/BD行）に全面書き換え |
| 2026-04-28 | 性能改善: `onset_strength` を1回だけ計算し `beat_track` / `onset_detect` 両方に渡すよう変更。`_classify_hit()` を廃止し `_classify_hits_batch()` に置換（per-onset FFT ループ → STFT 1 回 + numpy 一括分類）。`_FREQS_DRUM` / `_LO_MASK` / `_HI_MASK` をモジュール定数として初期化時に1回だけ計算 |
| 2026-05-13 | `analyze(audio_path: str)` → `analyze(source: Union[str, AnalysisSession])` に変更。`librosa.load` + `hpss` + `beat_track` を `AnalysisSession.audio_22k` / `.hpss_22k` / `.bpm` で代替し、全モジュール間でゼロコスト共有を実現 |
| 2026-05-19 | `to_text()` に `chords: List[str] \| None` / `key: str` オプショナルパラメータを追記（実装は既存。ドキュメント漏れを修正） |
