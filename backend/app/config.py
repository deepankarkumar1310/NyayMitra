"""Central configuration for the NyayMitra backend.

All secrets come from environment variables (loaded from a `.env` file in the
project root or in `backend/`). Nothing secret is ever hard-coded here.
"""

import os
from pathlib import Path

from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parent.parent
PROJECT_DIR = BACKEND_DIR.parent

load_dotenv(PROJECT_DIR / ".env")
load_dotenv(BACKEND_DIR / ".env")


def _env(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


# --- API keys -------------------------------------------------------------
GROQ_API_KEY = _env("GROQ_API_KEY")
GEMINI_API_KEY = _env("GEMINI_API_KEY")

# --- Models ---------------------------------------------------------------
GEMINI_MODEL = _env("GEMINI_MODEL", "gemini-flash-latest")
WHISPER_MODEL = _env("WHISPER_MODEL", "whisper-large-v3-turbo")
EMBED_MODEL = _env(
    "EMBED_MODEL", "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
)
GROQ_TRANSCRIBE_URL = "https://api.groq.com/openai/v1/audio/transcriptions"

# --- Storage --------------------------------------------------------------
DATA_DIR = Path(_env("NYAYMITRA_DATA_DIR") or BACKEND_DIR / "data")
KNOWLEDGE_DIR = BACKEND_DIR / "knowledge"
CHROMA_DIR = DATA_DIR / "chroma"
DB_PATH = DATA_DIR / "cases.db"
COLLECTION_NAME = "nyaymitra_knowledge"

# --- Limits ---------------------------------------------------------------
TOP_K = 5
MAX_UPLOAD_BYTES = 15 * 1024 * 1024
MAX_DOC_CHARS = 12_000
MAX_QUESTION_CHARS = 4_000

AUDIO_TYPES = {
    "audio/webm", "audio/ogg", "audio/wav", "audio/x-wav", "audio/mpeg",
    "audio/mp3", "audio/mp4", "audio/m4a", "audio/x-m4a",
}
IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp"}
PDF_TYPE = "application/pdf"

LANGUAGES = {"hi", "en"}
CRISIS_TYPES = {
    "unpaid_wages", "termination", "injury", "harassment",
    "documents", "schemes", "jobs", "other",
}
URGENCY_LEVELS = {"low", "medium", "high", "critical"}

# Official links the model is allowed to cite. Anything else is dropped.
TRUSTED_SOURCES = {
    "SAMADHAN (Ministry of Labour & Employment)": "https://samadhan.labour.gov.in/",
    "e-Shram": "https://eshram.gov.in/",
    "myScheme": "https://www.myscheme.gov.in/",
    "National Career Service": "https://www.ncs.gov.in/",
    "SHe-Box": "https://shebox.wcd.gov.in/",
    "Ministry of Labour & Employment": "https://labour.gov.in/",
}

HELPLINES = {
    "e-Shram helpline": "14434",
    "Emergency (police / ambulance)": "112",
    "Women helpline": "181",
}

CORS_ORIGINS = [
    o.strip()
    for o in _env("CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173").split(",")
    if o.strip()
]


def ensure_dirs() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    CHROMA_DIR.mkdir(parents=True, exist_ok=True)
