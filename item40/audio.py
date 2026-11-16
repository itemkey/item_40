from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import av
import numpy as np

from .downloads import check_cancel

SAMPLE_RATE = 16000
CORE_SECONDS = 120
OVERLAP_SECONDS = 3


@dataclass
class AudioChunk:
    samples: np.ndarray
    offset: float
    owned_start: float
    owned_end: float


def probe_audio(path: str) -> float | None:
    if not Path(path).is_file():
        raise ValueError("Файл не найден. Возможно, его переместили или удалили.")
    try:
        with av.open(path) as container:
            if not container.streams.audio:
                raise ValueError("В файле нет аудиодорожки.")
            stream = container.streams.audio[0]
            duration = (float(stream.duration * stream.time_base) if stream.duration is not None
                        else container.duration / av.time_base if container.duration else None)
            return duration if duration and duration > 0 else None
    except av.error.FFmpegError as error:
        raise ValueError("Не удалось прочитать аудио: файл повреждён, защищён или имеет неподдерживаемый кодек.") from error


def iter_audio_chunks(path: str, cancel, core_seconds: float = CORE_SECONDS,
                      overlap_seconds: float = OVERLAP_SECONDS):
    """Decode bounded windows; adjacent windows share a small context region."""
    core = int(core_seconds * SAMPLE_RATE)
    overlap = int(overlap_seconds * SAMPLE_RATE)
    window = core + overlap
    pending = np.empty(window, dtype=np.float32)
    used = 0
    offset = 0
    with av.open(path) as container:
        stream = container.streams.audio[0]
        resampler = av.AudioResampler(format="fltp", layout="mono", rate=SAMPLE_RATE)

        def frames():
            for frame in container.decode(stream):
                check_cancel(cancel)
                yield from resampler.resample(frame)
            yield from resampler.resample(None)

        for frame in frames():
            check_cancel(cancel)
            data = frame.to_ndarray().reshape(-1).astype(np.float32, copy=False)
            position = 0
            while position < len(data):
                size = min(window - used, len(data) - position)
                pending[used:used + size] = data[position:position + size]
                used += size
                position += size
                if used == window:
                    check_cancel(cancel)
                    yield AudioChunk(pending.copy(), offset / SAMPLE_RATE,
                                     (offset + overlap // 2) / SAMPLE_RATE if offset else 0.0,
                                     (offset + core + overlap // 2) / SAMPLE_RATE)
                    pending[:overlap] = pending[core:window]
                    used = overlap
                    offset += core
        # A final context-only tail was already covered by the preceding window.
        if used > (overlap // 2 if offset else 0):
            yield AudioChunk(pending[:used].copy(), offset / SAMPLE_RATE,
                             (offset + overlap // 2) / SAMPLE_RATE if offset else 0.0, float("inf"))


def owned_segments(segments, chunk: AudioChunk):
    """Assign words to exactly one window by the midpoint of their timestamps."""
    for segment in segments:
        words = getattr(segment, "words", None)
        if words:
            retained = [word for word in words
                        if chunk.owned_start <= chunk.offset + (word.start + word.end) / 2 < chunk.owned_end]
            if retained:
                yield {"start": max(0.0, chunk.offset + retained[0].start),
                       "end": chunk.offset + retained[-1].end,
                       "text": "".join(word.word for word in retained).strip()}
        else:
            midpoint = chunk.offset + (segment.start + segment.end) / 2
            if chunk.owned_start <= midpoint < chunk.owned_end and segment.text.strip():
                yield {"start": chunk.offset + segment.start, "end": chunk.offset + segment.end,
                       "text": segment.text.strip()}
