# ドキュメント更新ガイド

このファイルは **実装変更のたびに Copilot（または開発者）が参照する** チェックリストです。

---

## 必須ルール

> 実装を変更した場合、対応するドキュメントを **コードと同じコミット** に含める。
> ドキュメントが更新されていない PR はマージしない。

---

## 変更対象ファイルと更新すべきドキュメント

| 変更したファイル | 更新必須ドキュメント |
|---|---|
| `core/drum_analyzer.py` | `docs/core/drum_analyzer.md` の「処理フロー」「定数」「変更履歴」 + `docs/architecture.md` の「4-1. ドラム解析」 |
| `core/pitch_analyzer.py` | `docs/core/pitch_analyzer.md` の「処理フロー」「定数」「変更履歴」 + `docs/architecture.md` の「4-2. ピッチ解析」 |
| `core/exporter.py` | `docs/core/exporter.md` の「処理フロー」「変更履歴」 |
| `ui/main_window.py` | `docs/ui/main_window.md` の「ウィジェット構成」「状態遷移」「メソッド一覧」「変更履歴」 |
| パッケージ追加 / 削除 | `docs/architecture.md` の「2. パッケージ構成」 + `.github/copilot-instructions.md` の「2. ディレクトリ構成」 |
| 依存ライブラリ追加 | `docs/architecture.md` の「6. 技術スタック」 + `.github/copilot-instructions.md` の「5. 技術スタック」 |

---

## ドキュメント更新チェックリスト（コピーして使う）

```markdown
## ドキュメント更新チェック
- [ ] docs/core/drum_analyzer.md  （drum_analyzer.py を変更した場合）
- [ ] docs/core/pitch_analyzer.md （pitch_analyzer.py を変更した場合）
- [ ] docs/core/exporter.md       （exporter.py を変更した場合）
- [ ] docs/ui/main_window.md      （main_window.py を変更した場合）
- [ ] docs/architecture.md        （データフロー / パッケージ構成を変更した場合）
- [ ] .github/copilot-instructions.md （ディレクトリ構成 / 技術スタックを変更した場合）
```

---

## 各 docs ファイルの構成ルール

### `docs/core/*.md`

| セクション | 内容 |
|---|---|
| 責務 | モジュールが行うこと（1〜3行） |
| 公開 API | 関数シグネチャ・引数・戻り値・例外 |
| データクラス | フィールド定義 |
| 処理フロー | 主要ステップの順序（ASCII フロー図） |
| 定数 | 名前・値・意味（変更時は閾値も更新） |
| 変更履歴 | 日付・変更内容 |

### `docs/ui/main_window.md`

| セクション | 内容 |
|---|---|
| 責務 | UI 層の役割（ビジネスロジックを持たないこと） |
| クラス構成 | クラスとシグナルの一覧 |
| ウィジェット構成 | ウィジェットツリー |
| 状態遷移 | ボタン有効/無効の遷移 |
| メソッド一覧 | 全 public/private メソッドと説明 |
| 変更履歴 | 日付・変更内容 |

---

## Copilot への指示（このファイルを読んだ Copilot へ）

1. 実装ファイルを変更するリクエストを受けた場合、**コード変更と同じターンで対応ドキュメントも更新する**。
2. 新規ファイルを `core/` または `ui/` に追加した場合、`docs/` に対応する `.md` を作成し、`docs/architecture.md` のパッケージ構成も更新する。
3. 変更履歴の日付は変更を行った時点の日付を記入する。
