# core/player.py — 仕様書

> **更新ルール**: `core/player.py` を変更したら必ずこのファイルと `docs/architecture.md` を同時に更新する。

---

## 1. 責務

sounddevice + librosa によるリアルタイム再生エンジン。  
`ui/main_window.py` のプレイヤーパネルから利用される。`core/` の他モジュールには依存しない。

主機能:
- Play / Pause / Stop / シーク
- 再生速度変更 0.25x〜4.0x（ピッチを維持 — librosa time_stretch）
- 音程変更 ±24 半音（librosa pitch_shift）
- A-B ループ（指定区間を繰り返し再生）
- メトロノーム用クリック音生成（`make_click_sound()`）

---

## 2. 公開 API

### `make_click_sound(sr: int = 22050) -> np.ndarray`

880 Hz 正弦波バーストのメトロノーム用クリック音を生成する。

| 戻り値 | 説明 |
|---|---|
| `np.ndarray` (float32) | 長さ 25ms、エクスポネンシャル減衰付きクリック波形 |

### `class AudioPlayer`

| メソッド | 引数 | 説明 |
|---|---|---|
| `load(path)` | `str` | 音声ファイルをロードし現在の速度・ピッチ設定で前処理。**ブロッキング** |
| `rebuild()` | — | 速度・ピッチ設定を再適用。**ブロッキング**。事前に `pause()` すること |
| `play()` | — | 再生開始 |
| `pause()` | — | 一時停止 |
| `stop()` | — | 停止し再生位置を先頭に戻す |
| `seek(sec)` | `float` | 指定時刻にジャンプ |
| `set_speed(speed)` | `float` (0.25–4.0) | 速度を設定。`rebuild()` 呼び出し後に反映 |
| `set_pitch(semitones)` | `int` (-24–+24) | 音程を設定。`rebuild()` 呼び出し後に反映 |
| `set_loop(a_sec, b_sec)` | `float, float` | A-B ループ区間を設定 |
| `clear_loop()` | — | A-B ループを解除 |

| プロパティ | 型 | 説明 |
|---|---|---|
| `position_sec` | `float` | 現在の再生位置（秒） |
| `duration_sec` | `float` | 音声の全長（秒） |
| `is_playing` | `bool` | 再生中かどうか |
| `is_loaded` | `bool` | 音声がロード済みかどうか |
| `speed` | `float` | 現在の再生速度 |
| `pitch` | `int` | 現在の音程シフト（半音） |

---

## 3. 定数

| 定数 | 値 | 説明 |
|---|---|---|
| `SR` | `22050` | サンプリングレート |
| `BLOCKSIZE` | `2048` | sounddevice OutputStream バッファサイズ |

---

## 4. スレッドモデル

| コンテキスト | 実行内容 |
|---|---|
| 呼び出し元スレッド | `load()`, `rebuild()` — ブロッキング処理（UI からは `_Worker` スレッド経由で呼ぶ） |
| sounddevice コールバック | `_cb()` — オーディオスレッドで実行。`threading.Lock` で `_proc` / `_pos` を排他制御 |

> **重要**: `load()` と `rebuild()` は librosa の time_stretch / pitch_shift を含むため数秒かかる場合がある。
> `ui/main_window.py` はこれらを `_Worker(QThread)` 経由でバックグラウンド実行する。

---

## 5. A-B ループ処理

`_cb()` 内でフレーム単位に処理:
1. 現在位置 `pos` が `loop_b` を超えていたら `loop_a` に戻す
2. ループ区間の末尾をまたぐ場合: `lb - pos` フレームを出力後、`la` から残りを出力
3. ループなしでファイル末尾に達した場合: `_playing = False` で自動停止

---

## 6. 依存ライブラリ

- `librosa` — 遅延インポート（`load()` / `rebuild()` 内でのみ使用、起動高速化）
- `sounddevice` — 遅延インポート（`play()` / `_metro_tick()` 内でのみ使用）
- `numpy` — 音声データ処理

**禁止**: `PyQt5` など UI 系ライブラリの import

---

## 7. 変更履歴

| 日付 | 変更内容 |
|---|---|
| 2026-04-28 | 初版。AudioPlayer クラス + make_click_sound() 実装 |
| 2026-05-19 | 仕様書を新規作成（ドキュメント漏れを修正） |
