# DrumTabApp — Copilot Instructions
<!-- このファイルはリポジトリをクローンしたすべての PC で GitHub Copilot に自動的に読み込まれます。 -->
<!-- プロンプトを受け取る前に必ずこのファイルを参照し、以下のルールを遵守してください。 -->

---

## 1. プロジェクト概要

音源ファイル（MP3 / WAV）からドラム・ギター・ベースのタブ譜を自動生成する
デスクトップアプリケーション（Python + PyQt5）。

---

## 2. ディレクトリ構成と責務

```
DrumTabApp/
├── core/                    # ビジネスロジック層（UI を一切持たない）
│   ├── drum_analyzer.py     # ドラム解析の唯一の実装 (HPSS + onset_detect)
│   ├── pitch_analyzer.py    # ギター/ベース TAB の唯一の実装 (HPSS + piptrack)
│   └── exporter.py          # PDF エクスポート
├── ui/
│   └── main_window.py       # PyQt5 ウィンドウ（ロジックを持たず core を呼ぶだけ）
├── main.py                  # エントリポイント (python main.py)
├── docs/                    # 設計・機能ドキュメント（実装変更時に更新必須）
│   ├── architecture.md
│   ├── core/
│   │   ├── drum_analyzer.md
│   │   ├── pitch_analyzer.md
│   │   └── exporter.md
│   └── ui/
│       └── main_window.md
└── .github/
    └── copilot-instructions.md  # 本ファイル
```

> **旧ファイル群**（`drum_analyzer.py`, `tab_generator.py`, `attack_time_analysis.py`,
> `drum_sheet_generator.py`, `main_gui.py`）は後方互換のため残存するが、
> **新規機能追加・修正はすべて `core/` と `ui/` に行う。旧ファイルは触らない。**

---

## 3. 設計ルール（厳守）

### 3-1. 層間の依存方向
```
ui/ → core/   のみ許可
core/ → ui/   禁止
旧ファイル → core/   禁止（逆方向も禁止）
```

### 3-2. core/ のルール
- 各モジュールは **データクラスを戻り値** として返す（生文字列を返さない）
- `import matplotlib` や `PyQt5` など UI 系ライブラリを `core/` に持ち込まない
- 音声読み込みは常に `sr=22050, mono=True, dtype=np.float32` で統一
- HPSS は必ずかける（ドラム解析 → パーカッシブ、ピッチ解析 → ハーモニック）
- 定数（SR, HOP_LENGTH, N_FFT 等）はモジュール上部にまとめる

### 3-3. ui/ のルール
- 全解析処理は `_Worker(QThread)` 経由で実行する（メインスレッドブロック禁止）
- 解析中はボタンを `setEnabled(False)` にする
- エラーは `error` シグナルでキャッチして画面表示する（サイレントクラッシュ禁止）
- TAB 表示エリアのフォントは `Courier New`（等幅）を維持する

### 3-4. PDF エクスポート
- フォントは `Courier`（組み込み等幅）を使用する
- Mac/Windows 固定パスのフォントファイルを指定しない

---

## 4. ドキュメント更新ルール（最重要）

**実装を変更した場合、対応する `docs/` ファイルを必ず同時に更新する。**

| 変更したファイル | 更新が必要なドキュメント |
|---|---|
| `core/drum_analyzer.py` | `docs/core/drum_analyzer.md` + `docs/architecture.md` |
| `core/pitch_analyzer.py` | `docs/core/pitch_analyzer.md` + `docs/architecture.md` |
| `core/exporter.py` | `docs/core/exporter.md` |
| `ui/main_window.py` | `docs/ui/main_window.md` |
| パッケージ構成の変更 | `docs/architecture.md` + 本ファイルの「2. ディレクトリ構成」 |

更新しなかった場合はプルリクエストを **承認しない**。

---

## 5. 技術スタック

| 用途 | ライブラリ |
|---|---|
| 音声読み込み | `librosa` |
| HPSS（音源分離） | `librosa.effects.hpss` |
| オンセット検出 | `librosa.onset.onset_detect` |
| ピッチ検出 | `librosa.piptrack` |
| BPM 推定 | `librosa.beat.beat_track` |
| 音源分離（stems） | `spleeter` (`instrument_separator.py`) |
| GUI | `PyQt5` |
| PDF | `fpdf` |

---

## 6. 実行方法

```bash
# 依存インストール
pip install -r requirements.txt

# 起動
python main.py
```

---

## 7. コーディング規約

- Python 3.8+ 対応、`from __future__ import annotations` を全ファイルに記載
- 型ヒントを必ず付ける（`def analyze(path: str) -> DrumAnalysisResult`）
- `print()` デバッグ文を本番コードに残さない（ロガーを使うか削除）
- 1 関数 = 1 責務（分類 / 検出 / 表示を混在させない）
