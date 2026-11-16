from types import SimpleNamespace
from unittest.mock import Mock

from item40.worker import recognize_chunk


def test_auto_language_uses_audio_before_russian_punctuation_context():
    info = SimpleNamespace(language="ru", duration_after_vad=12)
    model = Mock()
    model.transcribe.return_value = (iter([]), info)
    recognize_chunk(model, "samples", None, "large-v3")
    first, second = model.transcribe.call_args_list
    assert first.kwargs["language"] is None
    assert first.kwargs["initial_prompt"] is None
    assert second.kwargs["language"] == "ru"
    assert "!" in second.kwargs["initial_prompt"]


def test_silence_and_other_languages_do_not_receive_russian_context():
    for language, duration in [("en", 0), ("ja", 12)]:
        model = Mock()
        model.transcribe.return_value = (iter([]), SimpleNamespace(language=language, duration_after_vad=duration))
        recognize_chunk(model, "samples", None, "large-v3")
        model.transcribe.assert_called_once()
        assert model.transcribe.call_args.kwargs["initial_prompt"] is None
