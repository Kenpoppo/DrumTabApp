# DrumTabApp

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.8%2B-blue?logo=python" />
  <img src="https://img.shields.io/badge/PyQt5-GUI-green" />
  <img src="https://img.shields.io/badge/librosa-0.10-orange" />
  <img src="https://img.shields.io/badge/basic--pitch-Spotify%20AI-blueviolet" />
  <img src="https://img.shields.io/badge/MIDI-MIDIUtil-yellow" />
  <img src="https://img.shields.io/badge/license-MIT-lightgrey" />
</p>

> **音源ファイル（MP3 / WAV）からドラム・ギター・ベースのタブ譜を自動生成するデスクトップアプリ。**  
> Spotify の神経網モデル「basic-pitch」を統合した高精度モードで、音楽ソフト（TuxGuitar 等）で再生可能な MIDI 出力も対応。

---

## 特徴

| 機能 | 詳細 |
|---|---|
| 🥁 ドラムTAB自動生成 | HPSS + onset detect + 3特徴量分類 (Kick/Snare/Hi-Hat) |
| 🎸 ギター/ベースTAB | **高速モード** (piptrack DSP) / **高精度モード** (Spotify basic-pitch 神経網) |
| 🎵 コード進行検出 | Krumhansl-Schmuckler キー検出 + コサイン類似度コードマッチング |
| 📄 標準ASCII TAB記法 | `1e+a` ビートカウント / HH=`x`・SN/BD=`o` / 小節番号 `m.1, m.2…` |
| 🎹 MIDI書き出し | TuxGuitar / DAW 対応 (.mid)。ドラム ch.10、ベース/ギター別チャンネル |
| 📑 PDF書き出し | Courier フォントでそのまま印刷可能 |

---

## スクリーンショット / 出力例

```
──────────────────────────────────────────────────────────
 Drum Tab  |  BPM: 123.0  |  Key: A# Major  |  Kick:298 / Snare:45 / HH:134
──────────────────────────────────────────────────────────

     |m.1                ||m.2                |
     |1e+a|2e+a|3e+a|4e+a||1e+a|2e+a|3e+a|4e+a|
 HH  |x-x-|x-x-|x-x-|x-x-||x-x-|x-x-|x-x-|x-x-|
 SN  |----|o---|----|o---||----|----|o---|----|
 BD  |o---|----|----|----||o---|----|----|----| 

   |m.1                                ||m.2                                |
   |Gm7                                ||Cm7                                |
 G |--------|--------|--------|--------||--------|--------|--------|--------|
 D |--------|--------|--------|--------||--------|--------|--------|--------|
 A |--5-----|---3----|--------|--------||---8----|--------|--------|--------|
 E |--------|--------|--------|--------||--------|--------|--------|--------|
```

---

## アーキテクチャ

```
DrumTabApp/
├── core/                        # ビジネスロジック層（UI 依存なし）
│   ├── drum_analyzer.py         # ドラム解析 (HPSS + onset_detect + 3特徴量分類)
│   ├── pitch_analyzer.py        # ギター/ベース TAB (HPSS + piptrack, 高速)
│   ├── basic_pitch_analyzer.py  # ★ 高精度モード (Spotify basic-pitch 神経網)
│   ├── chord_analyzer.py        # キー検出 + コード進行 (Krumhansl-Schmuckler)
│   ├── midi_exporter.py         # MIDI 書き出し (MIDIUtil)
│   └── exporter.py              # PDF 書き出し (fpdf)
├── ui/
│   └── main_window.py           # PyQt5 GUI (ロジックなし、_Worker スレッド)
├── main.py                      # エントリポイント
└── docs/                        # 設計・仕様ドキュメント
```

### 処理フロー

