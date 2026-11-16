import threading
from fractions import Fraction
from types import SimpleNamespace

import av
import numpy as np
import pytest

from item40.audio import AudioChunk, iter_audio_chunks, owned_segments, probe_audio
from item40.downloads import Cancelled


def write_audio(path, codec, container_format=None, seconds=2.5, sample_rate=44100):
    samples = (np.sin(np.arange(int(seconds * sample_rate)) * 2 * np.pi * 440 / sample_rate) * 0.15)
    with av.open(str(path), mode="w", format=container_format) as output:
        stream = output.add_stream(codec, rate=sample_rate)
        stream.layout = "mono"
        if codec == "wmav2":
            stream.bit_rate = 64000
        resampler = av.AudioResampler(format=stream.codec_context.format.name, layout="mono", rate=sample_rate)
        for start in range(0, len(samples), 1024):
            frame = av.AudioFrame.from_ndarray(samples[start:start + 1024].astype(np.float32)[None],
                                               format="fltp", layout="mono")
            frame.sample_rate = sample_rate
            frame.pts = start
            frame.time_base = Fraction(1, sample_rate)
            for encoded_frame in resampler.resample(frame):
                for packet in stream.encode(encoded_frame):
                    output.mux(packet)
        for encoded_frame in resampler.resample(None):
            for packet in stream.encode(encoded_frame):
                output.mux(packet)
        for packet in stream.encode(None):
            output.mux(packet)


@pytest.mark.parametrize(("suffix", "codec", "container_format"), [
    ("m4a", "aac", "mp4"), ("m4a", "alac", "mp4"), ("m4b", "aac", "mp4"),
    ("mp3", "libmp3lame", None), ("wav", "pcm_s16le", None), ("flac", "flac", None),
    ("aac", "aac", "adts"), ("ogg", "libvorbis", "ogg"), ("opus", "libopus", "ogg"),
    ("wma", "wmav2", "asf"), ("aiff", "pcm_s16be", "aiff"), ("caf", "pcm_s16le", "caf"),
])
def test_audio_formats_decode_and_resample(tmp_path, suffix, codec, container_format):
    if codec not in av.codecs_available:
        pytest.skip(f"Encoder {codec} is not included; decoder may still be available")
    path = tmp_path / f"запись.{suffix}"
    rate = 48000 if codec == "libopus" else 44100
    write_audio(path, codec, container_format, sample_rate=rate)
    assert probe_audio(str(path)) > 2
    chunks = list(iter_audio_chunks(str(path), threading.Event()))
    assert len(chunks) == 1
    assert chunks[0].samples.dtype == np.float32
    assert abs(len(chunks[0].samples) / 16000 - 2.5) < 0.1


def test_bounded_windows_and_final_tail(tmp_path):
    path = tmp_path / "long.wav"
    write_audio(path, "pcm_s16le", seconds=8.7)
    chunks = list(iter_audio_chunks(str(path), threading.Event(), core_seconds=2, overlap_seconds=0.5))
    assert len(chunks) == 5
    assert max(len(chunk.samples) for chunk in chunks) <= 40000
    assert chunks[0].owned_start == 0
    assert all(a.owned_end == b.owned_start for a, b in zip(chunks, chunks[1:]))
    assert chunks[-1].owned_end == float("inf")


def test_words_at_window_boundaries_have_single_owner():
    words = [SimpleNamespace(start=0.2, end=0.4, word=" первое"),
             SimpleNamespace(start=0.8, end=1.2, word=" второе")]
    segment = SimpleNamespace(start=0.2, end=1.2, text="первое второе", words=words)
    first = AudioChunk(np.empty(0), 0, 0, 1)
    second = AudioChunk(np.empty(0), 0, 1, float("inf"))
    assert list(owned_segments([segment], first))[0]["text"] == "первое"
    assert list(owned_segments([segment], second))[0]["text"] == "второе"


def test_invalid_and_cancelled_audio(tmp_path):
    invalid = tmp_path / "broken.m4a"
    invalid.write_bytes(b"not audio")
    with pytest.raises(ValueError, match="Не удалось"):
        probe_audio(str(invalid))
    with pytest.raises(ValueError, match="не найден"):
        probe_audio(str(tmp_path / "absent"))
    path = tmp_path / "ok.wav"
    write_audio(path, "pcm_s16le")
    cancel = threading.Event()
    cancel.set()
    with pytest.raises(Cancelled):
        list(iter_audio_chunks(str(path), cancel))
