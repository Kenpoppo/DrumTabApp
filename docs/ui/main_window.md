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

全解析・音声ロード・エフェクト再構築は `_Worker` 経由でバックグラウンド実行する。
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
        │   ├── _file_btn         [音源ファイルを選択]
        │   └── _file_label       選択ファイル名
        ├── btn_row (QHBoxLayout)
        │   ├── _all_btn          [⚡ 全解析]   ← 1セッションで全楽器を一括解析
        │   ├── _guitar_btn       [Guitar TAB 生成]
        │   ├── _bass_btn         [Bass TAB 生成]
        │   ├── _drum_btn         [Drum 解析]
        │   ├── _export_btn       [PDF エクスポート]
        │   ├── _midi_btn         [MIDI 書き出し]  ← 解析完了後に有効化
        │   ├── _gp_btn           [🎸 GP書き出し]  ← 解析完了後に有効化
        │   └── _hq_check         [🧠 高精度モード (basic-pitch)]
        ├── _player_panel (QGroupBox)  ← プレイヤーパネル
        │   ├── ctrl_row (QHBoxLayout)
        │   │   ├── _play_btn     [▶ / ⏸]
        │   │   ├── _stop_btn     [⏹]
        │   │   ├── _prog_slider  再生位置スライダー
        │   │   └── _time_lbl     "m:ss / m:ss"
        │   ├── fx_row (QHBoxLayout)
        │   │   ├── _speed_slider  速度 0.25x〜2.0x
        │   │   ├── _speed_lbl     "1.00x"
        │   │   ├── _pitch_slider  音程 -12〜+12 半音
        │   │   └── _pitch_lbl     "±0"
        │   └── loop_row (QHBoxLayout)
        │       ├── _loop_a_btn   [A 点 セット]
        │       ├── _loop_b_btn   [B 点 セット]
        │       ├── _loop_clr_btn [ループ解除]
        │       ├── _metro_btn    [🥁 メトロノーム] (チェッカブル)
        │       └── _metro_bpm_lbl "BPM: -"
        └── _display (QTextEdit, ReadOnly, Courier New 10pt)
```

---

## 4. 状態遷移

```text
[起動]
  → ファイル未選択: 解析ボタン・プレイヤーボタン disabled

[ファイル選択]
  → 解析ボタン enabled
  → _audio_cache.clear() でキャッシュリセット
  → _load_audio() でバックグラウンド音声ロード開始
  → ロード完了後: プレイヤーボタン enabled

[解析ボタン押下]
  → _Worker 起動
  → 全解析ボタン + MIDI/GP ボタン disabled
  → _display に「実行中...」テキスト表示

[_Worker.finished シグナル]
  → _display に結果テキストを表示
  → 解析ボタン enabled
  → MIDI/GP ボタン enabled (解析結果がある場合)
  → メトロノーム BPM を解析結果から更新
  → StatusBar に「完了」

[_Worker.error シグナル]
  → _display にエラーメッセージ表示
  → 解析ボタン enabled
  → StatusBar に「エラー発生」

[速度/音程スライダーを離す]
  → プレイヤーボタン disabled（rebuild 中）
  → _Worker で AudioPlayer.rebuild() をバックグラウンド実行
  → 完了後: プレイヤーボタン enabled、再生中なら再開
