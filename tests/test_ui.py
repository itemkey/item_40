from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest

from item40.domain import JobRequest
from item40.jobs import JobManager
from item40.storage import Store
from item40.ui.theme import STYLE
from item40.ui.window import MainWindow


def make_window(qtbot, tmp_path):
    store = Store(tmp_path / "test.sqlite3")
    store.set_setting("output_dir", str(tmp_path / "output"))
    manager = JobManager(store, tmp_path)
    window = MainWindow(store, manager, tmp_path)
    window.setStyleSheet(STYLE)
    qtbot.addWidget(window)
    window.show()
    return window


def test_edit_is_saved_when_switching_jobs_and_export_is_enabled(qtbot, tmp_path):
    window = make_window(qtbot, tmp_path)
    page = window.tool_views["audio.transcribe"]
    first, second = JobRequest(source="first.m4a"), JobRequest(source="second.m4a")
    for job in (first, second):
        window.store.add(job)
        window.store.update(job.id, status="completed", transcript="Исходный текст.")
    page.refresh()
    page.select(first.id)
    page.editor.setPlainText("Исправленный текст.")
    page.select(second.id)
    assert window.store.get(first.id)["transcript"] == "Исправленный текст."
    page.select(first.id)
    assert page.editor.toPlainText() == "Исправленный текст."
    assert page.export_button.isEnabled()
    assert page.copy_button.isEnabled()
    window.close()


def test_catalog_navigation_and_no_results(qtbot, tmp_path):
    window = make_window(qtbot, tmp_path)
    QTest.mouseClick(window.nav_buttons["catalog"][0], Qt.MouseButton.LeftButton)
    window.catalog.search.setText("несуществующий инструмент")
    assert window.catalog.no_results.isVisible()
    window.catalog.search.setText("аудио")
    assert not window.catalog.no_results.isVisible()
    window.open_tool("audio.transcribe")
    assert window.stack.currentWidget() is window.tool_views["audio.transcribe"]
    window.close()


def test_add_multiple_files_and_cancel_queued_job(qtbot, tmp_path):
    window = make_window(qtbot, tmp_path)
    page = window.tool_views["audio.transcribe"]
    paths = [tmp_path / "запись.m4a", tmp_path / "lecture.flac"]
    for path in paths:
        path.write_bytes(b"placeholder")
    page.add_files([str(path) for path in paths])
    assert len(window.store.pending()) == 2
    selected = page.selected_id
    page.cancel_selected()
    assert window.store.get(selected)["status"] == "cancelled"
    window.close()


def test_primary_action_stays_visible_in_small_window(qtbot, tmp_path):
    window = make_window(qtbot, tmp_path)
    window.resize(1080, 760)
    page = window.tool_views["audio.transcribe"]
    qtbot.wait(50)
    bottom = page.run_button.mapTo(window, QPoint(0, page.run_button.height())).y()
    assert bottom < window.height() - window.statusBar().height()
    assert page.run_button.visibleRegion().boundingRect().height() == page.run_button.height()
    window.close()


def test_remove_multiple_sources_persists_and_keeps_files(qtbot, tmp_path):
    window = make_window(qtbot, tmp_path)
    page = window.tool_views["audio.transcribe"]
    paths = [tmp_path / "one.m4a", tmp_path / "two.m4a"]
    for path in paths:
        path.write_bytes(b"original")
    page.add_files([str(path) for path in paths])
    ids = [row["id"] for row in window.store.jobs()]
    page.list.selectAll()
    page.remove_selected()
    assert page.list.count() == 0
    assert not page.selected_id
    assert page.editor.toPlainText() == ""
    assert not window.store.pending()
    assert all(window.store.get(job_id)["status"] == "cancelled" for job_id in ids)
    assert all(path.read_bytes() == b"original" for path in paths)
    window.close()
    store = Store(tmp_path / "test.sqlite3")
    assert not store.source_jobs()
    assert len(store.jobs()) == 2
    store.close()


def test_hidden_result_opens_from_history_and_saves_edits(qtbot, tmp_path):
    window = make_window(qtbot, tmp_path)
    page = window.tool_views["audio.transcribe"]
    job = JobRequest(source="meeting.m4a")
    window.store.add(job)
    window.store.update(job.id, status="completed", transcript="Результат.")
    page.refresh()
    page.select(job.id)
    page.remove_selected()
    assert not window.store.source_jobs()
    window.open_job(job.id)
    assert page.editor.toPlainText() == "Результат."
    assert page.list.count() == 0
    page.editor.setPlainText("Исправление.")
    page.flush_edit()
    output = window.store.get(job.id)["output_path"]
    from pathlib import Path
    assert Path(output).read_text(encoding="utf8") == "Исправление."
    window.close()


def test_output_directory_setting_and_save_dialog(qtbot, tmp_path, monkeypatch):
    window = make_window(qtbot, tmp_path)
    target = tmp_path / "Мои тексты"
    assert window.settings.set_output_directory(str(target))
    assert window.store.setting("output_dir") == str(target.resolve())
    page = window.tool_views["audio.transcribe"]
    job = JobRequest(source="meeting.m4a")
    window.store.add(job)
    window.store.update(job.id, status="completed", transcript="Текст.")
    page.refresh()
    page.select(job.id)
    from unittest.mock import Mock
    dialog = Mock(return_value=("", ""))
    monkeypatch.setattr("item40.ui.audio_page.QFileDialog.getSaveFileName", dialog)
    page.export()
    assert dialog.call_args.args[2] == str(target / "meeting.txt")
    window.close()
