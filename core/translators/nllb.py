"""
NLLB-200 translation backend — Meta's No Language Left Behind model.

Why this exists:
  Small local LLMs (7B-class) hallucinate on low-resource target languages
  (Uzbek, Kazakh, Tajik, Swahili, ...). NLLB is a dedicated translation
  transformer trained on 200 languages, so it actually KNOWS these languages
  rather than guessing words from cognates.

Model:
  facebook/nllb-200-distilled-600M
  - ~600 MB on disk, runs comfortably on CPU
  - covers 200 languages, both directions
  - quality is comparable to Google Translate on most pairs

Lazy-loaded singleton: the model is downloaded + initialized on first call,
then cached in-process. Subsequent calls are fast.
"""
from __future__ import annotations
import re, threading, asyncio
from typing import Optional

# ── FLORES-200 language codes used by NLLB ─────────────────────────────────
# Map our human-readable language names → NLLB code.
# Full reference: https://github.com/facebookresearch/flores/blob/main/flores200/README.md
NLLB_CODES: dict[str, str] = {
    # Tier 1
    "english": "eng_Latn",
    "spanish": "spa_Latn",
    "french": "fra_Latn",
    "german": "deu_Latn",
    "italian": "ita_Latn",
    "portuguese": "por_Latn",
    "russian": "rus_Cyrl",
    "chinese": "zho_Hans",         # simplified
    "mandarin": "zho_Hans",
    "japanese": "jpn_Jpan",
    "korean": "kor_Hang",
    "dutch": "nld_Latn",
    "polish": "pol_Latn",
    "arabic": "arb_Arab",          # modern standard
    "turkish": "tur_Latn",
    # Tier 2
    "swedish": "swe_Latn",
    "norwegian": "nob_Latn",       # bokmål
    "danish": "dan_Latn",
    "finnish": "fin_Latn",
    "czech": "ces_Latn",
    "romanian": "ron_Latn",
    "hungarian": "hun_Latn",
    "ukrainian": "ukr_Cyrl",
    "greek": "ell_Grek",
    "hebrew": "heb_Hebr",
    "hindi": "hin_Deva",
    "vietnamese": "vie_Latn",
    "thai": "tha_Thai",
    "indonesian": "ind_Latn",
    "malay": "zsm_Latn",
    # Tier 3 (the languages where NLLB is a game-changer vs. small LLMs)
    "uzbek": "uzn_Latn",           # Northern Uzbek, Latin script
    "kazakh": "kaz_Cyrl",
    "kyrgyz": "kir_Cyrl",
    "azerbaijani": "azj_Latn",     # North Azerbaijani, Latin
    "tajik": "tgk_Cyrl",
    "turkmen": "tuk_Latn",
    "mongolian": "khk_Cyrl",       # Halh Mongolian
    "tibetan": "bod_Tibt",
    "filipino": "tgl_Latn",
    "tagalog": "tgl_Latn",
    "swahili": "swh_Latn",
    "zulu": "zul_Latn",
    "amharic": "amh_Ethi",
    "yoruba": "yor_Latn",
    "igbo": "ibo_Latn",
    "punjabi": "pan_Guru",
    "marathi": "mar_Deva",
    "gujarati": "guj_Gujr",
    "tamil": "tam_Taml",
    "telugu": "tel_Telu",
    "bengali": "ben_Beng",
    "urdu": "urd_Arab",
    "sinhala": "sin_Sinh",
    "khmer": "khm_Khmr",
    "lao": "lao_Laoo",
    "burmese": "mya_Mymr",
    "georgian": "kat_Geor",
    "armenian": "hye_Armn",
    "albanian": "als_Latn",        # Tosk Albanian
}


def supported_languages() -> set[str]:
    """Return the set of human-readable language names NLLB can translate to/from."""
    return set(NLLB_CODES.keys())


# ── Lazy model loading (thread-safe singleton) ─────────────────────────────
_MODEL_NAME = "facebook/nllb-200-distilled-600M"
_lock = threading.Lock()
_state: dict = {
    "tokenizer": None,
    "model": None,
    "loaded": False,
    "failed": False,
    "error": "",
}


