
from item40.domain import JobRequest
from item40.exports import save_result
from item40.storage import Store


def completed(store, source, text):
    request = JobRequest(source=source)
    store.add(request)
    store.update(request.id, status="completed", transcript=text)
    return request.id


def test_duplicate_names_and_edits_do_not_overwrite_other_results(tmp_path):
    store = Store(tmp_path / "store.sqlite3")
    directory = tmp_path / "Тексты"
    store.set_setting("output_dir", str(directory))
    first = completed(store, "C:/one/запись.m4a", "Первая запись.")
    second = completed(store, "C:/two/запись.m4a", "Вторая запись.")
    first_path, second_path = save_result(store, first), save_result(store, second)
    assert first_path != second_path
    assert first_path.name == "запись.txt"
    assert second_path.name == "запись_2.txt"
    store.update(first, transcript="Исправленный текст.")
    assert save_result(store, first) == first_path
    assert first_path.read_text(encoding="utf8") == "Исправленный текст."
    assert second_path.read_text(encoding="utf8") == "Вторая запись."
    assert not list(directory.glob("*.tmp"))
    store.close()


def test_changed_folder_applies_to_new_results(tmp_path):
    store = Store(tmp_path / "store.sqlite3")
    store.set_setting("output_dir", str(tmp_path / "old"))
    old = completed(store, "old.m4a", "Текст.")
    old_path = save_result(store, old)
    store.set_setting("output_dir", str(tmp_path / "new"))
    new = completed(store, "new.m4a", "Новый текст.")
    assert save_result(store, new).parent == tmp_path / "new"
    store.update(old, transcript="Правка.")
    assert save_result(store, old) == old_path
    assert old_path.read_text(encoding="utf8") == "Правка."
    store.close()


def test_unwritable_output_keeps_transcription_and_records_error(tmp_path):
    store = Store(tmp_path / "store.sqlite3")
    blocked = tmp_path / "file"
    blocked.write_text("existing")
    store.set_setting("output_dir", str(blocked))
    job_id = completed(store, "test.m4a", "Результат.")
    assert save_result(store, job_id) is None
    job = store.get(job_id)
    assert job["status"] == "completed"
    assert job["transcript"] == "Результат."
    assert "Не удалось сохранить TXT" in job["output_error"]
    assert blocked.read_text() == "existing"
    store.set_setting("output_dir", str(tmp_path / "fixed"))
    assert save_result(store, job_id).is_file()
    assert not store.get(job_id)["output_error"]
    store.close()


def test_existing_external_file_is_not_overwritten(tmp_path):
    store = Store(tmp_path / "store.sqlite3")
    store.set_setting("output_dir", str(tmp_path))
    existing = tmp_path / "audio.txt"
    existing.write_text("Keep this", encoding="utf8")
    job_id = completed(store, "audio.m4a", "Текст.")
    assert save_result(store, job_id) == tmp_path / "audio_2.txt"
    assert existing.read_text(encoding="utf8") == "Keep this"
    store.close()
