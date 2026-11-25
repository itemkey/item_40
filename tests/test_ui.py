from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest

from item40.domain import JobRequest
from item40.jobs import JobManager
from item40.storage import Store
from item40.telegram import TOOL_ID as TELEGRAM_TOOL_ID
from item40.telegram import Emoji, EmojiPack
from item40.ui.theme import STYLE
from item40.ui.window import MainWindow
from item40.youtube import TOOL_ID, Stream, Video


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


def test_youtube_cancel_and_send_completed_file_to_transcription(qtbot, tmp_path, monkeypatch):
    window = make_window(qtbot, tmp_path)
    window.open_tool(TOOL_ID)
    page = window.tool_views[TOOL_ID]
    page.directory.setText(str(tmp_path))
    page.load_formats(Video("Тест", 5, [Stream("18", "mp4", "avc1", "aac", 640, 360, 30, 500, None)]), [])
    monkeypatch.setattr(page, "start_task", lambda request: None)

    page.start_download()
    cancelled_folder = page.work_dir
    partial = cancelled_folder / "source.mp4.part"
    partial.write_bytes(b"partial file")
    page.finish("cancelled")
    assert not cancelled_folder.exists()
    assert page.result is None

    page.start_download()
    incoming = page.work_dir / "output.mp4"
    incoming.write_bytes(b"complete file")
    page.finish("downloaded", source=incoming, readable_audio=True)
    assert page.result == tmp_path / "Тест.mp4"
    assert not page.transcribe_button.isHidden()
    QTest.mouseClick(page.transcribe_button, Qt.MouseButton.LeftButton)
    assert window.stack.currentWidget() is window.tool_views["audio.transcribe"]
    assert window.store.pending()[0]["source"] == str(page.result)
    window.close()


def test_telegram_selection_partial_download_retry_and_cancel(qtbot, tmp_path, monkeypatch):
    window = make_window(qtbot, tmp_path)
    window.open_tool(TELEGRAM_TOOL_ID)
    page = window.tool_views[TELEGRAM_TOOL_ID]
    page.token, page.username = "123456:TEST_ONLY_TOKEN", "test_bot"
    page.update_connection()
    emojis = [Emoji(str(i), i, f"file-{i}", "webp", "😀", 12, None) for i in (1, 2, 3)]
    page.load_pack(EmojiPack("TestEmoji", "Тест", emojis))
    page.directory.setText(str(tmp_path))

    def start_task(action, params, token=None):
        page.action = action

    monkeypatch.setattr(page, "start_task", start_task)
    page.items["1"].setSelected(True)
    page.items["3"].setSelected(True)
    assert page.selected_count.text() == "Выбрано 2 из 3"
    page.download_selected()
    assert [emoji.id for emoji in page.requested] == ["1", "3"]
    result = page.output_folder / "001_1.webp"
    result.write_bytes(b"original")
    page.handle_event("saved", {"id": "1", "path": result})
    page.handle_event("file_failed", {"id": "3", "error": "Недоступно"})
    page.finish("completed")
    assert not page.retry_button.isHidden()
    assert not page.open_button.isHidden()
    page.retry_failed()
    assert [emoji.id for emoji in page.requested] == ["3"]
    partial_folder = page.work_dir
    (partial_folder / "3.part").write_bytes(b"partial")
    page.finish("cancelled")
    assert not partial_folder.exists()
    assert result.read_bytes() == b"original"
    assert page.failed == {"3": "Загрузка прервана."}
    page.link.setText("t.me/addemoji/AnotherPack")
    assert page.pack is None
    assert page.grid.count() == 0
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