```
音源ファイル (.mp3/.wav)
    │
    ├─[Spleeter]──→ stems (drums / bass / other)       ← 任意の前処理
    │
    ├─[HPSS]──→ Harmonic + Percussive 分離
    │
    ├─ ドラム解析 ──→ onset_detect → 3特徴量分類 → DrumAnalysisResult
    │
    ├─ ピッチ解析 ─┬─ [高速] piptrack → BPM グリッド量子化 ──→ TabResult
    │              └─ [高精度] basic-pitch CNN → note events ──→ TabResult
    │
    ├─ コード解析 ──→ chroma_cqt → K-S → テンプレートマッチング → ChordAnalysisResult
    │
    └─ エクスポート ─┬─ ASCII TAB テキスト (画面表示)
                     ├─ PDF (.pdf)
                     └─ Standard MIDI (.mid) → TuxGuitar / DAW
```

---

## インストール

### 必要環境
- Python 3.8 – 3.11
- Windows / macOS / Ubuntu

```bash
# リポジトリをクローン
git clone https://github.com/Kenpoppo/DrumTabApp.git
cd DrumTabApp

# 仮想環境を作成して有効化
python -m venv .venv
# Windows:
.venv\Scripts\Activate.ps1
# macOS/Linux:
source .venv/bin/activate

# 依存ライブラリをインストール
pip install -r requirements.txt

# 高精度モード用（任意）
pip install basic-pitch
```

### ffmpeg（必要な場合）

一部の音源形式（m4a等）の読み込みに ffmpeg が必要です。

```bash
# Windows (winget)
winget install ffmpeg

# macOS
brew install ffmpeg

# Ubuntu
sudo apt install ffmpeg
```

---

## 使い方

```bash
python main.py
```

1. 「音源ファイルを選択」でMP3/WAVを選択
2. **Guitar TAB 生成 / Bass TAB 生成 / Drum 解析** のいずれかをクリック
3. 🧠 **高精度モード (basic-pitch)** チェックをONにすると神経網で解析（より正確）
4. 結果を画面で確認後、**PDF エクスポート** または **MIDI 書き出し**

### TuxGuitar での活用

MIDI 書き出しした `.mid` ファイルを TuxGuitar で開くと：
- ドラムトラック (ch.10) → ドラム譜として表示
- ベーストラック (ch.2) → ベース TAB として表示
- ギタートラック (ch.3) → ギター TAB として表示

---

## 解析アルゴリズム詳細

### ドラム解析

| ステップ | 手法 |
|---|---|
| 音源分離 | `librosa.effects.hpss(margin=3.0)` → パーカッシブ成分 |
| オンセット検出 | `onset_detect(delta=0.05, wait=5)` |
| 種別分類 | スペクトル重心 / 低域比率 / 高域比率 の3特徴量ルールベース |

**分類基準:**
- Hi-Hat: 重心 > 5000 Hz OR (重心 > 4000 Hz AND 高域比 > 0.20)
- Kick:   重心 < 1500 Hz OR (重心 < 2500 Hz AND 低域比 > 0.45)
- Snare:  それ以外

### ギター/ベース ピッチ検出

#### 高速モード（デフォルト）— `core/pitch_analyzer.py`

| ステップ | 手法 |
|---|---|
| 倍音抽出 | HPSS → ハーモニック成分 |
| ピッチ検出 | `librosa.piptrack` (stFT ベース) |
| 閾値 | 非ゼロマグニチュードの上位20%（適応的） |

#### 高精度モード — `core/basic_pitch_analyzer.py`