def _load_sync() -> bool:
    """Load NLLB model + tokenizer once. Returns True on success."""
    if _state["loaded"]:
        return True
    if _state["failed"]:
        return False
    with _lock:
        if _state["loaded"]:
            return True
        if _state["failed"]:
            return False
        try:
            # Defer the heavy imports so launching the app doesn't pay the
            # transformers import cost unless translation is actually used.
            from transformers import AutoTokenizer, AutoModelForSeq2SeqLM
            import torch
            tokenizer = AutoTokenizer.from_pretrained(_MODEL_NAME)
            model = AutoModelForSeq2SeqLM.from_pretrained(_MODEL_NAME)
            # CPU is fine — NLLB-600M runs at ~50 tokens/sec on a modern laptop.
            # If a GPU is present, move to it.
            if torch.cuda.is_available():
                model = model.to("cuda")
            model.eval()
            _state["tokenizer"] = tokenizer
            _state["model"] = model
            _state["loaded"] = True
            return True
        except Exception as e:
            _state["failed"] = True
            _state["error"] = f"{type(e).__name__}: {e}"
            return False


def is_available() -> bool:
    """Cheap check: have we already loaded, or could we?"""
    if _state["loaded"]:
        return True
    if _state["failed"]:
        return False
    # Don't trigger a load just to answer this — only confirm if libs are present.
    try:
        import transformers  # noqa
        import torch          # noqa
        return True
    except Exception:
        return False


# ── Source language detection ──────────────────────────────────────────────
# langdetect — Apache-2.0 statistical detector for 55 languages including the
# tier-3 ones (Uzbek, Kazakh, Tajik, ...). We try it first because it's far
# more accurate on short text than the stopword heuristic below.
try:
    from langdetect import detect_langs as _ld_detect_langs, DetectorFactory
    DetectorFactory.seed = 0  # deterministic results — reproducible benchmarks
    _LANGDETECT_OK = True
except Exception:
    _LANGDETECT_OK = False

# langdetect uses ISO 639-1 codes; map to our human-readable names that
# match NLLB_CODES. Codes langdetect doesn't support (uzbek, tajik) just
# fall through to the heuristic.
_ISO_TO_NAME = {
    "en": "english", "es": "spanish", "fr": "french", "de": "german",
    "it": "italian", "pt": "portuguese", "ru": "russian", "zh-cn": "chinese",
    "zh-tw": "chinese", "ja": "japanese", "ko": "korean", "nl": "dutch",
    "pl": "polish", "ar": "arabic", "tr": "turkish", "sv": "swedish",
    "no": "norwegian", "da": "danish", "fi": "finnish", "cs": "czech",
    "ro": "romanian", "hu": "hungarian", "uk": "ukrainian", "el": "greek",
    "he": "hebrew", "hi": "hindi", "vi": "vietnamese", "th": "thai",
    "id": "indonesian", "ms": "malay", "uz": "uzbek", "kk": "kazakh",
    "ky": "kyrgyz", "az": "azerbaijani", "tg": "tajik", "tk": "turkmen",
    "mn": "mongolian", "tl": "tagalog", "sw": "swahili", "am": "amharic",
    "yo": "yoruba", "pa": "punjabi", "mr": "marathi", "gu": "gujarati",
    "ta": "tamil", "te": "telugu", "bn": "bengali", "ur": "urdu",
    "si": "sinhala", "km": "khmer", "lo": "lao", "my": "burmese",
    "ka": "georgian", "hy": "armenian", "sq": "albanian",
}


