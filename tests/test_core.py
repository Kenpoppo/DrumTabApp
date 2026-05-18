"""
Core モジュールのユニットテスト。

実行:
    QT_QPA_PLATFORM=offscreen python -m pytest tests/ -v

依存: requirements-ci.txt (PyQt5 / tensorflow / basic-pitch は不要)
"""
from __future__ import annotations

import os
import sys
import threading

import numpy as np
import pytest
import scipy.io.wavfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ─── 共通ヘルパー ──────────────────────────────────────────────────────────────

def _make_sine_wav(path: str, sr: int = 22050,
                   freq: float = 440.0, duration: float = 2.0) -> str:
    t = np.linspace(0, duration, int(sr * duration), endpoint=False)
    y = (0.5 * np.sin(2 * np.pi * freq * t) * 32767).astype(np.int16)
    scipy.io.wavfile.write(path, sr, y)
    return path


def _make_pulse_wav(path: str, sr: int = 22050,
                    bpm: float = 120.0, duration: float = 4.0) -> str:
    """BPM に合ったパルス列 WAV を生成する（BPM 推定テスト用）。"""
    n = int(sr * duration)
    y = np.zeros(n, dtype=np.float32)
    beat_samples = int(60.0 / bpm * sr)
    for i in range(0, n - 100, beat_samples):
        y[i : i + 100] = 1.0
    scipy.io.wavfile.write(path, sr, (y * 32767).astype(np.int16))
    return path


# ─── AnalysisSession ──────────────────────────────────────────────────────────