def test_telegram_stickers_use_pack_links_selection_and_converter(qtbot, tmp_path, monkeypatch):
    window = make_window(qtbot, tmp_path)
    window.open_tool(TELEGRAM_TOOL_ID)
    page = window.tool_views[TELEGRAM_TOOL_ID]
    page.token, page.username = "123456:TEST_ONLY_TOKEN", "test_bot"
    page.update_connection()
    requests = []

    def start_task(action, params, token=None):
        requests.append((action, params))
        page.action = action

    monkeypatch.setattr(page, "start_task", start_task)
    page.link.setText("https://t.me/addstickers/TestStickers")
    page.lookup()
    assert requests[-1] == ("inspect", {"name": "TestStickers"})
    stickers = [Emoji(f"AgAD_{i}-AbC", i, f"file-{i}", "webp", "", 12, None) for i in (1, 2)]
    page.load_pack(EmojiPack("TestStickers", "Тест", stickers, "regular"))
    assert "стикеров" in page.pack_title.text()
    page.directory.setText(str(tmp_path))
    page.items["AgAD_2-AbC"].setSelected(True)
    page.download_selected()
    assert requests[-1][0] == "download"
    assert requests[-1][1]["emojis"] == stickers[1:]
    assert requests[-1][1]["sticker_type"] == "regular"
    result = page.output_folder / "002_AgAD_2-AbC.webp"
    result.write_bytes(b"original")
    page.handle_event("saved", {"id": "AgAD_2-AbC", "path": result})
    page.finish("completed")
    monkeypatch.setattr("item40.ui.converter_page.ConverterPage.add_files",
                        lambda self, paths: requests.append(paths))
    QTest.mouseClick(page.convert_button, Qt.MouseButton.LeftButton)
    assert requests[-1] == [str(result)]
    assert window.stack.currentWidget() is window.tool_views["files.convert"]
    page.link.setText("tg://addemoji?set=TestEmoji")
    assert page.pack is None and not page.saved and page.grid.count() == 0
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