def _detect_uzbek_latin(text: str) -> bool:
    """Pre-detector for Uzbek (Latin script).

    langdetect doesn't include Uzbek in its training profiles and confidently
    misclassifies it as Somali / Turkish. We use three independent signals:

      1. Apostrophe-letter signature: o', oʻ, oʼ, g', gʻ, gʼ — Uzbek-unique
      2. Native function words / common nouns — large stopword list
      3. Letter frequency cue — the letter 'q' is ~5% of Uzbek text vs ~0.1%
         of English. Two or more q's in a short sentence is a strong tell.

    Any single sufficiently-strong signal returns True.
    """
    if not text:
        return False
    low_raw = text.lower()
    low = " " + low_raw + " "

    # Signal 1: apostrophe-letters — by themselves enough to confirm
    apostrophe_letters = ("o'", "oʻ", "oʼ", "g'", "gʻ", "gʼ")
    if any(a in low for a in apostrophe_letters):
        return True

    # Signal 2: stopwords / common Uzbek tokens (substantially expanded).
    # Word-boundary matching tolerates punctuation: "qalaysiz?" still hits.
    stopwords = (
        "bu", "va", "bilan", "uchun", "ham", "lekin", "ammo",
        "kabi", "yoki", "agar", "chunki", "har", "mavjud",
        "emas", "edi", "esa", "hech", "hamma", "orqali",
        "biroq", "endi", "bunda", "shuningdek", "keyin",
        # Greetings and very common nouns/verbs
        "salom", "rahmat", "qalaysiz", "qalay", "dunyo", "men",
        "siz", "biz", "ular", "kim", "nima", "qachon", "qayer",
        "qaerda", "qanday", "qaysi", "qachongacha", "nechta",
        "juda", "yaxshi", "bor",
        "hafta", "kun", "yil", "oy", "soat", "bugun", "ertaga",
    )
    import re as _re
    tokens = _re.findall(r"[a-z']+", low_raw)
    token_set = set(tokens)
    sw_hits = sum(1 for w in stopwords if w in token_set)

    # Signal 3: 'q' frequency — Uzbek uses 'q' very heavily. 2+ q's in any
    # reasonably-sized text is a strong hint, especially when combined with
    # at least one stopword.
    q_count = low_raw.count("q")

    if sw_hits >= 2:
        return True
    if sw_hits >= 1 and q_count >= 2:
        return True
    if q_count >= 3 and len(low_raw) <= 60:
        # Lots of q's in a short sentence — very unlikely outside Uzbek
        return True
    return False


def detect_source_language(text: str) -> str:
    """Source-language detection.

    Strategy:
      1. Pre-check tier-3 Latin languages langdetect can't handle (Uzbek)
      2. langdetect (statistical n-gram model) — accurate even on short text
         for the 55 languages it supports
      3. Fallback to script + stopword heuristic if langdetect can't decide
         or returns low confidence.

    Returns a human-readable lowercase name matching NLLB_CODES.
    """
    # Pre-detectors for languages langdetect doesn't support
    if _detect_uzbek_latin(text):
        return "uzbek"

    if _LANGDETECT_OK and text and text.strip():
        try:
            sample = text[:1000]
            results = _ld_detect_langs(sample)
            if results:
                top = results[0]
                name = _ISO_TO_NAME.get(top.lang)
                if name:
                    # Confidence rules:
                    #  - Long text (>=80 chars): trust top match if prob >= 0.70
                    #  - Short text: require prob >= 0.95 for non-english
                    #    claims, since langdetect over-confidently classifies
                    #    short English snippets as Tagalog/Somali/Catalan/etc.
                    long_text = len(sample.strip()) >= 80
                    threshold = 0.70 if long_text else 0.95
                    if top.prob >= threshold:
                        return name
                    # Below threshold: only trust if it's english (default
                    # safe bet for unclear short Latin text)
                    if name == "english":
                        return name
        except Exception:
            pass  # fall through to heuristic

    return _detect_source_language_heuristic(text)


