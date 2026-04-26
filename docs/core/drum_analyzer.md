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

### `analyze(audio_path: str) -> DrumAnalysisResult`

音源ファイルを解析して `DrumAnalysisResult` を返す。

| 引数 | 型 | 説明 |
|---|---|---|
| `audio_path` | `str` | 解析対象の音源ファイルパス（mp3 / wav） |

**戻り値**: `DrumAnalysisResult`

---

### `to_text(result: DrumAnalysisResult) -> str`

`DrumAnalysisResult` を**ドラムタブ譜テキスト**に変換する。

出力形式（16 分音符グリッド）:
- 各列 = 16 分音符 1 つ
- 行 = 楽器（HH: Hi-Hat / SN: Snare / BD: Kick）
- `x` = ヒット、`-` = 無音
- `|` = 拍区切り（4 分音符）
- 2 小節ごとに折り返し

```
──────────────────────────────────────────────────────────
 Drum Tab  |  BPM: 123.0  |  Kick:298 / Snare:45 / HH:134
──────────────────────────────────────────────────────────

     |1---|2---|3---|4---|1---|2---|3---|4---|
 HH  |x-x-|x-x-|x-x-|x-x-|x-x-|x-x-|x-x-|x-x-|
 SN  |----|x---|----|x---|----|x---|----|x---|
 BD  |x---|----|-x--|----|-x--|----|x---|----|```

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
librosa.load(sr=22050, mono=True, float32)
  ↓
librosa.effects.hpss(margin=3.0)  → y_perc（打楽器成分）
  ↓
beat_track(y_perc) → BPM
  ↓
onset_detect(y_perc, backtrack=True, delta=0.05, wait=5) → onset_frames
  ↓
_classify_hit(y_full, frame) × N  → labels[]
  ↓
DrumAnalysisResult(...)
  ↓
to_text() → ドラムタブ譜テキスト
```

---

## 5. ドラム種別分類ロジック (`_classify_hit`)

| 特徴量 | 計算方法 |
|---|---|
| `centroid` | スペクトル重心 Hz |
| `low_r` | 20–200 Hz のパワー比 |
| `high_r` | 5 kHz+ のパワー比 |

**判定ルール（優先度順）:**

1. RMS < 1e-4 → **Unknown**（無音ウィンドウをスキップ）
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
| 2026-04-26 | 初版。HPSS + 3特徴量分類 + データクラス戻り値 || 2026-04-27 | ブラッシュアップ: `wait=10→5` (Hi-Hatインターバル対応), `delta=0.07→0.05` (感度向上), 分類閾値を実データ診断結果に基づき再設計 (Hi-Hat: 13→134, 総検出: 268→480) |
| 2026-04-27 | `to_text()` をサマリーテキストからドラムタブ譜形式（16分音符グリッド、HH/SN/BD行）に全面書き換え |