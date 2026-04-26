"""
core/player.py
─────────────────────────────────────────────────────────────────────────────
聞々ハヤえもん風 オーディオプレイヤー。

主要機能:
  - Play / Pause / Stop / シーク
  - 再生速度変更 0.25x ~ 2.0x（ピッチ維持 — librosa.effects.time_stretch）
  - 音程変更 ±12 半音（librosa.effects.pitch_shift）
  - A-B ループ（区間繰り返し）
  - sounddevice OutputStream でリアルタイムストリーミング再生

設計上の注意:
  - librosa / sounddevice は遅延インポート（起動高速化）
  - time_stretch / pitch_shift は rebuild() で事前処理 → ブロッキング
  - rebuild() はワーカースレッドから呼ぶこと（UI をブロックしない）
  - _cb() はオーディオスレッドから呼ばれる → Lock で排他制御
"""
from __future__ import annotations

import logging
import threading
from typing import Optional

import numpy as np

log = logging.getLogger(__name__)

SR        = 22050   # サンプリングレート
BLOCKSIZE = 2048    # sounddevice バッファサイズ


def make_click_sound(sr: int = SR) -> np.ndarray:
    """メトロノーム用クリック音（880 Hz 正弦波バースト）を生成する。"""
    dur = 0.025
    n   = int(sr * dur)
    t   = np.linspace(0, dur, n, endpoint=False, dtype=np.float32)
    return (np.sin(2 * np.pi * 880.0 * t) * np.exp(-t * 120.0) * 0.6).astype(np.float32)