def _detect_source_language_heuristic(text: str) -> str:
    """Fallback: script + stopword based detection. Kept as a safety net for
    when langdetect is unavailable or unsure."""
    if not text:
        return "english"
    # Sample first 500 chars to keep this cheap on long inputs
    sample = text[:500]

    # Script counts via unicode ranges
    cyrillic = sum(1 for c in sample if "Ѐ" <= c <= "ӿ")
    cjk      = sum(1 for c in sample if "一" <= c <= "鿿")
    arabic   = sum(1 for c in sample if "؀" <= c <= "ۿ")
    hebrew   = sum(1 for c in sample if "֐" <= c <= "׿")
    devanagari = sum(1 for c in sample if "ऀ" <= c <= "ॿ")
    hangul   = sum(1 for c in sample if "가" <= c <= "힯")
    hiragana_katakana = sum(1 for c in sample if "぀" <= c <= "ヿ")
    thai     = sum(1 for c in sample if "฀" <= c <= "๿")
    greek    = sum(1 for c in sample if "Ͱ" <= c <= "Ͽ")
    georgian = sum(1 for c in sample if "Ⴀ" <= c <= "ჿ")
    armenian = sum(1 for c in sample if "԰" <= c <= "֏")

    # Most-common-script wins
    scripts = {
        "cyrillic": cyrillic, "cjk": cjk, "arabic": arabic, "hebrew": hebrew,
        "devanagari": devanagari, "hangul": hangul, "japanese": hiragana_katakana,
        "thai": thai, "greek": greek, "georgian": georgian, "armenian": armenian,
    }
    top_script, top_count = max(scripts.items(), key=lambda kv: kv[1])
    if top_count < 3:
        # Fall through to Latin handling
        top_script = "latin"

    # Script → language disambiguation
    if top_script == "japanese":
        return "japanese"   # hiragana/katakana presence is conclusive
    if top_script == "hangul":
        return "korean"
    if top_script == "cjk":
        return "chinese"
    if top_script == "thai":
        return "thai"
    if top_script == "greek":
        return "greek"
    if top_script == "georgian":
        return "georgian"
    if top_script == "armenian":
        return "armenian"
    if top_script == "hebrew":
        return "hebrew"
    if top_script == "arabic":
        # Could be Arabic, Urdu, Persian. Cheap disambiguation by common words.
        low = sample.lower()
        if any(w in low for w in ("ہے", "کے", "کی", "نہیں")):
            return "urdu"
        return "arabic"
    if top_script == "devanagari":
        # Hindi vs. Marathi. Default to Hindi (much more common).
        return "hindi"
    if top_script == "cyrillic":
        low = sample.lower()
        # Tell Russian / Ukrainian / Kazakh / Kyrgyz / Tajik / Mongolian apart
        # by language-specific letters
        if any(c in sample for c in "ҐЄІЇ"):     # Ukrainian-unique
            return "ukrainian"
        if any(c in sample for c in "ӘҒҚҢӨҰҮҺІ"):  # Kazakh-unique-ish
            return "kazakh"
        if any(c in sample for c in "ңөү") and "ң" in low:
            return "kyrgyz"
        if any(c in sample for c in "ҷӣӯҳқғ"):  # Tajik-unique
            return "tajik"
        return "russian"

    # Latin script — guess by stopwords
    low = " " + sample.lower() + " "
    scores = {
        "english":     sum(low.count(f" {w} ") for w in ("the", "and", "of", "to", "is", "in", "that", "for")),
        "spanish":     sum(low.count(f" {w} ") for w in ("el", "la", "de", "que", "los", "las", "y", "es", "en")),
        "french":      sum(low.count(f" {w} ") for w in ("le", "la", "de", "et", "les", "des", "un", "une", "est")),
        "german":      sum(low.count(f" {w} ") for w in ("der", "die", "das", "und", "ist", "von", "zu", "mit", "nicht")),
        "italian":     sum(low.count(f" {w} ") for w in ("il", "la", "di", "che", "e", "è", "un", "una", "per")),
        "portuguese":  sum(low.count(f" {w} ") for w in ("o", "a", "de", "que", "do", "da", "é", "para", "com")),
        "polish":      sum(low.count(f" {w} ") for w in ("nie", "się", "jest", "że", "to", "na", "do", "co")),
        "turkish":     sum(low.count(f" {w} ") for w in ("bir", "ve", "bu", "için", "ile", "değil", "olarak")),
        "uzbek":       sum(low.count(f" {w} ") for w in ("va", "bu", "bilan", "uchun", "ham", "lekin", "ammo")),
        "vietnamese":  sum(low.count(f" {w} ") for w in ("của", "là", "và", "có", "trong", "được", "không")),
        "indonesian":  sum(low.count(f" {w} ") for w in ("yang", "dan", "di", "untuk", "ini", "dengan", "adalah")),
    }
    best = max(scores.items(), key=lambda kv: kv[1])
    return best[0] if best[1] >= 2 else "english"


