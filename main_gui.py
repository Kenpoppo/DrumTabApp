import sys
import os
import re
from PyQt5.QtWidgets import QApplication, QMainWindow, QLabel, QPushButton, QTextEdit, QFileDialog, QVBoxLayout, QWidget
from PyQt5.QtCore import QThread, pyqtSignal
from PyQt5.QtGui import QIcon
from fpdf import FPDF
from tab_generator import detect_pitches, generate_tab
from drum_analyzer import analyze_drum

# 📂 ダウンロードディレクトリ設定
downloads_dir = os.path.join(os.getcwd(), 'downloads')

# 🥁 ドラム解析用のスレッドクラス
class DrumAnalyzerThread(QThread):
    result_ready = pyqtSignal(str)  # ✅ 結果を返すためのシグナル

    def __init__(self, audio_path):
        super().__init__()
        self.audio_path = audio_path

    def run(self):
        # ドラム解析を実行して結果をシグナルで送信
        result = analyze_drum(self.audio_path)
        self.result_ready.emit(result)

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()

        # 🖼️ ウィンドウ設定
        self.setWindowTitle("🎸 Sonic Blue Tab Generator")
        self.setGeometry(200, 200, 800, 600)

        # 🌟 ファイル選択ボタン
        self.file_button = QPushButton("📂 音源ファイルを選択", self)
        self.file_button.clicked.connect(self.select_file)

        # 🎸 ギターTAB生成ボタン
        self.guitar_button = QPushButton("🎸 ギターTAB生成", self)
        self.guitar_button.clicked.connect(self.generate_guitar_tab)

        # 🪕 ベースTAB生成ボタン
        self.bass_button = QPushButton("🪕 ベースTAB生成", self)
        self.bass_button.clicked.connect(self.generate_bass_tab)

        # 🥁 ドラム譜生成ボタン
        self.drum_button = QPushButton("🥁 ドラム譜生成", self)
        self.drum_button.clicked.connect(self.generate_drum_tab)

        # 💾 エクスポートボタン
        self.export_button = QPushButton("💾 エクスポート (PDF)", self)
        self.export_button.clicked.connect(self.export_to_pdf)

        # 🖊 TAB表示エリア
        self.tab_display = QTextEdit(self)
        self.tab_display.setReadOnly(True)

        # 📂 選択されたファイルパス
        self.selected_file = None

        # 📋 レイアウト設定
        layout = QVBoxLayout()
        layout.addWidget(self.file_button)
        layout.addWidget(self.guitar_button)
        layout.addWidget(self.bass_button)
        layout.addWidget(self.drum_button)
        layout.addWidget(self.export_button)
        layout.addWidget(self.tab_display)

        container = QWidget()
        container.setLayout(layout)
        self.setCentralWidget(container)

        # 🔄 ドラム解析用スレッド (初期化)
        self.drum_thread = None

    # 📂 ファイル選択処理
    def select_file(self):
        file_path, _ = QFileDialog.getOpenFileName(self, "音源ファイルを選択", downloads_dir, "Audio Files (*.mp3 *.wav *.flac)")
        if file_path:
            self.selected_file = file_path
            self.tab_display.setText(f"📂 選択されたファイル: {os.path.basename(file_path)}")

    # 🎸 ギターTAB生成処理
    def generate_guitar_tab(self):
        if self.selected_file:
            notes = detect_pitches(self.selected_file)
            tab = generate_tab(notes, instrument='guitar')
            self.tab_display.setText("🎸 ギターTAB譜\n" + tab)
        else:
            self.tab_display.setText("⚠️ 音源ファイルを選択してください！")

    # 🪕 ベースTAB生成処理
    def generate_bass_tab(self):
        if self.selected_file:
            notes = detect_pitches(self.selected_file)
            tab = generate_tab(notes, instrument='bass')
            self.tab_display.setText("🪕 ベースTAB譜\n" + tab)
        else:
            self.tab_display.setText("⚠️ 音源ファイルを選択してください！")

    # 🥁 ドラム譜生成処理 (非同期)
    def generate_drum_tab(self):
        if self.selected_file:
            self.tab_display.setText("🥁 ドラム譜を生成中...")
            # 🔄 スレッドを作成して実行
            self.drum_thread = DrumAnalyzerThread(self.selected_file)
            self.drum_thread.result_ready.connect(self.display_drum_tab)
            self.drum_thread.start()
        else:
            self.tab_display.setText("⚠️ 音源ファイルを選択してください！")

    # 🥁 ドラム譜の表示
    def display_drum_tab(self, result):
        self.tab_display.setText("🥁 ドラム譜\n" + result)

    # 📂 PDFエクスポート処理
    def export_to_pdf(self):
        if self.tab_display.toPlainText():
            pdf = FPDF()
            pdf.add_page()
            pdf.set_font('Helvetica', '', 12)

            clean_text = re.sub(r'[^\x00-\x7F]+', '', self.tab_display.toPlainText())

            for line in clean_text.split("\n"):
                pdf.cell(0, 10, line, ln=1)

            save_path, _ = QFileDialog.getSaveFileName(self, "エクスポート先を選択", downloads_dir, "PDF Files (*.pdf)")
            if save_path:
                pdf.output(save_path)
                self.tab_display.setText(f"💾 エクスポート完了: {save_path}")
        else:
            self.tab_display.setText("⚠️ エクスポートするTAB譜がありません！")


# 🚀 アプリ起動
if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec_())