```

---

## 5. メソッド一覧

### 解析系

| メソッド | 説明 |
| --- | --- |
| `_setup_ui()` | ウィジェット生成・レイアウト設定 |
| `_select_file()` | ファイル選択ダイアログ表示、キャッシュクリア、プレイヤーロード開始 |
| `_run_all()` | 1 つの `AnalysisSession` で Drum / Guitar / Bass を一括解析し結果を連結表示 |
| `_run_guitar()` | Guitar TAB 解析を `_launch` 経由で起動（セッション経由） |
| `_run_bass()` | Bass TAB 解析を `_launch` 経由で起動（セッション経由） |
| `_run_drum()` | Drum 解析を `_launch` 経由で起動（セッション経由） |
| `_launch(label, fn)` | `_Worker` を生成・起動する共通ランチャー |
| `_on_done(result)` | `_Worker.finished` のコールバック。MIDI/GP ボタン有効化と BPM 更新も担う |
| `_on_error(message)` | `_Worker.error` のコールバック |
| `_export_pdf()` | PDF エクスポートダイアログと `core.exporter` 呼び出し |
| `_export_midi()` | MIDI エクスポートダイアログと `core.midi_exporter` 呼び出し |
| `_export_gp()` | GP4/GP5 エクスポートダイアログと `core.gp5_exporter` 呼び出し |
| `_set_analysis_enabled(bool)` | 解析ボタン群の有効/無効を一括切替（MIDI/GP ボタンは別制御） |

### プレイヤー系

| メソッド | 説明 |
| --- | --- |
| `_build_player_panel()` | プレイヤーパネル（QGroupBox）を生成してレイアウト設定 |
| `_load_audio()` | 選択中ファイルを `AudioPlayer.load()` でバックグラウンドロード |
| `_on_audio_loaded(dur_str)` | 音声ロード完了コールバック。プレイヤーボタンを有効化し時刻ラベルを更新 |
| `_toggle_play()` | ▶/⏸ ボタン: 再生 ↔ 一時停止を切替 |
| `_stop_playback()` | ⏹ ボタン: 停止し先頭に戻す |
| `_update_pos()` | 100ms タイマーコールバック: プログレスバーと時刻ラベルを更新 |
| `_on_prog_press()` / `_on_prog_release()` | プログレスバーのシーク操作（ドラッグ中は自動更新を停止） |
| `_on_speed_released()` | 速度スライダー離し: `set_speed()` → `_start_fx_worker()` |
| `_on_pitch_released()` | 音程スライダー離し: `set_pitch()` → `_start_fx_worker()` |
| `_start_fx_worker()` | `AudioPlayer.rebuild()` をバックグラウンド実行する |
| `_on_fx_ready(_)` | rebuild 完了コールバック。ボタン再有効化し、必要なら再生再開 |
| `_set_loop_a()` / `_set_loop_b()` | 現在位置を A/B 点としてセット |
| `_try_apply_loop()` | A・B 両点がセットされていたら `AudioPlayer.set_loop()` を呼ぶ |
| `_clear_loop()` | A-B ループを解除 |
| `_toggle_metro(checked)` | メトロノームのオン/オフ切替。BPM を解析結果から取得してタイマー設定 |
| `_metro_tick()` | メトロノームタイマーコールバック: sounddevice でクリック音を再生 |
| `_get_bpm()` | 解析結果から BPM を取得（drum → bass → guitar の優先順位） |
| `_set_player_enabled(bool)` | プレイヤーボタン群の有効/無効を一括切替 |
| `closeEvent(event)` | ウィンドウ終了時: タイマー停止、プレイヤー停止、ワーカー待機 |

---

## 6. 高精度モード (`_hq_check`)

`_hq_check` チェックボックスが ON のとき、ギター/ベース解析に `core.basic_pitch_analyzer` (basic-pitch NN) を使用する。  
OFF のとき（デフォルト）は `core.pitch_analyzer` (piptrack DSP) を使用する。

| モード | モジュール | 速度 | 精度 |
|---|---|---|---|
| 標準 (OFF) | `core.pitch_analyzer` | 高速 | DSP |
| 高精度 (ON) | `core.basic_pitch_analyzer` | 低速 (数十秒) | NN |

---

## 7. TAB 表示フォント

- フォント: `Courier New`（等幅）
- サイズ: `10pt`
- 変更禁止: TAB の桁揃えが崩れる

---

## 8. core/ との結合

`_Worker` 内の lambda で遅延インポートを使用:

```python
__import__("core.pitch_analyzer", fromlist=["analyze"]).analyze(session, "guitar")
```

これにより:

- アプリ起動時のインポートコストを最小化
- `core/` が存在しない環境でも起動エラーを防止

---

## 9. 変更履歴

| 日付 | 変更内容 |
| --- | --- |
| 2026-04-26 | 初版。汎用 `_Worker` で全解析を非同期化、エラーシグナル追加、QStatusBar 追加 |
| 2026-04-28 | `_select_file()` に `_audio_cache.clear()` を追加。ファイル切替時に音声キャッシュを破棄 |
| 2026-05-13 | 「⚡ 全解析」ボタン (`_all_btn`) 追加。`_run_all()` は `AnalysisSession` を1つ生成して全 analyzer に渡し、audio/HPSS/BPM の重複計算を完全排除。個別ボタンも `AnalysisSession` 経由に変更 |
| 2026-05-19 | プレイヤーパネル全体を仕様書に追記（`_build_player_panel`・速度/音程スライダー・A-Bループ・メトロノーム）。`_midi_btn`, `_gp_btn`, `_hq_check` ウィジェットを追記。`_export_midi()`, `_export_gp()`, `closeEvent()` を追記 |