class AudioPlayer:
    """
    sounddevice + librosa を使ったオーディオプレイヤー。
    再生速度・音程変更・A-B ループをサポート。
    """

    def __init__(self) -> None:
        self._raw:  Optional[np.ndarray] = None   # 元の mono float32
        self._proc: Optional[np.ndarray] = None   # (N, 2) float32 ステレオ処理済み
        self._sr    = SR

        self._speed: float = 1.0   # 再生速度 (0.25 ~ 4.0)
        self._pitch: int   = 0     # 音程シフト (半音) (-24 ~ +24)

        self._pos     = 0
        self._playing = False
        self._lock    = threading.Lock()

        self._loop_a: Optional[int] = None   # ループ開始フレーム (_proc 内)
        self._loop_b: Optional[int] = None   # ループ終了フレーム (_proc 内)

        self._stream = None   # sd.OutputStream

    # ── ロード & ビルド ────────────────────────────────────────────────────────

    def load(self, path: str) -> None:
        """音声ファイルをロードし現在の速度・ピッチ設定で前処理する。ブロッキング。"""
        import librosa as _lr
        log.info("load: %s", path)
        self._stop_stream()
        y, sr = _lr.load(path, sr=SR, mono=True, dtype=np.float32)
        log.debug("load done: samples=%d sr=%d dur=%.1fs", len(y), sr, len(y)/sr)
        with self._lock:
            self._raw     = y
            self._sr      = sr
            self._pos     = 0
            self._playing = False
            self._loop_a  = self._loop_b = None
        self._rebuild()

    def rebuild(self) -> None:
        """速度・ピッチ設定を再適用する。ブロッキング。事前に pause() すること。"""
        self._stop_stream()
        with self._lock:
            self._playing = False
        self._rebuild()

    def _rebuild(self) -> None:
        import librosa as _lr
        if self._raw is None:
            return
        log.debug("rebuild: speed=%.2f pitch=%+d", self._speed, self._pitch)
        y = self._raw.copy()
        if self._pitch != 0:
            y = _lr.effects.pitch_shift(y, sr=self._sr, n_steps=float(self._pitch))
        if self._speed != 1.0:
            y = _lr.effects.time_stretch(y, rate=self._speed)
        proc = np.ascontiguousarray(np.stack([y, y], axis=1).astype(np.float32))
        with self._lock:
            if self._proc is not None and len(self._proc) > 0 and len(proc) > 0:
                ratio = len(proc) / len(self._proc)
                self._pos = min(int(self._pos * ratio), len(proc) - 1)
            self._proc = proc
        log.debug("rebuild done: proc_frames=%d dur=%.1fs", len(proc), len(proc)/self._sr)

    # ── 再生制御 ───────────────────────────────────────────────────────────────

    def play(self) -> None:
        """再生開始。"""
        import sounddevice as _sd
        if self._proc is None:
            log.warning("play() called but nothing loaded")
            return
        self._stop_stream()
        with self._lock:
            if self._pos >= len(self._proc):
                self._pos = 0
            self._playing = True
        self._stream = _sd.OutputStream(
            samplerate=self._sr, channels=2, dtype="float32",
            blocksize=BLOCKSIZE, callback=self._cb,
        )
        self._stream.start()
        log.info("play: pos=%.1fs dur=%.1fs", self._pos/self._sr, self.duration_sec)

    def pause(self) -> None:
        with self._lock:
            self._playing = False
        log.info("pause: pos=%.1fs", self.position_sec)

    def stop(self) -> None:
        self._stop_stream()
        with self._lock:
            self._playing = False
            self._pos = 0
        log.info("stop")

    def seek(self, sec: float) -> None:
        with self._lock:
            if self._proc is None:
                return
            self._pos = max(0, min(int(sec * self._sr), len(self._proc) - 1))

    # ── パラメータ設定 ─────────────────────────────────────────────────────────

    def set_speed(self, speed: float) -> None:
        """速度を設定する。rebuild() を呼ぶまで反映されない。"""
        self._speed = max(0.25, min(4.0, speed))

    def set_pitch(self, semitones: int) -> None:
        """音程を設定する。rebuild() を呼ぶまで反映されない。"""
        self._pitch = max(-24, min(24, int(semitones)))

    def set_loop(self, a_sec: float, b_sec: float) -> None:
        with self._lock:
            self._loop_a = int(a_sec * self._sr)
            self._loop_b = int(b_sec * self._sr)
        log.info("loop set: A=%.2fs B=%.2fs", a_sec, b_sec)

    def clear_loop(self) -> None:
        with self._lock:
            self._loop_a = self._loop_b = None
        log.info("loop cleared")

    # ── プロパティ ─────────────────────────────────────────────────────────────

    @property
    def position_sec(self) -> float:
        return self._pos / self._sr

    @property
    def duration_sec(self) -> float:
        with self._lock:
            return (len(self._proc) / self._sr) if self._proc is not None else 0.0

    @property
    def is_playing(self) -> bool:
        return self._playing

    @property
    def is_loaded(self) -> bool:
        return self._proc is not None

    @property
    def speed(self) -> float:
        return self._speed

    @property
    def pitch(self) -> int:
        return self._pitch

    # ── 内部 ───────────────────────────────────────────────────────────────────

    def _stop_stream(self) -> None:
        s, self._stream = self._stream, None
        if s is not None:
            try:
                s.stop()
                s.close()
                log.debug("stream stopped")
            except Exception as exc:
                log.warning("stream stop error: %s", exc)

    def _cb(self, outdata: np.ndarray, frames: int, time_info, status) -> None:
        """sounddevice OutputStream コールバック（オーディオスレッドで実行）。"""
        with self._lock:
            if not self._playing or self._proc is None:
                outdata[:] = 0
                return

            proc  = self._proc
            total = len(proc)
            la, lb = self._loop_a, self._loop_b
            pos = self._pos

            # ループ境界を越えていたら先頭に戻す
            if la is not None and lb is not None and pos >= lb:
                pos = self._pos = la

            end = pos + frames

            if la is not None and lb is not None:
                # A-B ループ処理
                if end <= lb:
                    outdata[:] = proc[pos:end]
                    self._pos = end
                else:
                    # ループ折り返し
                    f1 = max(0, lb - pos)
                    outdata[:f1] = proc[pos : pos + f1]
                    f2  = frames - f1
                    got = min(f2, total - la)
                    if got > 0:
                        outdata[f1 : f1 + got] = proc[la : la + got]
                    if f1 + got < frames:
                        outdata[f1 + got :] = 0
                    self._pos = la + f2

            elif end >= total:
                # ファイル末尾 → 停止
                avail = total - pos
                if avail > 0:
                    outdata[:avail] = proc[pos:total]
                outdata[max(0, avail) :] = 0
                self._playing = False
                self._pos     = 0

            else:
                outdata[:] = proc[pos:end]
                self._pos  = end
