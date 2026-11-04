"""Speech-to-text with Groq-hosted Whisper."""

import httpx

from . import config


class TranscriptionError(RuntimeError):
    """Raised when audio cannot be transcribed."""


def transcribe_audio(
    data: bytes, filename: str, content_type: str, language: str | None = None
) -> str:
    if not config.GROQ_API_KEY:
        raise TranscriptionError(
            "GROQ_API_KEY is not set. Get a free key at https://console.groq.com/ "
            "and add it to your .env file."
        )
    if not data:
        raise TranscriptionError("The audio recording is empty.")
    if len(data) > config.MAX_UPLOAD_BYTES:
        raise TranscriptionError("The audio file is too large (max 15 MB).")

    form = {"model": config.WHISPER_MODEL, "response_format": "json", "temperature": "0"}
    if language in config.LANGUAGES:
        form["language"] = language

    try:
        response = httpx.post(
            config.GROQ_TRANSCRIBE_URL,
            headers={"Authorization": f"Bearer {config.GROQ_API_KEY}"},
            data=form,
            files={"file": (filename or "audio.webm", data, content_type or "audio/webm")},
            timeout=60,
        )
    except httpx.HTTPError as exc:
        raise TranscriptionError(f"Could not reach Groq: {exc}") from exc

    if response.status_code == 401:
        raise TranscriptionError("Groq rejected the API key. Check GROQ_API_KEY in .env.")
    if response.status_code >= 400:
        raise TranscriptionError(f"Groq returned {response.status_code}: {response.text[:200]}")

    return (response.json().get("text") or "").strip()
