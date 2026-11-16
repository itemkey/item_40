from item40.jobs import JobManager
from item40.storage import Store


def test_worker_failure_does_not_block_the_next_file(qtbot, tmp_path):
    store = Store(tmp_path / "test.sqlite3")
    manager = JobManager(store, tmp_path)
    paths = [tmp_path / "broken.m4a", tmp_path / "second.m4a"]
    for path in paths:
        path.write_bytes(b"invalid")
    ids = manager.enqueue(paths, "small", "ru", "cpu")
    manager.start()
    qtbot.waitUntil(lambda: all(store.get(job_id)["status"] == "failed" for job_id in ids), timeout=15000)
    assert all("аудио" in store.get(job_id)["error"] for job_id in ids)
    manager.shutdown()
    store.close()


def test_removing_running_job_cancels_it(qtbot, tmp_path):
    import wave
    source = tmp_path / "test.wav"
    with wave.open(str(source), "wb") as stream:
        stream.setnchannels(1)
        stream.setsampwidth(2)
        stream.setframerate(16000)
        stream.writeframes(bytes(32000))
    store = Store(tmp_path / "test.sqlite3")
    manager = JobManager(store, tmp_path)
    job_id = manager.enqueue([str(source)], "small", "ru", "cpu")[0]
    manager.start()
    manager.remove_sources([job_id])
    assert not store.source_jobs()
    qtbot.waitUntil(lambda: store.get(job_id)["status"] == "cancelled", timeout=10000)
    assert source.exists()
    assert manager.active is None
    manager.shutdown()
    store.close()


def test_completed_job_creates_output_file(tmp_path, qtbot):
    from pathlib import Path

    from item40.domain import JobRequest
    store = Store(tmp_path / "test.sqlite3")
    store.set_setting("output_dir", str(tmp_path / "output"))
    manager = JobManager(store, tmp_path)
    job = JobRequest(source="recording.m4a")
    store.add(job)
    store.update(job.id, status="running", transcript="Готовый текст.")
    manager.active = job.id
    manager._finish("completed")
    row = store.get(job.id)
    assert row["status"] == "completed"
    assert Path(row["output_path"]).read_text(encoding="utf8") == "Готовый текст."
    manager.shutdown()
    store.close()
