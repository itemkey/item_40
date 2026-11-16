import queue
import threading
from types import SimpleNamespace
from unittest.mock import Mock

import numpy as np
import pytest

from item40.audio import AudioChunk
from item40.domain import JobRequest, format_transcript, job_files, source_label
from item40.storage import Store
from item40.worker import run_job


def test_old_requests_remain_compatible_and_boundaries_form_paragraphs():
    assert JobRequest(**{"source": "old.m4a"}).files == ["old.m4a"]
    assert job_files({"source": "old.m4a", "options": "{}"}) == ["old.m4a"]
    segments = [{"start": 0, "end": 1, "text": "Вторая запись.", "source_index": 0},
                {"start": 1, "end": 2, "text": "Первая запись.", "source_index": 1}]
    assert format_transcript(segments) == "Вторая запись.\n\nПервая запись."


def test_combination_consumes_pending_sources_and_preserves_existing_results(tmp_path):
    store = Store(tmp_path / "test.sqlite3")
    first, second = JobRequest(source="one.m4a"), JobRequest(source="two.m4a")
    store.add(first)
    store.add(second)
    store.update(second.id, status="completed", transcript="Сохранённый результат.")
    group = JobRequest(source="two.m4a", source_files=["two.m4a", "one.m4a"])
    store.combine_sources(group, [first.id, second.id])
    assert store.get(first.id) is None
    assert store.get(second.id)["transcript"] == "Сохранённый результат."
    assert store.get(second.id)["in_sources"] == 0
    assert [job["id"] for job in store.source_jobs()] == [group.id]
    assert job_files(store.get(group.id)) == ["two.m4a", "one.m4a"]
    store.reorder_sources(group.id, ["one.m4a", "two.m4a"])
    assert store.get(group.id)["source"] == "one.m4a"
    assert source_label(store.get(group.id)) == "2 файла · one.m4a"
    store.close()
    reopened = Store(tmp_path / "test.sqlite3")
    assert job_files(reopened.get(group.id)) == ["one.m4a", "two.m4a"]
    reopened.close()


def test_running_source_cannot_be_replaced_by_a_group(tmp_path):
    store = Store(tmp_path / "test.sqlite3")
    job = JobRequest(source="one.m4a")
    store.add(job)
    store.update(job.id, status="running")
    group = JobRequest(source="one.m4a", source_files=["one.m4a", "two.m4a"])
    with pytest.raises(ValueError):
        store.combine_sources(group, [job.id])
    assert store.get(group.id) is None
    assert store.get(job.id)["status"] == "running"
    store.close()


def test_worker_uses_one_model_and_respects_file_order_and_offsets(tmp_path, monkeypatch):
    import item40.audio as audio
    import item40.worker as worker
    monkeypatch.setattr(worker, "ensure_model", Mock(return_value=tmp_path))
    monkeypatch.setattr(audio, "probe_audio", Mock(side_effect=[2.0, 3.0]))

    def chunks(path, cancel):
        size = 3 * 16000 if path == "second.m4a" else 2 * 16000
        yield AudioChunk(np.zeros(size, dtype=np.float32), 0, 0, float("inf"))

    monkeypatch.setattr(audio, "iter_audio_chunks", chunks)
    model = Mock()
    info = SimpleNamespace(language="ru", duration_after_vad=1)
    model.transcribe.side_effect = [
        ([SimpleNamespace(start=0, end=1, text="Вторая запись.", words=None)], info),
        ([SimpleNamespace(start=0, end=1, text="Первая запись.", words=None)], info),
    ]
    constructor = Mock(return_value=model)
    monkeypatch.setattr("faster_whisper.WhisperModel", constructor)
    events = queue.Queue()
    run_job(JobRequest(source="second.m4a", source_files=["second.m4a", "first.m4a"], device="cpu"),
            str(tmp_path), events, threading.Event())
    messages = list(events.queue)
    assert messages[-1]["kind"] == "completed", messages
    constructor.assert_called_once()
    assert all(call.kwargs["language"] is None for call in model.transcribe.call_args_list)
    segments = [event["data"]["segment"] for event in messages if event["kind"] == "segment"]
    assert [seg["text"] for seg in segments] == ["Вторая запись.", "Первая запись."]
    assert [seg["start"] for seg in segments] == [0, 3]
    assert [seg["source_index"] for seg in segments] == [0, 1]
    progress = [event["data"]["progress"] for event in messages if event["kind"] == "progress"]
    assert progress == sorted(progress)