class TestAnalysisSession:
    def test_file_not_found(self):
        from core.analysis_session import AnalysisSession
        with pytest.raises(FileNotFoundError):
            AnalysisSession("/nonexistent_file_xyz_abc.wav")

    def test_audio_native_shape(self, tmp_path):
        from core.analysis_session import AnalysisSession
        path = _make_sine_wav(str(tmp_path / "sine.wav"))
        session = AnalysisSession(path)
        y, sr = session.audio_native
        assert y.ndim == 1
        assert len(y) > 0
        assert sr > 0

    def test_audio_22k_sr(self, tmp_path):
        from core.analysis_session import AnalysisSession
        path = _make_sine_wav(str(tmp_path / "sine.wav"), sr=44100)
        session = AnalysisSession(path)
        _, sr = session.audio_22k
        assert sr == 22050

    def test_hpss_native_shapes_match(self, tmp_path):
        from core.analysis_session import AnalysisSession
        path = _make_sine_wav(str(tmp_path / "sine.wav"))
        session = AnalysisSession(path)
        y_harm, y_perc = session.hpss_native
        y, _ = session.audio_native
        assert y_harm.shape == y.shape
        assert y_perc.shape == y.shape

    def test_bpm_in_range(self, tmp_path):
        from core.analysis_session import AnalysisSession
        path = _make_pulse_wav(str(tmp_path / "pulse.wav"), bpm=120.0)
        session = AnalysisSession(path)
        bpm = session.bpm
        assert 60.0 <= bpm <= 200.0

    def test_lazy_called_once(self, tmp_path):
        from core.analysis_session import AnalysisSession
        path = _make_sine_wav(str(tmp_path / "sine.wav"))
        session = AnalysisSession(path)
        call_count = [0]

        def fn():
            call_count[0] += 1
            return "value"

        session._lazy("test_key", fn)
        session._lazy("test_key", fn)
        assert call_count[0] == 1

    def test_lazy_thread_safety(self, tmp_path):
        from core.analysis_session import AnalysisSession
        path = _make_sine_wav(str(tmp_path / "sine.wav"))
        session = AnalysisSession(path)
        call_count = [0]
        barrier = threading.Barrier(4)

        def fn():
            call_count[0] += 1
            return "value"

        def worker():
            barrier.wait()
            session._lazy("thread_key", fn)

        threads = [threading.Thread(target=worker) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert call_count[0] == 1

    def test_session_properties_cached(self, tmp_path):
        from core.analysis_session import AnalysisSession
        path = _make_sine_wav(str(tmp_path / "sine.wav"))
        session = AnalysisSession(path)
        y1, sr1 = session.audio_native
        y2, sr2 = session.audio_native
        assert y1 is y2  # same object — not recomputed


# ─── pitch_analyzer ───────────────────────────────────────────────────────────

class TestPitchAnalyzer:
    def test_tab_result_dataclass(self):
        from core.pitch_analyzer import TabResult
        r = TabResult(instrument="guitar", tab_text="test", note_count=5, bpm=120.0)
        assert r.instrument == "guitar"
        assert r.note_count == 5
        assert r.bpm == 120.0
        assert r.timed_notes == []

    def test_choose_string_guitar_open_e(self):
        from core.pitch_analyzer import _choose_string, _TUNINGS
        tuning = _TUNINGS["guitar"]
        result = _choose_string(40, tuning, None, None, "guitar")  # MIDI 40 = E2
        assert result is not None
        string_idx, fret = result
        assert 0 <= fret <= 24

    def test_choose_string_out_of_range(self):
        from core.pitch_analyzer import _choose_string, _TUNINGS
        tuning = _TUNINGS["guitar"]
        result = _choose_string(10, tuning, None, None, "guitar")  # too low
        assert result is None

    def test_analyze_guitar_returns_tab_result(self, tmp_path):
        from core.pitch_analyzer import analyze, TabResult
        path = _make_sine_wav(str(tmp_path / "sine.wav"))
        result = analyze(path, "guitar")
        assert isinstance(result, TabResult)
        assert result.instrument == "guitar"
        assert isinstance(result.tab_text, str)
        assert len(result.tab_text) > 0
        assert result.bpm > 0

    def test_analyze_bass_returns_tab_result(self, tmp_path):
        from core.pitch_analyzer import analyze, TabResult
        path = _make_sine_wav(str(tmp_path / "sine.wav"), freq=110.0)  # A2
        result = analyze(path, "bass")
        assert isinstance(result, TabResult)
        assert result.instrument == "bass"

    def test_analyze_unknown_instrument_raises(self, tmp_path):
        from core.pitch_analyzer import analyze
        path = _make_sine_wav(str(tmp_path / "sine.wav"))
        with pytest.raises(ValueError):
            analyze(path, "banjo")

    def test_analyze_with_session(self, tmp_path):
        from core.analysis_session import AnalysisSession
        from core.pitch_analyzer import analyze
        path = _make_sine_wav(str(tmp_path / "sine.wav"))
        session = AnalysisSession(path)
        r_guitar = analyze(session, "guitar")
        r_bass = analyze(session, "bass")
        assert r_guitar.bpm == r_bass.bpm  # same session → same BPM


# ─── drum_analyzer ────────────────────────────────────────────────────────────

class TestDrumAnalyzer:
    def test_analyze_returns_result(self, tmp_path):
        from core import drum_analyzer
        path = _make_sine_wav(str(tmp_path / "sine.wav"))
        result = drum_analyzer.analyze(path)
        assert hasattr(result, "bpm")
        assert hasattr(result, "hits")
        assert result.bpm > 0

    def test_analyze_with_session(self, tmp_path):
        from core.analysis_session import AnalysisSession
        from core import drum_analyzer
        path = _make_sine_wav(str(tmp_path / "sine.wav"))
        session = AnalysisSession(path)
        result = drum_analyzer.analyze(session)
        assert result.bpm > 0

    def test_to_text_contains_bpm(self, tmp_path):
        from core import drum_analyzer
        path = _make_sine_wav(str(tmp_path / "sine.wav"))
        result = drum_analyzer.analyze(path)
        text = drum_analyzer.to_text(result)
        assert isinstance(text, str)
        assert len(text) > 0
        assert "BPM" in text

    def test_drum_hit_counts(self, tmp_path):
        from core import drum_analyzer
        path = _make_pulse_wav(str(tmp_path / "pulse.wav"), bpm=120.0, duration=4.0)
        result = drum_analyzer.analyze(path)
        assert result.onset_count >= 0
        assert result.kick_count + result.snare_count + result.hihat_count == result.onset_count

    def test_session_shared_bpm(self, tmp_path):
        from core.analysis_session import AnalysisSession
        from core import drum_analyzer
        from core.pitch_analyzer import analyze as pitch_analyze
        path = _make_sine_wav(str(tmp_path / "sine.wav"))
        session = AnalysisSession(path)
        drum_result = drum_analyzer.analyze(session)
        pitch_result = pitch_analyze(session, "guitar")
        assert drum_result.bpm == pitch_result.bpm


# ─── _audio_cache ─────────────────────────────────────────────────────────────

class TestAudioCache:
    def test_clear_does_not_raise(self):
        from core._audio_cache import clear
        clear()

    def test_load_returns_array(self, tmp_path):
        from core._audio_cache import load, clear
        clear()
        path = _make_sine_wav(str(tmp_path / "sine.wav"), sr=22050)
        y, sr = load(path, sr=22050)
        assert isinstance(y, np.ndarray)
        assert y.ndim == 1
        assert sr == 22050
        clear()

    def test_load_cached_same_object(self, tmp_path):
        from core._audio_cache import load, clear
        clear()
        path = _make_sine_wav(str(tmp_path / "sine.wav"), sr=22050)
        y1, _ = load(path, sr=22050)
        y2, _ = load(path, sr=22050)
        assert y1 is y2
        clear()
