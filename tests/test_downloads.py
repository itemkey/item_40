import hashlib
import threading
from unittest.mock import Mock

import pytest

from item40.downloads import Cancelled, download_file, ensure_model


def test_downloaded_model_never_contacts_network(tmp_path, monkeypatch):
    folder = tmp_path / "models" / "small"
    folder.mkdir(parents=True)
    for name in ("config.json", "model.bin", "tokenizer.json", "vocabulary.txt", ".ready"):
        (folder / name).write_text("ready")
    download = Mock(side_effect=AssertionError("Network should not be used"))
    monkeypatch.setattr("huggingface_hub.HfApi.model_info", download)
    assert ensure_model("small", tmp_path, Mock(), threading.Event()) == folder
    download.assert_not_called()


def test_partial_model_is_not_treated_as_ready(tmp_path, monkeypatch):
    folder = tmp_path / "models" / "small"
    folder.mkdir(parents=True)
    (folder / ".ready").write_text("1")
    monkeypatch.setattr("huggingface_hub.HfApi.model_info", Mock(return_value=Mock(siblings=[], sha="test")))
    with pytest.raises(RuntimeError, match="не полностью"):
        ensure_model("small", tmp_path, Mock(), threading.Event())


def test_download_resumes_and_verifies_checksum(tmp_path, monkeypatch):
    data = b"first-second"
    destination = tmp_path / "test.whl"
    destination.with_suffix(".part").write_bytes(b"first-")
    response = Mock()
    response.__enter__ = Mock(return_value=response)
    response.__exit__ = Mock(return_value=False)
    response.status_code = 206
    response.headers = {"Content-Length": "6"}
    response.iter_content.return_value = [b"second"]
    get = Mock(return_value=response)
    monkeypatch.setattr("requests.get", get)
    download_file("https://example.invalid", destination, hashlib.sha256(data).hexdigest(), Mock(), threading.Event())
    assert destination.read_bytes() == data
    assert get.call_args.kwargs["headers"]["Range"] == "bytes=6-"


def test_cancel_before_model_download(tmp_path):
    cancel = threading.Event()
    cancel.set()
    with pytest.raises(Cancelled):
        ensure_model("small", tmp_path, Mock(), cancel)