# ── Translate ──────────────────────────────────────────────────────────────
def _translate_sync(text: str, src_lang: str, tgt_lang: str,
                     max_length: int = 1024) -> str:
    """Core blocking translate call. Splits long input into sentences to fit
    NLLB's 512-token context."""
    if not _load_sync():
        raise RuntimeError(f"NLLB not available: {_state['error']}")

    src_code = NLLB_CODES.get(src_lang.lower())
    tgt_code = NLLB_CODES.get(tgt_lang.lower())
    if not src_code:
        raise ValueError(f"Source language not supported by NLLB: {src_lang}")
    if not tgt_code:
        raise ValueError(f"Target language not supported by NLLB: {tgt_lang}")

    tokenizer = _state["tokenizer"]
    model     = _state["model"]
    import torch
    device = next(model.parameters()).device

    tokenizer.src_lang = src_code
    # Resolve the target language as a forced BOS token (NLLB convention)
    forced_bos = tokenizer.convert_tokens_to_ids(tgt_code)

    # Sentence-chunk long input so each chunk fits NLLB's 512-token window
    chunks = _chunk_text(text, max_chars=900)
    out_parts: list[str] = []
    for chunk in chunks:
        inputs = tokenizer(chunk, return_tensors="pt", truncation=True, max_length=512)
        inputs = {k: v.to(device) for k, v in inputs.items()}
        with torch.no_grad():
            gen = model.generate(
                **inputs,
                forced_bos_token_id=forced_bos,
                max_length=max_length,
                num_beams=4,
                early_stopping=True,
                no_repeat_ngram_size=3,
            )
        decoded = tokenizer.batch_decode(gen, skip_special_tokens=True)[0]
        out_parts.append(decoded.strip())
    return " ".join(out_parts).strip()


_SENT_SPLIT = re.compile(r"(?<=[.!?…])\s+(?=[A-ZА-ЯЁ])|(?<=[。！？])")


def _chunk_text(text: str, max_chars: int = 900) -> list[str]:
    """Split text into sentence-respecting chunks under max_chars."""
    text = text.strip()
    if len(text) <= max_chars:
        return [text]
    sentences = _SENT_SPLIT.split(text)
    chunks: list[str] = []
    buf = ""
    for s in sentences:
        s = s.strip()
        if not s:
            continue
        if len(buf) + len(s) + 1 > max_chars and buf:
            chunks.append(buf.strip())
            buf = s
        else:
            buf = (buf + " " + s).strip() if buf else s
    if buf:
        chunks.append(buf.strip())
    # Last-resort hard split for pathological cases (no sentence boundaries)
    final: list[str] = []
    for c in chunks:
        if len(c) <= max_chars:
            final.append(c)
        else:
            for i in range(0, len(c), max_chars):
                final.append(c[i:i + max_chars])
    return final


async def translate(text: str, target: str, source: Optional[str] = None) -> str:
    """Async wrapper — runs the blocking NLLB call in a thread.

    Args:
      text:    source text to translate
      target:  human-readable target language name (e.g. "uzbek", "russian")
      source:  optional source language name; auto-detected if omitted
    """
    if not text or not text.strip():
        return ""
    src = (source or detect_source_language(text)).lower()
    tgt = target.lower()
    if src == tgt:
        return text  # already in target language
    return await asyncio.to_thread(_translate_sync, text, src, tgt)
