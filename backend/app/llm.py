"""Grounded guidance generation with Google Gemini, plus output validation."""

import json
import re

from . import config
from .documents import Document
from .prompts import build_system_prompt, build_user_prompt


class GuidanceError(RuntimeError):
    """Raised when guidance cannot be generated."""


FALLBACK_STEPS = {
    "hi": [
        "e-Shram हेल्पलाइन 14434 पर मुफ्त कॉल करें।",
        "SAMADHAN पोर्टल (samadhan.labour.gov.in) पर शिकायत दर्ज करें।",
        "अपनी वेतन पर्ची, हाज़िरी और बैंक रिकॉर्ड संभालकर रखें।",
    ],
    "en": [
        "Call the free e-Shram helpline 14434.",
        "File a complaint on the SAMADHAN portal (samadhan.labour.gov.in).",
        "Keep your wage slips, attendance and bank records safe.",
    ],
    "bn": [
        "বিনামূল্যে e-Shram হেল্পলাইন 14434-এ ফোন করুন।",
        "SAMADHAN পোর্টালে (samadhan.labour.gov.in) অভিযোগ জানান।",
        "আপনার বেতনের স্লিপ, হাজিরা ও ব্যাংকের রেকর্ড সাবধানে রাখুন।",
    ],
    "ta": [
        "இலவச e-Shram உதவி எண் 14434-ஐ அழைக்கவும்.",
        "SAMADHAN இணையதளத்தில் (samadhan.labour.gov.in) புகார் அளிக்கவும்.",
        "உங்கள் சம்பளச் சீட்டு, வருகைப் பதிவு, வங்கிப் பதிவுகளைப் பத்திரமாக வைத்திருங்கள்.",
    ],
    "te": [
        "ఉచిత e-Shram హెల్ప్‌లైన్ 14434కు కాల్ చేయండి.",
        "SAMADHAN పోర్టల్‌లో (samadhan.labour.gov.in) ఫిర్యాదు చేయండి.",
        "మీ జీతం స్లిప్పులు, హాజరు, బ్యాంక్ రికార్డులను జాగ్రత్తగా ఉంచుకోండి.",
    ],
    "mr": [
        "मोफत e-Shram हेल्पलाइन 14434 वर कॉल करा.",
        "SAMADHAN पोर्टलवर (samadhan.labour.gov.in) तक्रार नोंदवा.",
        "तुमच्या पगार स्लिप, हजेरी आणि बँक नोंदी जपून ठेवा.",
    ],
}
FALLBACK_SUMMARY = {
    "hi": "हमें इस समस्या के बारे में पक्की जानकारी नहीं मिली।",
    "en": "We could not find verified information for this problem.",
    "bn": "এই সমস্যার বিষয়ে আমরা নিশ্চিত তথ্য পাইনি।",
    "ta": "இந்தப் பிரச்சினை பற்றி உறுதியான தகவல் கிடைக்கவில்லை.",
    "te": "ఈ సమస్య గురించి ధృవీకరించిన సమాచారం దొరకలేదు.",
    "mr": "या समस्येबद्दल खात्रीशीर माहिती मिळाली नाही.",
}


def fallback_answer(language: str) -> dict:
    language = language if language in FALLBACK_SUMMARY else "en"
    return {
        "summary": FALLBACK_SUMMARY[language],
        "crisis_type": "other",
        "urgency": "medium",
        "steps": FALLBACK_STEPS[language],
        "document_findings": [],
        "sources": [
            {"name": "e-Shram", "url": config.TRUSTED_SOURCES["e-Shram"]},
            {
                "name": "SAMADHAN",
                "url": config.TRUSTED_SOURCES["SAMADHAN (Ministry of Labour & Employment)"],
            },
        ],
        "not_found": True,
    }


def _normalise_url(url: str) -> str:
    return url.strip().rstrip("/").lower().replace("://www.", "://")


def parse_json(text: str) -> dict:
    """Parse model output, tolerating ```json fences around the object."""
    text = text.strip()
    fenced = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.DOTALL)
    if fenced:
        text = fenced.group(1)
    else:
        start, end = text.find("{"), text.rfind("}")
        if start != -1 and end != -1:
            text = text[start : end + 1]
    data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError("Model did not return a JSON object")
    return data


def _str_list(value, limit: int) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(v).strip() for v in value if str(v).strip()][:limit]


def sanitize_answer(raw: dict, language: str, chunks: list[dict]) -> dict:
    """Clamp enums, cap list sizes and drop any URL that is not trusted."""
    allowed = {_normalise_url(u) for u in config.TRUSTED_SOURCES.values()}
    allowed |= {_normalise_url(c["url"]) for c in chunks if c.get("url")}

    sources, seen = [], set()
    for item in raw.get("sources") or []:
        if not isinstance(item, dict):
            continue
        url = str(item.get("url", "")).strip()
        key = _normalise_url(url)
        if key in allowed and key not in seen:
            seen.add(key)
            sources.append({"name": str(item.get("name") or url).strip(), "url": url})

    answer = {
        "summary": str(raw.get("summary") or "").strip(),
        "crisis_type": raw.get("crisis_type") if raw.get("crisis_type") in config.CRISIS_TYPES else "other",
        "urgency": raw.get("urgency") if raw.get("urgency") in config.URGENCY_LEVELS else "medium",
        "steps": _str_list(raw.get("steps"), 8),
        "document_findings": _str_list(raw.get("document_findings"), 8),
        "sources": sources,
        "not_found": bool(raw.get("not_found", False)),
    }
    if not answer["steps"]:
        return fallback_answer(language)
    if not answer["summary"]:
        answer["summary"] = FALLBACK_SUMMARY.get(language, FALLBACK_SUMMARY["en"])
    return answer


def _client():
    if not config.GEMINI_API_KEY:
        raise GuidanceError(
            "GEMINI_API_KEY is not set. Get a free key at https://aistudio.google.com/apikey "
            "and add it to your .env file."
        )
    from google import genai

    return genai.Client(api_key=config.GEMINI_API_KEY)


def generate_guidance(
    question: str, language: str, chunks: list[dict], document: Document | None = None
) -> dict:
    """One grounded Gemini call -> validated answer dict."""
    from google.genai import types

    client = _client()
    contents: list = []
    if document and document.is_image:
        contents.append(types.Part.from_bytes(data=document.data, mime_type=document.mime_type))
    contents.append(build_user_prompt(question, document.text if document else "", chunks))

    gen_config = types.GenerateContentConfig(
        system_instruction=build_system_prompt(language),
        response_mime_type="application/json",
        temperature=0.2,
    )

    last_error: Exception | None = None
    for _ in range(2):  # one retry if the JSON is malformed
        try:
            response = client.models.generate_content(
                model=config.GEMINI_MODEL, contents=contents, config=gen_config
            )
            return sanitize_answer(parse_json(response.text or ""), language, chunks)
        except (ValueError, json.JSONDecodeError) as exc:
            last_error = exc
        except Exception as exc:  # network / auth / quota errors from the SDK
            raise GuidanceError(f"Gemini request failed: {exc}") from exc
    raise GuidanceError(f"Gemini returned invalid JSON twice: {last_error}")
