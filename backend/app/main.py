"""NyayMitra API.

Pipeline for /api/ask:
    text (typed or transcribed) + optional PDF/photo
      -> retrieve top-5 trusted chunks (MiniLM + ChromaDB)
      -> one grounded Gemini call
      -> validate output (allow-listed links only)
      -> save case in SQLite
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware

from . import config, db
from .documents import DocumentError, load_document
from .llm import GuidanceError, generate_guidance
from .rag import retrieve
from .stt import TranscriptionError, transcribe_audio

log = logging.getLogger("nyaymitra")


@asynccontextmanager
async def lifespan(_: FastAPI):
    config.ensure_dirs()
    db.init_db()
    yield


app = FastAPI(title="NyayMitra API", version="1.0.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=config.CORS_ORIGINS,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


def _language(value: str) -> str:
    return value if value in config.LANGUAGES else "hi"


@app.get("/api/health")
def health() -> dict:
    return {
        "ok": True,
        "app": "nyaymitra",
        "groq_key": bool(config.GROQ_API_KEY),
        "gemini_key": bool(config.GEMINI_API_KEY),
    }


@app.post("/api/transcribe")
async def transcribe(audio: UploadFile = File(...), language: str = Form("hi")) -> dict:
    content_type = (audio.content_type or "").split(";")[0].lower()
    if content_type and content_type not in config.AUDIO_TYPES:
        raise HTTPException(415, "Unsupported audio format.")
    data = await audio.read()
    try:
        text = transcribe_audio(data, audio.filename or "audio.webm", content_type, _language(language))
    except TranscriptionError as exc:
        raise HTTPException(400 if "empty" in str(exc) or "large" in str(exc) else 502, str(exc))
    return {"text": text}


@app.post("/api/ask")
async def ask(
    text: str = Form(""),
    language: str = Form("hi"),
    file: UploadFile | None = File(None),
) -> dict:
    language = _language(language)
    question = text.strip()[: config.MAX_QUESTION_CHARS]

    document = None
    if file is not None and file.filename:
        try:
            document = load_document(file.filename, file.content_type or "", await file.read())
        except DocumentError as exc:
            raise HTTPException(400, str(exc))

    if not question and document is None:
        raise HTTPException(400, "Please type or speak your problem, or attach a document.")

    query = " ".join(filter(None, [question, document.text[:1000] if document else ""]))
    try:
        chunks = retrieve(query or "worker documents wages rights")
    except Exception:  # missing index / model download failure should not crash the API
        log.exception("Retrieval failed; continuing without sources")
        chunks = []

    try:
        answer = generate_guidance(question, language, chunks, document)
    except GuidanceError as exc:
        raise HTTPException(502, str(exc))

    case_id = db.save_case(language, question, document.name if document else None, answer)
    return {"id": case_id, "language": language, "question": question, **answer}


@app.get("/api/cases")
def cases(limit: int = 20) -> list[dict]:
    return db.list_cases(max(1, min(limit, 100)))


@app.get("/api/cases/{case_id}")
def case_detail(case_id: int) -> dict:
    case = db.get_case(case_id)
    if case is None:
        raise HTTPException(404, "Case not found.")
    return case
