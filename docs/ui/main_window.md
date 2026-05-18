# ui/main_window.py — 仕様書

> **更新ルール**: `ui/main_window.py` を変更したら必ずこのファイルを更新する。

---

## 1. 責務

ユーザーインターフェースの描画とユーザー操作の受け付け。
ビジネスロジックは **一切持たない**。全解析は `core/` への呼び出しに委譲する。

---

## 2. クラス構成

### `_Worker(QThread)`

| 要素 | 説明 |
| --- | --- |
| コンストラクタ引数 | `fn: Callable[[], str]` — バックグラウンドで実行する関数 |
| シグナル `finished` | `str` — 解析成功時の結果テキスト |
| シグナル `error` | `str` — 例外発生時のエラーメッセージ |

全解析（ドラム・ギター・ベース）は `_Worker` 経由でバックグラウンド実行する。
メインスレッドをブロックしてはならない。

### `MainWindow(QMainWindow)`

アプリのメインウィンドウ。

---

## 3. ウィジェット構成

```text
MainWindow
└── centralWidget (QWidget)
    └── QVBoxLayout
        ├── file_row (QHBoxLayout)
        │   ├── _file_btn   [音源ファイルを選択]
        │   └── _file_label  選択ファイル名
        ├── btn_row (QHBoxLayout)
        │   ├── _all_btn     [⚡ 全解析]   ← 1セッションで全楽器を一括解析
        │   ├── _guitar_btn  [Guitar TAB 生成]
        │   ├── _bass_btn    [Bass TAB 生成]
        │   ├── _drum_btn    [Drum 解析]
        │   └── _export_btn  [PDF エクスポート]
        └── _display (QTextEdit, ReadOnly, Courier New 10pt)
```

---

## 4. 状態遷移

```text
[起動]
  → ファイル未選択: 解析ボタン disabled
  → ファイル選択後: 解析ボタン enabled

[解析ボタン押下]
  → _Worker 起動
  → 全解析ボタン disabled
  → _display に「実行中...」テキスト表示

[_Worker.finished シグナル]
  → _display に結果テキストを表示
  → 解析ボタン enabled
  → StatusBar に「完了」

[_Worker.error シグナル]
  → _display にエラーメッセージ表示
  → 解析ボタン enabled
  → StatusBar に「エラー発生」
```

---

## 5. メソッド一覧

| メソッド | 説明 |
| --- | --- |
| `_setup_ui()` | ウィジェット生成・レイアウト設定 |
| `_select_file()` | ファイル選択ダイアログ表示、`_audio_cache.clear()` で音声キャッシュをリセット |
| `_run_all()` | 1 つの `AnalysisSession` で Drum / Guitar / Bass を一括解析し結果を連結表示 |
| `_run_guitar()` | Guitar TAB 解析を `_launch` 経由で起動（セッション経由） |
| `_run_bass()` | Bass TAB 解析を `_launch` 経由で起動（セッション経由） |
| `_run_drum()` | Drum 解析を `_launch` 経由で起動（セッション経由） |
| `_launch(label, fn)` | `_Worker` を生成・起動する共通ランチャー |
| `_on_done(result)` | `_Worker.finished` のコールバック |
| `_on_error(message)` | `_Worker.error` のコールバック |
| `_export_pdf()` | PDF エクスポートダイアログと `core.exporter` 呼び出し |
| `_set_analysis_enabled(bool)` | 解析ボタン群（`_all_btn` 含む）の有効/無効を一括切替 |

---

## 6. TAB 表示フォント

- フォント: `Courier New`（等幅）
- サイズ: `10pt`
- 変更禁止: TAB の桁揃えが崩れる

---

## 7. core/ との結合

`_Worker` 内の lambda で遅延インポートを使用:

```python
__import__("core.pitch_analyzer", fromlist=["analyze"]).analyze(path, "guitar")
```

これにより:

- アプリ起動時のインポートコストを最小化
- `core/` が存在しない環境でも起動エラーを防止

---

## 8. 変更履歴

| 日付 | 変更内容 |
| --- | --- |
| 2026-04-26 | 初版。汎用 `_Worker` で全解析を非同期化、エラーシグナル追加、QStatusBar 追加 |
| 2026-04-28 | `_select_file()` に `_audio_cache.clear()` を追加。ファイル切替時に音声キャッシュを破棄することで、前の曲のデータが残留しないよう修正 |
| 2026-05-13 | 「⚡ 全解析」ボタン (`_all_btn`) 追加。`_run_all()` は `AnalysisSession` を1つ生成して全 analyzer に渡し、audio/HPSS/BPM の重複計算を完全排除。個別ボタンも `AnalysisSession` 経由に変更 |
