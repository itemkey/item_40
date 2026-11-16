from __future__ import annotations

import logging
import os
import subprocess
from pathlib import Path

from .domain import JobRequest
from .downloads import Cancelled, check_cancel, ensure_gpu, ensure_model

_dll_handles = []

# Whisper uses preceding transcript context to infer writing style. Keep it short,
# language-matched, and free of names or facts that could bias the recording.
PUNCTUATION_CONTEXT = {
    "ru": "Здравствуйте! Это запись речи. Точная расшифровка: с пунктуацией, вопросами и ответами.",
    "en": "Hello! This is a speech recording. A faithful transcript, with punctuation, questions and answers.",
}


def recognize_chunk(model, samples, language, profile):
    options = dict(task="transcribe", beam_size=5, vad_filter=True, word_timestamps=True,
                   condition_on_previous_text=False)
    context = PUNCTUATION_CONTEXT.get(language) if profile == "large-v3" else None
    segments, info = model.transcribe(samples, language=language, initial_prompt=context, **options)
    # Detect from audio before choosing a writing-style context. Do not impose a
    # Russian prompt on another language, or lock the language on a silent chunk.
    if language is None and profile == "large-v3" and info.duration_after_vad > 0:
        context = PUNCTUATION_CONTEXT.get(info.language)
        if context:
            segments, info = model.transcribe(samples, language=info.language, initial_prompt=context, **options)
    return segments, info


def nvidia_gpu() -> str | None:
    try:
        result = subprocess.run(["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
                                capture_output=True, text=True, timeout=5,
                                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return result.stdout.strip().splitlines()[0] if result.returncode == 0 and result.stdout.strip() else None
    except (OSError, subprocess.TimeoutExpired):
        return None


def run_job(request: JobRequest, root: str, events, cancel):
    """Spawn-safe worker entrypoint. Never imports the UI or writes to its SQLite connection."""
    def emit(kind, **data):
        events.put({"kind": kind, "data": data})

    try:
        from .audio import SAMPLE_RATE, iter_audio_chunks, owned_segments, probe_audio

        data = Path(root)
        data.mkdir(parents=True, exist_ok=True)
        logging.basicConfig(filename=data / "worker.log", encoding="utf-8", level=logging.INFO)
        download_only = request.tool_id == "models.download"
        files = request.files
        durations = []
        if not download_only:
            for source in files:
                check_cancel(cancel)
                try:
                    durations.append(probe_audio(source))
                except ValueError as error:
                    raise ValueError(f"{Path(source).name}: {error}") from error
        model_dir = ensure_model(request.model, data, emit, cancel)
        if download_only:
            emit("completed", download_only=True)
            return

        device = "cuda" if request.device != "cpu" and nvidia_gpu() else "cpu"
        if request.device == "cuda" and device != "cuda":
            raise ValueError("NVIDIA GPU не найдена. Выберите «Процессор» или «Автоматически».")
        if device == "cuda":
            try:
                gpu_dir = ensure_gpu(data, emit, cancel)
                if hasattr(os, "add_dll_directory"):
                    _dll_handles.append(os.add_dll_directory(str(gpu_dir)))
                os.environ["PATH"] = str(gpu_dir) + os.pathsep + os.environ.get("PATH", "")
            except Cancelled:
                raise
            except Exception:
                if request.device == "cuda":
                    raise
                logging.exception("GPU setup failed, using CPU")
                device = "cpu"
                emit("notice", message="Ускорение GPU недоступно. Продолжаем на процессоре.")

        check_cancel(cancel)
        emit("progress", stage="Загрузка модели в память", progress=0)
        from faster_whisper import WhisperModel

        kwargs = {"device": device, "compute_type": "float16" if device == "cuda" else "int8",
                  "cpu_threads": max(1, min(8, (os.cpu_count() or 4) // 2)), "local_files_only": True}
        try:
            model = WhisperModel(str(model_dir), **kwargs)
        except Exception:
            if device != "cuda" or request.device == "cuda":
                raise
            logging.exception("GPU initialization failed, using CPU")
            device = "cpu"
            emit("notice", message="Не удалось запустить GPU. Продолжаем на процессоре.")
            kwargs.update(device="cpu", compute_type="int8")
            model = WhisperModel(str(model_dir), **kwargs)
        total_duration = sum(durations) if all(durations) else None
        offset = 0.0
        processed_duration = 0.0
        last_progress = 0.0
        for source_index, (source, duration) in enumerate(zip(files, durations)):
            language = request.language
            decoded_duration = 0.0
            stage = (f"{source_index + 1}/{len(files)} · {Path(source).name}" if len(files) > 1 else
                     f"Распознавание · {'NVIDIA GPU' if device == 'cuda' else 'процессор'}")

            def progress(local_time):
                nonlocal last_progress
                value = ((processed_duration + local_time) / total_duration if total_duration else
                         (source_index + min(1, local_time / duration) if duration else source_index) / len(files))
                last_progress = max(last_progress, min(0.99, value))
                emit("progress", stage=stage, progress=last_progress)

            for chunk in iter_audio_chunks(source, cancel):
                check_cancel(cancel)
                decoded_duration = max(decoded_duration, chunk.offset + len(chunk.samples) / SAMPLE_RATE)
                progress(chunk.owned_start)
                segments, info = recognize_chunk(model, chunk.samples, language, request.model)
                if language is None and info.duration_after_vad > 0:
                    language = info.language
                    emit("language", language=language)
                for segment in owned_segments(segments, chunk):
                    check_cancel(cancel)
                    local_end = segment["end"]
                    segment.update(start=segment["start"] + offset, end=segment["end"] + offset,
                                   source_index=source_index)
                    emit("segment", segment=segment)
                    progress(local_end)
            offset += decoded_duration
            processed_duration += duration or decoded_duration
        check_cancel(cancel)
        emit("completed", language=language, device=device)
    except Cancelled:
        emit("cancelled")
    except Exception as error:
        logging.exception("Transcription failed")
        message = str(error)
        if any(term in message.lower() for term in ("connection", "resolve", "https", "offline", "timeout")):
            message = "Не удалось скачать компоненты. Проверьте интернет и повторите попытку. Загрузка продолжится."
        emit("failed", error=message or type(error).__name__)