Spotify の [basic-pitch](https://github.com/spotify/basic-pitch) (ICASSP 2022) を統合。

| 項目 | piptrack | basic-pitch |
|---|---|---|
| アルゴリズム | DSP / stFT | 軽量 CNN (神経網) |
| 多声音対応 | ✗ | ✓ |
| onset/offset 精度 | △ | ✓ |
| ベロシティ検出 | ✗ | ✓ |
| 処理速度 | ◎ 高速 | △ 数十秒 |

### コード/キー検出 — `core/chord_analyzer.py`

| 項目 | 手法 |
|---|---|
| クロマ特徴量 | `librosa.feature.chroma_cqt` |
| キー検出 | Krumhansl-Schmuckler プロファイル相関法 (24 調) |
| コード検出 | コサイン類似度 vs 84テンプレート (12ルート × 7種: M/m/7/m7/M7/dim/sus4) |

---

## 既存ソフトとの比較・改善ロードマップ

既存の音楽解析ツールを参照した上で、今後の改善アイデアを挙げる。

### 参照した既存ツール

| ツール | 強み | 参照点 |
|---|---|---|
| [TuxGuitar](https://tuxguitar.app/) | GP5/MIDI 表示・再生 | MIDI ch割り当て規約 |
| [MuseScore](https://musescore.org/) | MusicXML 標準対応 | 楽譜品質の基準 |
| [basic-pitch](https://github.com/spotify/basic-pitch) (Spotify) | 軽量 CNN 多声音検出 | ✅ 高精度モードとして統合済み |
| [CREPE](https://github.com/marl/crepe) | モノフォニック高精度 | 単音楽器への応用 |
| [Demucs](https://github.com/facebookresearch/demucs) (Meta AI) | 高品質音源分離 | Spleeter の上位互換候補 |
| [madmom](https://github.com/CPJKU/madmom) | 確率的ビートトラッキング | 拍子/テンポ精度向上 |

### ロードマップ

#### 精度向上 🎯

- [ ] **Demucs 統合** — Meta AI の高品質音源分離 (`pip install demucs`)。Spleeter より大幅に音質向上。ベース・ギター分離精度がTAB品質に直結。
- [ ] **madmom ビートトラッキング** — 確率的 DBN (Dynamic Bayesian Network) で小節頭・拍子を正確に推定。変拍子楽曲に対応。
- [ ] **CREPE 統合** — モノフォニックボーカル・ソロ楽器向け超高精度ピッチ追跡（CNN, ICASSP 2018）。
- [ ] **ドラム CNN 分類器** — 現在のルールベース → 学習済みモデル（ADTlib / DrumNet など）。Ride / Open HH / Crash を識別。
- [ ] **Viterbi HMM コード追跡** — 現在のフレーム単位コサイン類似度 → Hidden Markov Model でコード遷移を平滑化。

#### 出力フォーマット 📄

- [ ] **MusicXML エクスポート** (`music21`) — MuseScore / Finale / Dorico で読み込み可能。楽譜として完全整形。
- [ ] **GuitarPro 形式 (.gp5)** (`guitarpro` ライブラリ) — TuxGuitar でネイティブ表示。弦番号・フィンガリングまで埋め込み可能。
- [ ] **LilyPond 出力** — プロ品質の楽譜 PDF を自動生成。

#### UX 改善 🖥️

- [ ] **進捗バー** — 解析ステップ（分離→ピッチ→コード→描画）の進捗を QProgressBar で表示。
- [ ] **パラメータパネル** — onset_threshold / frame_threshold をスライダーで調整してリアルタイムプレビュー。
- [ ] **YouTube URL 入力** — `yt-dlp` で直接ダウンロードして解析。
- [ ] **結果キャッシュ** — 同一ファイルの再解析をスキップ（JSONキャッシュ）。

#### 高度機能 🚀

- [ ] **リアルタイム入力** — マイク入力をリアルタイム解析してライブTAB表示。
- [ ] **GPU アクセラレーション** — CUDA / MPS での basic-pitch 高速化。
- [ ] **カポ / チューニング自動検出** — 開放弦ピーク解析でカポポジションを推定。
- [ ] **難易度スコアリング** — フレット分散・BPM・ポリフォニー度合いから TAB 難易度を自動算出。

---

## 依存ライブラリ

| ライブラリ | 用途 |
|---|---|
| `librosa` | 音声読み込み / HPSS / onset / ピッチ / BPM |
| `numpy` | 数値計算 |
| `PyQt5` | GUI |
| `fpdf` | PDF 書き出し |
| `midiutil` | MIDI 書き出し |
| `spleeter` | 音源分離 (2-stem) |
| `basic-pitch` | 高精度ピッチ検出 (Spotify, ICASSP 2022) |

---

## ライセンス

MIT License — © 2024 Kenpoppo
