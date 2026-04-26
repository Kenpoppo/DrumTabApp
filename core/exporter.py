"""
core/exporter.py
─────────────────────────────────────────────────────────────────────────────
PDF エクスポートモジュール。
TAB テキストを等幅フォント (Courier) で PDF に書き出す。

改善点（旧 main_gui.py 内のインライン実装との比較）:
  - クラス内埋め込みの import / インライン処理をモジュールとして分離
  - 等幅フォント使用 → TAB の桁揃えが崩れない
  - multi_cell でページ自動改ページに対応
  - 非 ASCII 文字（絵文字・日本語）を安全に除去してから出力
"""
from __future__ import annotations

import re

from fpdf import FPDF

# ASCII 外の文字を除去するパターン
_NON_ASCII = re.compile(r"[^\x00-\x7F]+")


def export_pdf(text: str, save_path: str) -> None:
    """
    TAB テキストを PDF として保存する。

    Parameters
    ----------
    text      : 表示中の TAB テキスト（絵文字・日本語含む可）
    save_path : 保存先パス（.pdf 拡張子）
    """
    ascii_text = _NON_ASCII.sub("", text)

    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()
    pdf.set_font("Courier", size=9)   # 等幅フォント → TAB 桁揃え

    for line in ascii_text.split("\n"):
        pdf.multi_cell(0, 4, line)

    pdf.output(save_path)
