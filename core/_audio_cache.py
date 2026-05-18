"""
core/_audio_cache.py
─────────────────────────────────────────────────────────────────────────────
スレッドセーフな音声ファイルキャッシュ。

chord_analyzer と pitch_analyzer は同じ音源を sr=None でロードするため、
同一 (path, sr) の組み合わせを 1 回のロードで共用できる。

最大 MAX_ENTRIES エントリを LRU で保持。典型的な使用 (1 ファイル解析) では
メモリ増加なし。新しいファイルを選択すれば古いエントリは自動で押し出される。
"""
from __future__ import annotations

import threading
from collections import OrderedDict
from typing import Optional, Tuple

import numpy as np

MAX_ENTRIES = 3   # 保持する (path, sr) キーの最大数
_cache: OrderedDict[Tuple[str, Optional[int]], Tuple[np.ndarray, int]] = OrderedDict()
_lock = threading.Lock()


def load(path: str, sr: Optional[int] = None) -> Tuple[np.ndarray, int]:
    """
    音声ファイルをロードし結果をキャッシュする（スレッドセーフ）。

    同じ (path, sr) が既にキャッシュされていれば即座に返す。
    """
    key = (path, sr)
    with _lock:
        if key in _cache:
            _cache.move_to_end(key)   # LRU 更新
            return _cache[key]

    import librosa
    y, actual_sr = librosa.load(path, sr=sr, mono=True, dtype=np.float32)

    with _lock:
        _cache[key] = (y, actual_sr)
        _cache.move_to_end(key)
        while len(_cache) > MAX_ENTRIES:
            _cache.popitem(last=False)  # 最も古いエントリを削除

    return y, actual_sr


def clear() -> None:
    """キャッシュ全体を破棄する（新しいファイルを選択した際に呼ぶ）。"""
    with _lock:
        _cache.clear()
