"""Explicit long-file acceptance check; does not download a model."""
import threading
import tracemalloc
from fractions import Fraction

import av
import numpy as np
import pytest

from item40.audio import iter_audio_chunks, probe_audio


@pytest.mark.integration
def test_two_hours_are_decoded_with_bounded_memory(tmp_path):
    path = tmp_path / "two-hours.flac"
    rate, seconds = 16000, 7200
    with av.open(str(path), "w") as output:
        stream = output.add_stream("flac", rate=rate)
        stream.layout = "mono"
        data = np.zeros((1, rate), dtype=np.int16)
        for second in range(seconds):
            frame = av.AudioFrame.from_ndarray(data, format="s16", layout="mono")
            frame.sample_rate = rate
            frame.pts = second * rate
            frame.time_base = Fraction(1, rate)
            for packet in stream.encode(frame):
                output.mux(packet)
        for packet in stream.encode(None):
            output.mux(packet)
    assert abs(probe_audio(str(path)) - seconds) < 0.01
    tracemalloc.start()
    count = 0
    for chunk in iter_audio_chunks(str(path), threading.Event()):
        assert len(chunk.samples) <= 123 * rate
        count += 1
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    assert count == 60
    assert peak < 40 * 1024 * 1024
