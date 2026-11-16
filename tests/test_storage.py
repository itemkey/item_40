from item40.domain import JobRequest, format_transcript
from item40.storage import Store


def test_edits_options_and_recovery_survive_restart(tmp_path):
    path = tmp_path / "store.sqlite3"
    store = Store(path)
    job = JobRequest(source="C:/Лекции/запись.m4a", model="large-v3", language="ru")
    store.add(job)
    store.set_setting("device", "cpu")
    store.update(job.id, status="running", transcript="Исправленный текст.", edited=1,
                 segments=[{"start": 0, "end": 1, "text": "Текст."}])
    store.close()
    reopened = Store(path)
    saved = reopened.get(job.id)
    assert saved["status"] == "interrupted"
    assert saved["transcript"] == "Исправленный текст."
    assert saved["edited"] == 1
    assert reopened.setting("device") == "cpu"
    reopened.close()


def test_version_one_database_migrates_without_losing_data(tmp_path):
    import sqlite3
    path = tmp_path / "old.sqlite3"
    connection = sqlite3.connect(path)
    connection.executescript("""
        CREATE TABLE jobs (id TEXT PRIMARY KEY, tool_id TEXT, source TEXT, options TEXT, status TEXT,
            progress REAL DEFAULT 0, stage TEXT DEFAULT '', transcript TEXT DEFAULT '',
            segments TEXT DEFAULT '[]', edited INTEGER DEFAULT 0, error TEXT DEFAULT '',
            created_at TEXT, updated_at TEXT);
        INSERT INTO jobs (id,tool_id,source,options,status,transcript,created_at,updated_at)
            VALUES ('old','audio.transcribe','old.m4a','{}','completed','Saved text','date','date');
        PRAGMA user_version=1;
    """)
    connection.close()
    store = Store(path)
    job = store.get("old")
    assert job["transcript"] == "Saved text"
    assert job["in_sources"] == 1
    assert job["output_path"] == ""
    assert store.connection.execute("PRAGMA user_version").fetchone()[0] == 2
    store.close()


def test_legacy_data_directory_is_reused(tmp_path, monkeypatch):
    from item40.paths import data_dir, database_path
    monkeypatch.delenv("ITEM40_DATA_DIR", raising=False)
    monkeypatch.delenv("MASTERSKAYA_DATA_DIR", raising=False)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    assert data_dir() == tmp_path / "item-40"
    legacy = tmp_path / "Masterskaya"
    legacy.mkdir()
    database = legacy / "masterskaya.sqlite3"
    database.touch()
    assert data_dir() == legacy
    assert database_path(legacy) == database


def test_queue_uses_creation_order_and_does_not_retry_failed_jobs(tmp_path):
    store = Store(tmp_path / "store.sqlite3")
    first, second = JobRequest(source="first"), JobRequest(source="second")
    store.add(first)
    store.add(second)
    assert [row["id"] for row in store.pending()] == [first.id, second.id]
    store.update(first.id, status="failed", error="test")
    assert [row["id"] for row in store.pending()] == [second.id]
    store.close()


def test_paragraphs_follow_pauses_without_rewriting_words():
    result = format_transcript([{"start": 0, "end": 2, "text": "  Привет, мир! "},
                                {"start": 2.1, "end": 3, "text": "Это проверка."},
                                {"start": 5, "end": 6, "text": "Новый абзац."}])
    assert result == "Привет, мир! Это проверка.\n\nНовый абзац."


def test_quality_changes_apply_to_waiting_files_only(tmp_path):
    import json
    store = Store(tmp_path / "store.sqlite3")
    waiting, running = JobRequest(source="waiting.m4a"), JobRequest(source="running.m4a")
    store.add(waiting)
    store.add(running)
    store.update(running.id, status="running")
    store.configure_pending("large-v3", "ru", "cuda")
    assert json.loads(store.get(waiting.id)["options"])["model"] == "large-v3"
    assert json.loads(store.get(running.id)["options"])["model"] == "small"
    store.close()
