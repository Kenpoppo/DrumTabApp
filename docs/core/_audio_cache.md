# core/_audio_cache.py — 仕様書

> **更新ルール**: `core/_audio_cache.py` を変更したら必ずこのファイルと `docs/architecture.md` を更新する。

---

## 1. 責務

`chord_analyzer` / `pitch_analyzer` / `basic_pitch_analyzer` が同一音源ファイルを
`sr=None` で重複ロードする問題を解消するスレッドセーフな LRU キャッシュ。

1 ファイル解析の典型フロー（Guitar TAB 生成）では以下の順でロードが発生する。

```text
_run_guitar()
  ├── chord_analyzer.analyze(path)     → librosa.load(path, sr=None)  [1回目]
  └── pitch_analyzer.analyze(path, …)  → librosa.load(path, sr=None)  [2回目・重複]
```

`_audio_cache.load()` に置き換えることで 2 回目以降はキャッシュから即座に返す。

---

## 2. 公開 API

### `load(path: str, sr: int | None = None) -> (np.ndarray, int)`

| 引数 | 型 | 説明 |
| --- | --- | --- |
| `path` | `str` | 音源ファイルパス |
| `sr` | `int \| None` | リサンプリングレート。`None` でネイティブ SR を維持 |

**戻り値**: `(y: np.ndarray, sr: int)` — librosa.load と同じ形式
**スレッドセーフ**: `threading.Lock` による排他制御

### `clear() -> None`

キャッシュ全体を破棄する。`ui/main_window._select_file()` がファイル切替時に呼ぶ。

---

## 3. キャッシュ仕様

| 項目 | 値 |
| --- | --- |
| キーの型 | `(path: str, sr: int \| None)` |
| 最大エントリ数 | `MAX_ENTRIES = 3` |
| 退避ポリシー | LRU（`collections.OrderedDict` で実装） |
| スレッド安全性 | `threading.Lock` で読み書きを排他制御 |

`sr=None` と `sr=22050` は別エントリとして管理されるため、
`chord_analyzer` (sr=None) と `drum_analyzer` (sr=22050) は共有されない。

---

## 4. 依存ライブラリ

- `librosa` — 実際のファイルロード（キャッシュミス時のみ）
- `numpy` — 戻り値の型
- `threading` — Lock（標準ライブラリ）
- `collections.OrderedDict` — LRU 管理（標準ライブラリ）

**禁止**: `PyQt5` など UI 系ライブラリの import

---

## 5. 変更履歴

| 日付 | 変更内容 |
| --- | --- |
| 2026-04-28 | 初版。chord_analyzer / pitch_analyzer / basic_pitch_analyzer の重複ロードを排除するため新設 |
