# core/exporter.py — 仕様書

> **更新ルール**: `core/exporter.py` を変更したら必ずこのファイルを更新する。

---

## 1. 責務

TAB テキストを PDF ファイルとして保存する。  
旧 `main_gui.py` 内のインライン PDF 処理をモジュールとして分離したもの。

---

## 2. 公開 API

### `export_pdf(text: str, save_path: str) -> None`

| 引数 | 型 | 説明 |
|---|---|---|
| `text` | `str` | 表示中の TAB テキスト（絵文字・日本語含む可） |
| `save_path` | `str` | 保存先パス（`.pdf` 拡張子を付けること） |

**戻り値**: なし  
**例外**: `fpdf` が書き込みに失敗した場合は例外を上位に伝播させる（呼び出し側でキャッチ）

---

## 3. 処理フロー

```
text (UTF-8 任意文字列)
  ↓
re.sub(r"[^\x00-\x7F]+", "", text)  → ASCII のみに絞る
  ↓
FPDF()
  set_auto_page_break(True, margin=15)
  add_page()
  set_font("Courier", size=9)        ← 等幅フォント（TAB 桁揃え）
  ↓
改行で分割して multi_cell() で書き込み（自動改ページ対応）
  ↓
pdf.output(save_path)
```

---

## 4. フォント方針

- 組み込みフォント `Courier` を使用する
- OS 固有パスのフォントファイルを **絶対に指定しない**
  - 理由: Windows / Mac / Linux いずれでも動作させるため

---

## 5. 非 ASCII 文字の扱い

- 絵文字・日本語は `_NON_ASCII` 正規表現で除去してから PDF に書き込む
- TAB テキスト本体は ASCII のみで構成されているため情報損失はない

---

## 6. 依存ライブラリ

- `fpdf` — PDF 生成

**禁止**: `PyQt5` など UI 系ライブラリの import

---

## 7. 変更履歴

| 日付 | 変更内容 |
|---|---|
| 2026-04-26 | 初版。`main_gui.py` から分離、等幅フォント・自動改ページ対応 |