def test_combination_uses_selected_order_and_creates_one_editor_job(qtbot, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QDialog

    from item40.domain import job_files
    window = make_window(qtbot, tmp_path)
    page = window.tool_views["audio.transcribe"]
    paths = [tmp_path / "first.m4a", tmp_path / "second.flac"]
    for path in paths:
        path.write_bytes(b"original")
    page.add_files([str(path) for path in paths])
    assert len(page.list.selectedItems()) == 2
    assert page.combine_button.isEnabled()

    class ReversedOrder:
        def __init__(self, files, *args, **kwargs):
            self.files = list(reversed(files))

        def exec(self):
            return QDialog.DialogCode.Accepted

        def paths(self):
            return self.files

    monkeypatch.setattr("item40.ui.audio_page.FileOrderDialog", ReversedOrder)
    QTest.mouseClick(page.combine_button, Qt.MouseButton.LeftButton)
    assert page.list.count() == 1
    group = window.store.get(page.selected_id)
    assert job_files(group) == [str(paths[1]), str(paths[0])]
    assert len(window.store.pending()) == 1
    assert len(window.store.jobs()) == 1
    page.edit_order(group["id"])
    assert job_files(window.store.get(group["id"])) == [str(path) for path in paths]
    assert all(path.read_bytes() == b"original" for path in paths)
    window.close()


def test_order_dialog_up_and_down(qtbot):
    from item40.ui.file_order import FileOrderDialog
    dialog = FileOrderDialog(["first.m4a", "second.wav", "third.flac"])
    qtbot.addWidget(dialog)
    dialog.show()
    dialog.list.setCurrentRow(2)
    QTest.mouseClick(dialog.up, Qt.MouseButton.LeftButton)
    QTest.mouseClick(dialog.up, Qt.MouseButton.LeftButton)
    assert dialog.paths() == ["third.flac", "first.m4a", "second.wav"]
    assert not dialog.up.isEnabled()
    QTest.mouseClick(dialog.down, Qt.MouseButton.LeftButton)
    assert dialog.paths() == ["first.m4a", "third.flac", "second.wav"]
    dialog.close()


def streaming_page(qtbot, tmp_path):
    window = make_window(qtbot, tmp_path)
    page = window.tool_views["audio.transcribe"]
    job = JobRequest(source="stream.m4a")
    window.store.add(job)
    text = "\n".join(f"Строка {number}: текст расшифровки." for number in range(180))
    window.store.update(job.id, status="running", transcript=text)
    page.refresh()
    page.select(job.id)
    qtbot.waitUntil(lambda: page.editor.verticalScrollBar().maximum() > 50)
    return window, page, job, text


def test_stream_follows_bottom_pauses_above_it_and_resumes(qtbot, tmp_path):
    window, page, job, text = streaming_page(qtbot, tmp_path)
    scroll = page.editor.verticalScrollBar()
    scroll.setValue(scroll.maximum())
    text += "\n" + "\n".join(f"Новая строка {number}." for number in range(40))
    window.store.update(job.id, transcript=text)
    page.refresh(job.id)
    qtbot.wait(50)
    assert scroll.value() == scroll.maximum()

    # Moving only one line away from the end must already stop following.
    scroll.setValue(scroll.maximum() - 1)
    reading_position = scroll.value()
    text += "\n" + "\n".join(f"Продолжение {number}." for number in range(40))
    window.store.update(job.id, transcript=text)
    page.refresh(job.id)
    qtbot.wait(50)
    assert scroll.value() == reading_position

    scroll.setValue(scroll.maximum())
    text += "\nПоследний фрагмент.\nЕщё одна строка."
    window.store.update(job.id, transcript=text)
    page.refresh(job.id)
    qtbot.wait(50)
    assert scroll.value() == scroll.maximum()
    window.close()


def test_stream_preserves_reading_position_and_selection(qtbot, tmp_path):
    from PySide6.QtGui import QTextCursor
    window, page, job, text = streaming_page(qtbot, tmp_path)
    cursor = page.editor.textCursor()
    cursor.setPosition(20)
    cursor.setPosition(45, QTextCursor.MoveMode.KeepAnchor)
    page.editor.setTextCursor(cursor)
    selected = page.editor.textCursor().selectedText()
    scroll = page.editor.verticalScrollBar()
    scroll.setValue(scroll.maximum() // 3)
    position = scroll.value()
    window.store.update(job.id, transcript=text + "\nСледующий фрагмент. " * 30)
    page.refresh(job.id)
    qtbot.wait(50)
    assert scroll.value() == position
    assert page.editor.textCursor().selectedText() == selected
    window.close()


def test_user_scroll_cancels_a_pending_follow_update(qtbot, tmp_path):
    window, page, job, text = streaming_page(qtbot, tmp_path)
    scroll = page.editor.verticalScrollBar()
    scroll.setValue(scroll.maximum())
    window.store.update(job.id, transcript=text + "\nДополнение." * 30)
    page.refresh(job.id)
    scroll.setValue(scroll.maximum() // 2)
    position = scroll.value()
    qtbot.wait(50)
    assert scroll.value() == position
    window.close()


def test_first_streamed_text_follows_after_editor_becomes_visible(qtbot, tmp_path):
    window, page, job, text = streaming_page(qtbot, tmp_path)
    qtbot.wait(50)
    scroll = page.editor.verticalScrollBar()
    assert scroll.value() == scroll.maximum()
    window.close()


def test_wrapped_stream_and_rapid_updates_keep_the_chosen_scroll_mode(qtbot, tmp_path):
    window, page, job, _ = streaming_page(qtbot, tmp_path)
    text = "Текст без разрывов строк. " * 1200
    window.store.update(job.id, transcript=text)
    page.refresh(job.id)
    qtbot.wait(50)
    scroll = page.editor.verticalScrollBar()
    scroll.setValue(scroll.maximum() - 1)
    position = scroll.value()
    for _ in range(3):
        text += "Продолжение фразы. " * 100
        window.store.update(job.id, transcript=text)
        page.refresh(job.id)
    qtbot.wait(50)
    assert scroll.value() == position
    scroll.setValue(scroll.maximum())
    for _ in range(3):
        text += "Ещё текст. " * 100
        window.store.update(job.id, transcript=text)
        page.refresh(job.id)
    qtbot.wait(50)
    assert scroll.value() == scroll.maximum()
    window.close()


def test_restarted_transcription_follows_from_empty_text(qtbot, tmp_path):
    window, page, job, text = streaming_page(qtbot, tmp_path)
    scroll = page.editor.verticalScrollBar()
    scroll.setValue(scroll.maximum() // 2)
    window.store.update(job.id, transcript="")
    page.refresh(job.id)
    qtbot.wait(20)
    window.store.update(job.id, transcript=text)
    page.refresh(job.id)
    qtbot.wait(50)
    assert scroll.value() == scroll.maximum()
    window.close()
