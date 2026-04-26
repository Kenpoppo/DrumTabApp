# core/gp5_exporter.py — GP4/GP5 エクスポーター

## 概要

解析結果（ドラム・ギター・ベース）を Guitar Pro 形式（`.gp4`）に書き出す。
TuxGuitar など Guitar Pro 互換ソフトで直接開くことが可能。

---

## 主要 API

```python
def export_gp5(
    save_path: str,
    bpm: float,
    drum_result: DrumAnalysisResult | None = None,
    bass_result: TabResult | None = None,
    guitar_result: TabResult | None = None,
    title: str = "DrumTabApp",
    artist: str = "",
) -> Gp5ExportResult:
```

### 戻り値 `Gp5ExportResult`

| フィールド | 型 | 説明 |
|---|---|---|
| `saved_path` | `str` | 実際に保存されたファイルパス |
| `n_tracks` | `int` | 書き出しトラック数 (1〜3) |
| `n_measures` | `int` | 小節数 |

---

## 設計ポイント

### 量子化グリッド
- 16分音符 (16th note) 単位でノートを配置
- `subdivisions_per_measure = time_signature.numerator * (16 // time_signature.denominator)` で計算
- 各ノートは最寄りのグリッドスロットに割り当てられる

### トラック構成
| トラック # | 名前 | チャンネル | 楽器 |
|---|---|---|---|
| 1 | Guitar | 1 | プログラム 25 (Acoustic Guitar) |
| 2 | Bass | 2 | プログラム 33 (Electric Bass) |
| 3 | Drums | 10 | パーカッション |

### ドラムマッピング
各ドラムタイプを個別の弦番号に割り当て、`writeNotes` の stringFlags ビット競合を回避:

| ドラムタイプ | 弦番号 | MIDI ノート |
|---|---|---|
| Kick | 1 | 36 |
| Snare | 2 | 38 |
| Hi-Hat | 3 | 42 |
| Unknown | 2 | (Snare 扱い) |

### ギター/ベース チューニング
- ギター: E4 B3 G3 D3 A2 E2（標準6弦）
- ベース: G2 D2 A1 E1（標準4弦）
- 各 MIDI ピッチから `midi - string_open_midi = fret` でフレット番号を算出
- フレット 0〜24 の範囲で弦を選択（一番フレットが小さい弦を優先）

---

## PyGuitarPro 既知バグ対策

### 1. GP5 writer/reader 順序不一致
- **症状**: `.gp5` で保存・読み込みすると Beat データが壊れる
- **対策**: **必ず `.gp4` 拡張子を使用する**（GP4 は writer/reader が整合）

### 2. `Beat.status` デフォルト = `BeatStatus.empty`
- **症状**: デフォルトのまま保存すると 0 ティックのビートになり全ビートが position 960 に積み重なる
- **対策**: `Beat(voice, start=tick, duration=d, status=BeatStatus.normal)` で明示指定

### 3. `Note.type` デフォルト = `NoteType.rest`
- **症状**: ノートが rest として扱われ音が出ない
- **対策**: `Note(beat=b, value=fret, ..., type=NoteType.normal)` で明示指定

### 4. 同一弦への複数 Note
- **症状**: 同じ弦に 2 Note を割り当てると stringFlags のビットが 1 つしか立たず 2 個書き出されるが 1 個しか読めない → ファイル壊れ
- **対策**: 各弦には 1 Beat 内で最大 1 Note しか割り当てない（ドラムは弦番号を種類別に分散）

---

## 依存関係

```python
import guitarpro  # PyGuitarPro>=0.10
from core.drum_analyzer import DrumAnalysisResult
from core.pitch_analyzer import TabResult
```

---

## テスト済み動作

```
tracks: 3, measures: 71, size: 18,988 bytes
[1] Guitar  perc=False  notes=580
[2] Bass    perc=False  notes=542
[3] Drums   perc=True   notes=483
FULL GP4 roundtrip OK!
```
