"""
TranslationSkill — Level 1 capability (translate text or web pages).

Detects translation intent and routes through a focused prompt that:
  - Returns clean translation (no preamble, no commentary)
  - Preserves formatting / code blocks
  - Honors the user's thinking toggle for tricky / nuanced translation
"""
from __future__ import annotations
import re, sys, time
from typing import AsyncIterator


import pathlib as _pathlib
_LOG_PATH = _pathlib.Path(__file__).resolve().parent.parent.parent / "translation_debug.log"

def _log(msg: str) -> None:
    """Diagnostic log — written to stderr AND translation_debug.log so the
    NLLB pipeline is observable even when the server console is in another
    window. Truncates daily."""
    stamp = time.strftime("%H:%M:%S")
    line  = f"[translation {stamp}] {msg}"
    print(line, file=sys.stderr, flush=True)
    try:
        with _LOG_PATH.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass

from core.skills.base import Skill, SkillContext, SkillEvent
from core.skills._synthesize import synthesize
from core.web_navigator    import fetch_smart
from core.skills.web_fetch import _extract_explicit_urls
from core.generator        import generate, stream as llm_stream
from core.translation_memory import (
    load_glossary, format_glossary_for_prompt,
    find_relevant_examples, format_examples_for_prompt,
    available_languages, append_example,
    apply_domain_rewrites, _classify_domain,
)
from core.translators import (
    nllb_translate, nllb_available,
    detect_source_language, supported_languages as nllb_supported,
)


# Build the target-language detection regex AUTO-MAGICALLY from LANGUAGE_TIERS
# (defined below) so adding a language to LANGUAGE_TIERS automatically makes it
# detectable here too. NO MORE forgotten languages.
def _build_target_lang_re():
    # Forward reference — LANGUAGE_TIERS is defined later in this module.
    # We use a placeholder pattern and rebuild after the dict exists.
    return None

_TARGET_LANG_RE = None        # set after LANGUAGE_TIERS is defined
_TRIGGER_RE     = None        # likewise


def _ensure_compiled():
    """Compile detection regexes from LANGUAGE_TIERS — called lazily on first use."""
    global _TARGET_LANG_RE, _TRIGGER_RE
    if _TARGET_LANG_RE is not None:
        return
    lang_names = sorted(LANGUAGE_TIERS.keys(), key=len, reverse=True)  # longer first to win matches
    lang_alt   = "|".join(re.escape(n) for n in lang_names)

    _TARGET_LANG_RE = re.compile(
        rf"\b(?:to|into|in|in\s+the)\s+({lang_alt})\b",
        re.I,
    )
    # Translation skill only fires on EXPLICIT translation intent. We
    # deliberately do NOT match bare "in <language>" — that pattern fires
    # on sentences like "tell me a fact in uzbek about the universe", which
    # is a general-knowledge question wanting the ANSWER in Uzbek, not a
    # translation. Those go through the normal LLM path; modern LLMs handle
    # multilingual response naturally without a translation pipeline.
    _TRIGGER_RE = re.compile(
        rf"\b(translate|translation|"
        rf"how\s+do\s+(?:you|i)\s+say|how\s+to\s+say|what\s+does\s+\".+\"\s+mean|"
        rf"convert\s+(?:this|it)\s+to\s+(?:{lang_alt}))\b",
        re.I,
    )


def _detect_target_lang(query: str) -> str | None:
    _ensure_compiled()
    m = _TARGET_LANG_RE.search(query)
    if m:
        return m.group(1).lower().title()
    return None


# ── Language tiers ──────────────────────────────────────────────────────────
# Tier 1: model has strong fluency. Expect near-native output.
# Tier 2: workable but watch for code-switching / awkward phrasing.
# Tier 3: low-resource — model often produces broken/mixed-script output.
#         We warn the user up front.
LANGUAGE_TIERS: dict[str, int] = {
    # Tier 1 (well-represented)
    "english":1, "spanish":1, "french":1, "german":1, "italian":1,
    "portuguese":1, "russian":1, "chinese":1, "mandarin":1, "japanese":1,
    "korean":1, "dutch":1, "polish":1, "arabic":1, "turkish":1,
    # Tier 2 (workable)
    "swedish":2, "norwegian":2, "danish":2, "finnish":2, "czech":2,
    "romanian":2, "hungarian":2, "ukrainian":2, "greek":2, "hebrew":2,
    "hindi":2, "vietnamese":2, "thai":2, "indonesian":2, "malay":2,
    # Tier 3 (low-resource — model struggles)
    "uzbek":3, "kazakh":3, "kyrgyz":3, "azerbaijani":3, "tajik":3,
    "turkmen":3, "mongolian":3, "tibetan":3, "filipino":3, "tagalog":3,
    "swahili":3, "zulu":3, "amharic":3, "yoruba":3, "igbo":3,
    "punjabi":3, "marathi":3, "gujarati":3, "tamil":3, "telugu":3,
    "bengali":3, "urdu":3, "sinhala":3, "khmer":3, "lao":3,
    "burmese":3, "georgian":3, "armenian":3, "albanian":3,
}


# ── Multi-language tech glossary ────────────────────────────────────────────
GLOSSARIES = {
    "French": """
   garbage collection         → ramasse-miettes / gestion automatique de la mémoire
   machine learning           → apprentissage automatique (NOT "apprentissages")
   deep learning              → apprentissage profond
   backward-compatible        → rétrocompatible
   forward-compatible         → compatible ascendant
   top ten                    → les dix premiers / le top 10
   plain English              → anglais clair / langage simple
   batteries included         → piles incluses (idiomatic) / livré avec ses outils
   open source                → libre / à code ouvert
   high-level language        → langage de haut niveau
   low-level language         → langage de bas niveau
   dynamic typing             → typage dynamique
   static typing              → typage statique
   ease of writing            → facilité d'écriture
   bug                        → bogue (or anglicism "bug")
   library                    → bibliothèque
   framework                  → cadre / framework
   release                    → version / publication
   end-of-life                → fin de vie / fin de support""",
    "Russian": """
   garbage collection         → сборка мусора
   machine learning           → машинное обучение (NOT "обучение машин")
   deep learning              → глубокое обучение
   backward-compatible        → обратно совместимый
   forward-compatible         → прямо совместимый
   top ten                    → первая десятка (NOT "первое место среди десяти")
   plain English              → простой английский / обычный английский
   batteries included         → «всё в комплекте» / со встроенными библиотеками
   open source                → открытый исходный код / открытое ПО
   high-level language        → язык высокого уровня
   low-level language         → язык низкого уровня
   dynamic typing             → динамическая типизация
   static typing              → статическая типизация
   indentation                → отступы (NOT "отступление" — that means "deviation")
   ease of writing            → удобство написания
   bug                        → баг / ошибка
   library                    → библиотека
   framework                  → фреймворк
   release                    → выпуск / релиз / версия
   end-of-life                → конец поддержки / окончание срока поддержки
   "Beginning with..."        → "Начиная с..." (NOT "Стартуя с...")
   "supports X, Y, Z"         → "поддерживает X, Y, Z" (verb agrees with subject)
   1980s in Russian           → 1980-е годы (NO trailing "s")""",
    "Spanish": """
   garbage collection         → recolección de basura
   machine learning           → aprendizaje automático
   deep learning              → aprendizaje profundo
   backward-compatible        → retrocompatible
   top ten                    → los diez mejores / top 10
   plain English              → inglés sencillo / inglés llano
   open source                → código abierto
   high-level language        → lenguaje de alto nivel
   dynamic typing             → tipado dinámico
   static typing              → tipado estático
   library                    → biblioteca
   framework                  → marco de trabajo / framework
   release                    → versión / lanzamiento
   end-of-life                → fin de vida / fin del soporte""",
    "German": """
   garbage collection         → Speicherbereinigung / Garbage Collection
   machine learning           → maschinelles Lernen
   deep learning              → tiefes Lernen / Deep Learning
   backward-compatible        → abwärtskompatibel
   top ten                    → die ersten zehn / Top 10
   plain English              → einfaches Englisch
   open source                → quelloffen / Open Source
   high-level language        → höhere Programmiersprache
   dynamic typing             → dynamische Typisierung
   library                    → Bibliothek
   framework                  → Framework
   release                    → Veröffentlichung / Version
   end-of-life                → Lebensende / Support-Ende""",
    "Chinese": """
   garbage collection         → 垃圾回收
   machine learning           → 机器学习
   deep learning              → 深度学习
   backward-compatible        → 向后兼容
   top ten                    → 前十名 / 十大
   plain English              → 通俗英语
   open source                → 开源
   high-level language        → 高级语言
   dynamic typing             → 动态类型
   library                    → 库 / 函数库
   framework                  → 框架
   release                    → 发布 / 发布版
   end-of-life                → 生命周期结束 / 终止支持""",
    "Japanese": """
   garbage collection         → ガベージコレクション
   machine learning           → 機械学習
   deep learning              → 深層学習 / ディープラーニング
   backward-compatible        → 後方互換 / 下位互換
   top ten                    → トップ10
   plain English              → 平易な英語
   open source                → オープンソース
   high-level language        → 高水準言語
   library                    → ライブラリ
   framework                  → フレームワーク
   release                    → リリース
   end-of-life                → サポート終了""",
}


def _glossary_for(target: str, source_text: str = "") -> str:
    """Return the relevant glossary for the target language.

    Domain-aware: if a source_text is provided, ONLY include glossary entries
    whose English key actually appears in the source. This prevents the
    programming-domain glossary (which is what most user-extended glossaries
    end up being) from poisoning translations of literary, legal, medical,
    or other non-programming text.

    Without this filter, a literary Russian passage gets a system prompt
    full of "programming language", "standard library", "garbage collection"
    mappings — and the small LLM dutifully sprinkles them into the output
    even though none of those concepts are in the source.

    Priority: translation_memory (data/translations/glossaries/<lang>.json) →
              built-in GLOSSARIES dict → empty.
    """
    tm_gloss = load_glossary(target)
    if tm_gloss:
        if source_text:
            src_low = " " + source_text.lower() + " "
            relevant = {
                k: v for k, v in tm_gloss.items()
                if k.lower() in src_low or any(
                    part in src_low for part in k.lower().split() if len(part) >= 5
                )
            }
            if not relevant:
                return ""        # no programming terms in literary text → no glossary
            return format_glossary_for_prompt(relevant, max_terms=60)
        return format_glossary_for_prompt(tm_gloss, max_terms=60)
    # Fall back to static built-in (these are also tech-domain, so apply the
    # same domain filter when source_text is present)
    builtin = GLOSSARIES.get(target.title(), "")
    if builtin and source_text:
        src_low = source_text.lower()
        # Built-in glossaries are formatted as text blocks. Only return them
        # if the source contains at least one obvious tech keyword.
        tech_markers = ("python", "programming", "language", "library", "framework",
                         "code", "function", "compile", "runtime", "object",
                         "программирован", "библиотек", "функци", "код", "компил")
        if any(m in src_low for m in tech_markers):
            return builtin
        return ""
    return builtin


def _tier_for(target: str) -> int:
    """Return the effective quality tier for the target language.

    If we have curated examples in translation_memory, the tier is upgraded —
    because the few-shot injection significantly improves output quality even
    for languages the base model wouldn't otherwise handle well.
    """
    base = LANGUAGE_TIERS.get(target.lower(), 2)
    # Check if we have substantial training data
    tm_stats = available_languages()
    key = re.sub(r"[^a-z]", "", target.lower())
    stats = tm_stats.get(key, {})
    has_glossary = stats.get("gloss", 0) >= 15
    has_examples = stats.get("examples", 0) >= 10
    # If we have BOTH glossary AND examples, upgrade tier by 1 (max upgrade to tier 1)
    if has_glossary and has_examples:
        return max(1, base - 1)
    return base


_TRANSLATE_SYSTEM_TEMPLATE = """You are a professional translator producing native-quality {target} output.

═══════════════════════════════════════════════════════════════════════
ABSOLUTE RULES (violations make the output unusable)
═══════════════════════════════════════════════════════════════════════

1. NO CODE-SWITCHING. Translate EVERY non-technical English word into {target}.
   The ONLY English allowed in the output:
     • Proper nouns (company / product / framework / person names) — KEEP AS-IS
       (e.g. "Python Software Foundation" stays "Python Software Foundation",
        NOT translated to "Foundation of Python Software" in any language)
     • Globally-standard acronyms: API, HTTP, JSON, URL, CPU, GPU, SQL, HTML, CSS, JS
     • Code identifiers inside `code spans` or fenced ```code``` blocks
   Everything else MUST be in {target}.

2. SCRIPT CONSISTENCY. Use ONLY the standard script for {target}.
   ❌ NEVER mix Cyrillic and Latin letters in the same word.
   ❌ NEVER mix scripts (e.g. Russian Т vs Latin T — they look identical but
      they are different characters. Always use the script of {target}.)
   If {target} uses Cyrillic: every letter in non-English words must be Cyrillic.
   If {target} uses Latin: every letter in non-English words must be Latin.

3. GRAMMAR AGREEMENT MUST BE CORRECT.
   • Romance/Slavic languages: adjectives agree with nouns in gender + number.
   • Slavic languages: verbs agree with subject in person + number + tense.
   • Word order must be natural for {target}, not a literal word-by-word transposition.

4. PROPER NOUNS DO NOT TRANSLATE.
   Company / product / framework / person names stay in English.
   ❌ WRONG: "Foundation Software Python" / "Software Python Foundation"
   ✅ RIGHT: "Python Software Foundation" (unchanged from English)

5. TIME REFERENCES MUST BE PRECISE.
   "late 1980s"   → "fin des années 1980" (FR) / "конец 1980-х" (RU)
                    NOT "early/début" or "middle/середина"
   "early 1990s"  → "début des années 1990" / "начало 1990-х"
   In Russian/French/etc., decades have NO trailing "s" (no "1980s" — write "1980-е" / "1980").

6. NUMBERS AND IDIOMS:
   "top ten" means "the top ten" — translate as "the best 10" / "first 10" idiom,
   NOT as "first place among ten" or similar incorrect rephrasing.

7. TECHNICAL GLOSSARY for {target}:
{glossary}

8. OUTPUT FORMAT:
   • Output ONLY the translation. NO preamble, NO "Here's the translation:".
   • Preserve line breaks, markdown headings, bullet points, code fences.
   • Inside code fences: keep code unchanged; translate only comments.
   • Keep URLs and email addresses untouched.
   • Preserve citation markers like [38][39][47] as-is.

9. IF SOURCE IS ALREADY IN {target}: reply briefly "The source is already in {target}." and return it.
"""


def _build_system_prompt(target: str, source_text: str = "") -> str:
    """Build the per-translation system prompt with glossary + few-shot examples.

    If translation_memory has parallel examples for this language, inject the
    most-relevant ones to the source text as few-shot guidance. This is the
    main mechanism for improving low-resource languages: by feeding the model
    concrete examples of native-quality output, we sidestep its lack of native
    fluency training.
    """
    glossary = _glossary_for(target, source_text=source_text) or "   (No specific glossary — apply general native-fluency rules.)"
    base = _TRANSLATE_SYSTEM_TEMPLATE.format(target=target, glossary=glossary)

    # Inject relevant parallel examples if we have a curated corpus
    examples = find_relevant_examples(source_text, target, k=5)
    if examples:
        ex_block = format_examples_for_prompt(examples, target)
        base += "\n\n" + "═" * 70 + "\n" + ex_block + "\n" + "═" * 70 + "\n"
        base += (
            f"\nThe examples above show native-quality {target} translation. "
            f"Match their style, terminology, and grammar conventions closely."
        )

    # Per-language fluency rules — same body used in the polish pass.
    # Including them in the FIRST pass too means we catch issues without
    # waiting for the polish round.
    extra = _LANG_POLISH_RULES.get(target.title(), "")
    if extra:
        base += "\n\n" + extra
    return base


# Tier-3 warning prepended to output when the model is likely to struggle
_TIER3_DISCLAIMER_TEMPLATE = (
    "> ⚠️ **Quality warning**: {target} is a low-resource language for this local model.\n"
    "> The translation below may contain errors, mixed scripts, or unnatural phrasing.\n"
    "> For professional-quality {target} translation, consider a specialized service.\n\n"
)


_TRANSLATE_USER = """TASK: Translate the source text below into {target}.

DO NOT:
  • Return the source text unchanged
  • Add a preamble like "Here is the translation:"
  • Explain or comment
  • Repeat the same sentence or paragraph more than once
  • Continue generating after you have produced the complete translation —
    STOP as soon as the {target} version is finished.

DO:
  • Output ONLY the {target} translation, nothing else.
  • Use the {target} script throughout.
  • If the source has a typo or grammar issue, still translate the INTENDED meaning.
  • The source may be in any language (not necessarily English).

{instructions}

Source:
---
{source}
---

Now output the {target} translation ONCE and then stop:"""


# Second pass — only when reasoning is enabled. Catches the specific failure
# modes flagged in real-world testing: code-switching, grammar agreement,
# mistranslated proper nouns, mixed scripts, factual translation errors.
_POLISH_SYSTEM_TEMPLATE = """You are a native {target} editor reviewing a draft translation. Your job is to FIX every issue, then output ONLY the polished version.

CHECK FOR AND FIX:
1. CODE-SWITCHING: any English word/phrase that should have been translated.
   Allowed English: proper nouns, API/HTTP/JSON-style acronyms, code inside fences.
   Examples of WRONG patterns to fix:
     "ease d'écriture"     → "facilité d'écriture"
     "plain English"       → "anglais clair"  (FR) / "простой английский" (RU)
     "backward-compatible" → "rétrocompatible" / "обратно совместимый"

2. MIXED SCRIPTS: in scripts like Cyrillic, every letter of a Russian word must be
   Cyrillic. Latin "T" instead of Cyrillic "Т" in "ТIOBE" → WRONG, fix to all-Latin
   "TIOBE" (it's a proper noun) or all-Cyrillic if translated.

3. GRAMMAR AGREEMENT (case/gender/number/person/tense):
   ❌ "une bibliothèque extensives"  → ✅ "une bibliothèque extensive"
   ❌ "позволяющие опциональной"      → ✅ "позволяющие опциональную"

4. PROPER NOUNS: company / product / person names stay in English.
   ❌ "La Fondation Software Python" / "Фонд программного обеспечения Python"
   ✅ "La Python Software Foundation" / "Python Software Foundation"

5. TIME REFERENCES:
   ❌ "début des années 1980s"  (wrong meaning + trailing s)
   ✅ "fin des années 1980"     (late, no trailing s)
   ❌ "1980-х годов"  (incorrect — "конец 1980-х годов" if "late")
   ✅ "конец 1980-х годов"

6. NUMBER/IDIOM:
   ❌ "первое место среди десяти" (means "1st place among ten" — wrong!)
   ✅ "входит в первую десятку"   (correct idiom for "ranks in the top ten")

7. TECH TERMINOLOGY — use the standard native term. Glossary:
{glossary}

8. AWKWARD WORD ORDER: reorder for natural {target} flow.

9. HALLUCINATED CONTENT: if the draft added sentences not in the source, REMOVE them.

OUTPUT: just the polished translation in {target}. No preamble. No "I fixed X" commentary.
If the draft is already clean, return it unchanged.
"""


# Language-specific polish rules — appended to the universal polish prompt.
# These catch the exact failure modes we've observed in real testing.
_LANG_POLISH_RULES: dict[str, str] = {
    "Uzbek": """
SPECIFIC UZBEK FLUENCY RULES:
1. POSSESSIVE CASE: when a noun is "X of Y" or "Y's X", use possessive -i/-si suffix
   ❌ "soddalikini"   (mixed double-suffix)
   ✅ "soddaligini"   (possessive -i + accusative -ni → -igi-ni)
   ❌ "kodini o'qilishi"
   ✅ "kodning o'qilishi"   (kodning = genitive of kod)

2. SENTENCE SPLITTING for long English sentences:
   Long English sentences with multiple emphases should be split into 2-3 natural
   Uzbek sentences connected with "Bunda", "Bu bilan", "Shu sababli", "U", etc.
   Direct word-for-word transposition produces unnatural English-shaped Uzbek.
   ❌ "Python kod o'qilishini ... orqali ta'minlashga e'tibor qaratadi, ... orqali"
       (one giant comma-spliced English-style sentence)
   ✅ "Python kodning o'qilishi, soddaligi va yozish qulayligiga urg'u beradi.
       Bunda indentatsiya, oddiy inglizcha nomlash va keng standart kutubxona
       qo'llaniladi."
       (two natural Uzbek sentences with "Bunda" connector)

3. PREFERRED TECHNICAL TERMS (use these even if dictionary suggests otherwise):
   indentation                  → indentatsiya  (NOT "muhim chekinishlar")
   garbage collection           → garbage collection / xotirani avtomatik boshqarish
   has automatic memory mgmt    → xotirani avtomatik boshqarish imkoniyatiga ega
   Don't end a sentence with a dangling "orqali" (through/via) — complete it with
   "imkoniyatiga ega" or "boshqaradi" or another verb.

4. AGGLUTINATIVE MORPHOLOGY: when stacking suffixes, follow vowel harmony:
   • Soft vowels (e, i, o, u after soft consonants): -gi, -gini, -ga
   • The accusative -ni attaches to the possessive -i: -ini  (not -nini)
   ❌ "yozish qulayligini" → fine
   ❌ "kod o'qilishi" + accusative → "kodning o'qilishini"  (genitive + possessive + accusative)

5. AVOID OVER-LITERAL CONSTRUCTIONS:
   "with the use of X" → "X dan foydalanib" / "X yordamida" (NOT "X ning ishlatilishi bilan")
   "in order to" → "uchun" (NOT "tartibida")
   "such as" → "kabi" / "masalan" (NOT "shunday narsalar")
""",

    "Russian": """
SPECIFIC RUSSIAN FLUENCY RULES:
1. Word order: Russian allows free word order; use the natural emphasis pattern,
   not English SVO transposition.
2. Cases: ensure nominative/accusative/genitive agreement.
   ❌ "позволяющие опциональной"  → ✅ "позволяющие опциональную"
3. Number agreement on verbs: plural subject → plural verb.
4. Avoid stiff calques: "Стартуя с" is unnatural; use "Начиная с".
5. "1980s" → "1980-е годы" (NEVER with trailing "s").
6. Idiomatic numerical phrasing: "top ten" → "первая десятка" (NOT "первое место среди десяти").
""",
}


def _build_polish_prompt(target: str, source_text: str = "") -> str:
    glossary = _glossary_for(target, source_text=source_text) or "   (Apply general native-fluency rules for this language.)"
    base = _POLISH_SYSTEM_TEMPLATE.format(target=target, glossary=glossary)
    extra = _LANG_POLISH_RULES.get(target.title(), "")
    if extra:
        base += "\n\n" + extra
    return base

_POLISH_USER = """Original source ({target} target language):
---
{source}
---

Draft translation to review:
---
{draft}
---

Output the polished {target} version only."""


# ── Back-translation verification before corpus save ─────────────────────
async def _verify_and_save(source_text: str, translation: str, target: str,
                            src_lang: str, domain: str, model: str) -> None:
    """Save (source, translation) to the corpus ONLY if a round-trip preserves
    meaning. Runs in background — does not block the user response.

    Verification: translate `translation` back to `src_lang` via NLLB, then
    compute character-level similarity to the original source. If the
    similarity is high enough, the translation is faithful and we save.
    Otherwise we discard silently (no corpus pollution, no user noise).

    This is the difference between "auto-train on everything" (dangerous —
    bad outputs reinforce themselves) and "auto-train only on what we can
    verify" (safe — only meaning-preserving translations enter memory).
    """
    try:
        from core.translators import nllb_translate as _nllb
        back = await _nllb(translation, target=src_lang, source=target.lower())
        if not back:
            _log(f"verify: back-translation empty, skipping save")
            return

        sim = _char_similarity(source_text, back)
        _log(f"verify: back-translation similarity={sim:.2f} ({src_lang} ↔ {target})")
        # Empirical thresholds based on trigram Jaccard:
        #   <0.30 = round-trip drifted to unrelated content (reject)
        #   0.30-0.45 = same topic but lossy (save with moderate confidence)
        #   >0.45 = faithful round-trip (save with high confidence)
        # Unrelated text scores ~0.01; faithful translations score ~0.40-0.55.
        if sim < 0.30:
            _log(f"verify: REJECTED save (similarity {sim:.2f} < 0.30)")
            return
        confidence = 0.95 if sim >= 0.45 else 0.80
        append_example(source_text, translation, target,
                        source_lang=src_lang, domain=domain,
                        confidence=confidence)
        _log(f"verify: SAVED to corpus (confidence={confidence:.2f}, domain={domain})")
    except Exception as e:
        _log(f"verify: exception during back-check: {type(e).__name__}: {e}")


def _char_similarity(a: str, b: str) -> float:
    """Crude meaning-similarity proxy: shingled bigram Jaccard on letters.

    Good enough to catch "round-trip preserved most content" vs. "round-trip
    drifted into different territory". Doesn't require an embedding model.
    """
    import re as _re
    norm_a = _re.sub(r"[^\w]", "", a.lower())
    norm_b = _re.sub(r"[^\w]", "", b.lower())
    if len(norm_a) < 10 or len(norm_b) < 10:
        return 0.0
    grams_a = {norm_a[i:i+3] for i in range(len(norm_a) - 2)}
    grams_b = {norm_b[i:i+3] for i in range(len(norm_b) - 2)}
    if not grams_a or not grams_b:
        return 0.0
    return len(grams_a & grams_b) / len(grams_a | grams_b)


# ── Repetition detector for streaming output ──────────────────────────────
# Small models on low-resource targets often degenerate into a paragraph loop
# (same 3-4 sentences regenerated until num_predict is exhausted). We watch
# the rolling tail of the stream for self-similarity and break out early.
def _looks_repetitive(text: str) -> bool:
    """True if the tail of `text` shows clear repetition (an entire chunk repeats)."""
    if len(text) < 400:
        return False
    tail = text[-1200:]
    # Check for an identical block of ≥150 chars appearing 3+ times in the tail.
    # We bucket on a normalized 150-char slab and count occurrences.
    slab = tail[-200:].strip()
    if len(slab) < 80:
        return False
    # Count how many times the last 120-char window appears in the full text.
    needle = text[-160:-40].strip()
    if len(needle) < 60:
        return False
    occurrences = text.count(needle)
    return occurrences >= 3


# Ollama inference options shared by all translation generations.
# repeat_penalty + repeat_last_n make degenerate loops much less likely.
_INFER_OPTS = {
    "num_predict": 1500,
    "temperature": 0.2,
    "num_ctx": 8192,
    "repeat_penalty": 1.3,
    "repeat_last_n": 256,
    "stop": ["\n---\n---", "\n\n---\n\n---", "</translation>"],
}


# ── Output validation: did the model actually translate? ───────────────────
def _is_translation_failure(source: str, draft: str, target: str) -> tuple[bool, str]:
    """Detect when the model returned the source language instead of translating.

    Heuristics:
      • Output is essentially identical to source → failure
      • Output is mostly ASCII when target uses a non-Latin script → failure
      • Output for Latin-script target has zero shared words with high-frequency
        target-language words → suspicious (skipped here, would need wordlists)

    Returns: (is_failure, reason)
    """
    src = (source or "").strip().lower()
    drf = (draft or "").strip()
    drf_low = drf.lower()

    if not drf:
        return True, "Empty output"

    # 1. Output is the source verbatim (or near-verbatim)
    if src and (drf_low == src or drf_low.replace(' a ', ' ').replace(' the ', ' ') == src.replace(' a ', ' ').replace(' the ', '')):
        return True, "Output is the source unchanged"
    # Token-level near-identity — but only meaningful if the source has
    # enough Latin tokens to compute a real ratio. Skipping this when the
    # source is mostly non-Latin (e.g. Russian Cyrillic with just a stray
    # English word) avoids false positives like {"uzbek"} matching the
    # word "uzbek" anywhere in the output.
    src_tokens = set(re.findall(r"[a-z]{3,}", src))
    drf_tokens = set(re.findall(r"[a-z]{3,}", drf_low))
    if len(src_tokens) >= 5 and len(src_tokens & drf_tokens) / len(src_tokens) > 0.85:
        return True, "Output is >85% the same English words as the source"

    # 2. Target uses non-Latin script but output is mostly ASCII → didn't translate
    NON_LATIN = {"russian", "ukrainian", "bulgarian", "serbian", "kazakh", "kyrgyz",
                 "mongolian", "chinese", "mandarin", "japanese", "korean", "arabic",
                 "hebrew", "urdu", "persian", "hindi", "bengali", "tamil", "telugu",
                 "gujarati", "greek", "armenian", "georgian", "thai", "khmer",
                 "lao", "burmese"}
    if target.lower() in NON_LATIN:
        ascii_chars = sum(1 for c in drf if ord(c) < 128 and c.isalpha())
        non_ascii   = sum(1 for c in drf if ord(c) >= 128)
        total_letters = ascii_chars + non_ascii
        if total_letters > 20 and non_ascii / total_letters < 0.4:
            return True, f"Target ({target}) uses non-Latin script but output is mostly ASCII"

    return False, ""


_RETRY_USER = """The previous attempt returned the source unchanged. That is WRONG.

You MUST translate from English into {target}.

Output ONLY the {target} translation. Use the {target} script throughout.

English source:
{source}

{target} translation:"""


async def _retry_translation(target: str, source: str, model: str) -> str:
    """Second attempt with a stripped-down, very explicit prompt."""
    msgs = [
        {"role": "system", "content": (
            f"You translate English into {target}. Output ONLY the {target} translation. "
            f"Never repeat the English source. Never explain. Just the translation."
        )},
        {"role": "user",   "content": _RETRY_USER.format(target=target, source=source)},
    ]
    try:
        return (await generate(
            msgs, model=model,
            options={**_INFER_OPTS, "temperature": 0.3, "num_ctx": 4096},
        )).strip()
    except Exception:
        return ""


async def _polish_translation(
    target: str,
    source: str,
    draft: str,
    model: str,
) -> str:
    """Run the polish pass and return the cleaned-up translation."""
    msgs = [
        {"role": "system", "content": _build_polish_prompt(target, source_text=source)},
        {"role": "user",   "content": _POLISH_USER.format(target=target,
                                                            source=source[:4000],
                                                            draft=draft[:5000])},
    ]
    try:
        return (await generate(
            msgs, model=model,
            options={**_INFER_OPTS, "temperature": 0.15},
        )).strip()
    except Exception:
        return draft   # fall back to draft if polish fails


class TranslationSkill(Skill):
    name        = "translation"
    label       = "Translation"
    description = "Translates text or web pages between languages"
    priority    = 9    # before file_generation (10) so "translate this and save as PDF" routes here first

    def matches(self, ctx: SkillContext) -> bool:
        _ensure_compiled()
        # Must have a clear translation verb / target-language phrase
        if not _TRIGGER_RE.search(ctx.query):
            return False
        # Defer to file_generation when the user is asking for a downloadable
        # file. "Translate ... and save as PDF" / "generate a pdf with the
        # translation" → that's file_generation's job (it already knows how
        # to call NLLB per block and emit a bilingual PDF).
        try:
            from core.skills.file_generation import _detect_format
            if _detect_format(ctx.query) is not None:
                return False
        except Exception:
            pass
        return True

    async def execute(self, ctx: SkillContext) -> AsyncIterator[SkillEvent]:
        query = ctx.query
        target = _detect_target_lang(query) or "English"

        # If the query contains a URL, fetch the page and translate the content
        urls = _extract_explicit_urls(query)
        source_text = ""
        url_used = None

        if urls:
            url_used = urls[0]
            yield SkillEvent(kind="status", content={
                "skill": self.name, "label": self.label,
                "stage": "fetching", "url": url_used, "target": target,
            })
            kind, content, _ = await fetch_smart(url_used)
            # fetch_smart already filters error/nav-only pages, but double-check
            # that we have substantive content before translating navigation junk.
            if not content or len(content.strip()) < 400:
                yield SkillEvent(kind="answer_chunk", content=(
                    f"I tried to fetch {url_used} but couldn't retrieve substantive content "
                    f"to translate. Possible reasons:\n\n"
                    f"- The page is paywalled, JavaScript-heavy, or behind authentication\n"
                    f"- The URL is incorrect or the page no longer exists\n"
                    f"- The server returned only navigation/menu text\n\n"
                    f"Try pasting the text you want translated directly, or use a different URL."
                ))
                yield SkillEvent(kind="done", content={"skill": self.name, "ok": False,
                                                        "reason": "no_substantive_content"})
                return
            source_text = content[:6000]
        else:
            # No URL — translate the literal text in the query, after stripping
            # the translation verb itself
            source_text = re.sub(
                r"^\s*(translate|convert)\s+(this|the\s+following|to|into|in)?\s*"
                r"(text|message|sentence|paragraph)?\s*[:\-]?\s*",
                "",
                query, flags=re.I,
            )
            # Also drop any trailing "to <language>" since we already extracted target
            source_text = _TARGET_LANG_RE.sub("", source_text).strip()
            # Strip a leading bare-language prefix like "uzbek:" or "uzbek -"
            # left over from queries like "translate into uzbek: <text>". If
            # we leave it in, NLLB echoes the prefix into its output and the
            # validator rejects the result as "source-matched".
            _lang_alt = "|".join(re.escape(n) for n in LANGUAGE_TIERS.keys())
            source_text = re.sub(
                rf"^\s*(?:{_lang_alt})\s*[:\-–—]?\s*",
                "", source_text, flags=re.I,
            ).strip()
            if not source_text or len(source_text) < 4:
                yield SkillEvent(kind="answer_chunk",
                                  content="What text would you like translated? Paste it after your translation request, "
                                           "or give me a URL to translate.")
                yield SkillEvent(kind="done", content={"skill": self.name, "ok": False})
                return

        yield SkillEvent(kind="status", content={
            "skill": self.name, "stage": "synthesizing",
            "target": target, "chars": len(source_text),
        })

        # ── NLLB primary path ──────────────────────────────────────────────
        # NLLB-200 actually knows the 200+ languages it covers, including the
        # tier-3 ones (Uzbek, Kazakh, Tajik, Swahili, ...) where small local
        # LLMs hallucinate. Try NLLB first; fall back to the LLM path only
        # if the language isn't covered or the model isn't installed.
        #
        # We deliberately do NOT run the small-LLM polish pass on NLLB output.
        # NLLB is a dedicated translation model and beats any 7B general LLM
        # on quality. The "polish" pass uses a programming-domain glossary,
        # so when fed literary or academic text it injects irrelevant terms
        # like "kodning yozish qulayligi" (ease of writing code) into the
        # translation. Trust NLLB; don't second-guess it.
        nllb_used = False
        nllb_supported_lang = target.lower() in nllb_supported()
        nllb_libs_ok = nllb_available()
        nllb_error_detail = ""
        _log(f"target={target!r} nllb_supports_lang={nllb_supported_lang} nllb_libs_ok={nllb_libs_ok}")

        if nllb_supported_lang and nllb_libs_ok:
            t0 = time.time()
            try:
                src_lang = detect_source_language(source_text)
                _log(f"NLLB: translating {len(source_text)} chars, {src_lang} → {target}")
                yield SkillEvent(kind="status", content={
                    "skill": self.name, "stage": "nllb_translating",
                    "target": target, "source_lang": src_lang,
                    "chars": len(source_text),
                })
                translated = await nllb_translate(source_text, target=target, source=src_lang)
                dt = time.time() - t0
                _log(f"NLLB: done in {dt:.2f}s, {len(translated)} chars out")

                val_failure, val_reason = _is_translation_failure(source_text, translated, target)
                if translated and not val_failure:
                    nllb_used = True

                    # Domain-aware post-processing: rewrite NLLB's general-
                    # register vocabulary to the preferred domain term
                    # (e.g. "san'at asari" → "badiiy asar" for literature).
                    # Loaded from data/translations/glossaries/<lang>_<domain>.json.
                    src_domain = _classify_domain(source_text)
                    final = apply_domain_rewrites(translated, target, src_domain)
                    if final != translated:
                        _log(f"NLLB: applied {src_domain}-domain rewrites "
                              f"({len(translated)} → {len(final)} chars)")

                    yield SkillEvent(kind="answer_chunk", content=final)

                    # Grow the translation memory corpus — but ONLY after a
                    # back-translation similarity check, not blindly. We
                    # translate the output back to the source language and
                    # compare to the original. If they're meaningfully
                    # similar, the round-trip preserved meaning; if not, we
                    # skip saving (better an empty corpus than a wrong one).
                    #
                    # Runs in the background after we've already sent the
                    # translation to the user, so it doesn't add user-visible
                    # latency.
                    import asyncio as _asyncio
                    _asyncio.create_task(_verify_and_save(
                        source_text, final, target, src_lang, src_domain, ctx.model
                    ))

                    if url_used:
                        yield SkillEvent(kind="citations", content={
                            "sources": [{"n": 1, "title": "Source page",
                                          "url": url_used, "snippet": source_text[:160]}],
                        })
                    yield SkillEvent(kind="done", content={
                        "skill": self.name, "ok": True, "target": target,
                        "chars": len(source_text), "from_url": bool(url_used),
                        "engine": "nllb-200",
                        "polished": False,
                        "source_lang": src_lang,
                    })
                    return
                else:
                    nllb_error_detail = (
                        f"validator rejected output (reason: {val_reason!r}; "
                        f"output preview: {translated[:120]!r})"
                    )
                    _log(f"NLLB: output rejected — {nllb_error_detail}")
            except Exception as e:
                import traceback
                tb = traceback.format_exc(limit=4)
                nllb_error_detail = f"{type(e).__name__}: {e}"
                _log(f"NLLB: EXCEPTION {nllb_error_detail}\n{tb}")
                yield SkillEvent(kind="status", content={
                    "skill": self.name, "stage": "nllb_fallback",
                    "error": nllb_error_detail,
                })

            # NLLB is available for this language but produced no usable output.
            # We REFUSE to silently fall back to the LLM path here, because for
            # tier-3 languages the LLM produces domain-contaminated garbage that
            # looks confident but is wrong. Better to tell the user.
            yield SkillEvent(kind="answer_chunk", content=(
                f"⚠️ **NLLB translator failed.** Refusing to fall back to the "
                f"local LLM for {target} (it would hallucinate programming-domain "
                f"vocabulary on literary text).\n\n"
                f"**Exact error:** `{nllb_error_detail or '(no detail captured)'}`\n\n"
                f"Full trace in `translation_debug.log` at the repo root."
            ))
            yield SkillEvent(kind="done", content={
                "skill": self.name, "ok": False, "target": target,
                "reason": "nllb_failed_no_safe_fallback",
            })
            return
        else:
            _log(f"NLLB not used for {target} — falling back to LLM path "
                 f"(supports_lang={nllb_supported_lang}, libs_ok={nllb_libs_ok})")

        instructions = (
            f"Translate the following text to {target}." +
            (f" The text was fetched from {url_used}." if url_used else "")
        )

        # Build a language-specific system prompt with relevant few-shot examples
        # pulled from the translation memory (data/translations/).
        system_prompt = _build_system_prompt(target, source_text=source_text)
        tier = _tier_for(target)

        # For low-resource languages, prepend a quality warning so the user
        # knows the output may be imperfect.
        if tier >= 3:
            yield SkillEvent(kind="answer_chunk",
                              content=_TIER3_DISCLAIMER_TEMPLATE.format(target=target))

        # First pass — produce the draft translation.
        # When reasoning is OFF: we stream directly to the user.
        # When reasoning is ON: we collect silently into a draft, run a polish
        # pass, then stream the polished version.
        draft = ""
        if ctx.use_reasoning:
            yield SkillEvent(kind="status", content={
                "skill": self.name, "stage": "generating", "index": 0, "total": 1,
                "title": f"draft → {target}", "complex": True, "fmt": "",
            })
            draft_msgs = [
                {"role": "system", "content": system_prompt},
                {"role": "user",   "content": _TRANSLATE_USER.format(
                    instructions=instructions, source=source_text, target=target,
                )},
            ]
            async for tok in llm_stream(
                draft_msgs, model=ctx.model, options=_INFER_OPTS,
            ):
                draft += tok
                yield SkillEvent(kind="status", content={
                    "skill": self.name, "stage": "task_thinking_delta", "index": 0,
                    "title": f"draft → {target}", "delta": tok,
                })
                if _looks_repetitive(draft):
                    # Model fell into a paragraph loop — cut it off and trim
                    # the trailing repeated tail so the polish pass sees a
                    # clean draft.
                    draft = draft[: -len(draft) // 4].rstrip() + "\n"
                    break
            yield SkillEvent(kind="status", content={
                "skill": self.name, "stage": "task_thinking_done", "index": 0,
                "title": f"draft → {target}", "thinking": draft,
            })

            # Polish pass — fix code-switching, grammar, proper nouns, etc.
            yield SkillEvent(kind="status", content={
                "skill": self.name, "stage": "task_content_delta", "index": 0,
                "title": f"polishing → {target}", "delta": "",
            })
            polished = await _polish_translation(target, source_text, draft, ctx.model)

            # Failure detection — did the polished output actually translate?
            failure, reason = _is_translation_failure(source_text, polished, target)
            if failure:
                retry = await _retry_translation(target, source_text, ctx.model)
                fail2, _ = _is_translation_failure(source_text, retry, target)
                if retry and not fail2:
                    polished = retry
                else:
                    polished += (
                        f"\n\n*(Note: the model couldn't produce a confident {target} translation. "
                        f"Submit a correction via 'Suggest better' so future similar requests work.)*"
                    )

            yield SkillEvent(kind="answer_chunk", content=polished)
            yield SkillEvent(kind="status", content={
                "skill": self.name, "stage": "task_complete", "index": 0,
                "title": f"polished → {target}",
            })
        else:
            # Single-pass: collect output silently so we can detect failure + retry
            draft_msgs = [
                {"role": "system", "content": system_prompt},
                {"role": "user",   "content": _TRANSLATE_USER.format(
                    instructions=instructions, source=source_text, target=target,
                )},
            ]
            collected = ""
            stopped_early = False
            async for tok in llm_stream(
                draft_msgs, model=ctx.model, options=_INFER_OPTS,
            ):
                collected += tok
                yield SkillEvent(kind="answer_chunk", content=tok)
                if _looks_repetitive(collected):
                    stopped_early = True
                    break
            if stopped_early:
                # Trim the looping tail so the user doesn't see N copies of the
                # same paragraph, then signal the cut-off.
                yield SkillEvent(kind="answer_chunk", content=(
                    "\n\n*(Output stopped — the model started repeating itself. "
                    "This is common for low-resource target languages.)*"
                ))

            # Failure detection — did the model actually translate?
            failure, reason = _is_translation_failure(source_text, collected, target)
            if failure:
                # Try once more with a stripped-down prompt
                yield SkillEvent(kind="answer_chunk", content=(
                    f"\n\n*(Detected translation failure: {reason}. Retrying with a simpler prompt…)*\n\n"
                ))
                retry = await _retry_translation(target, source_text, ctx.model)
                if retry:
                    fail2, _ = _is_translation_failure(source_text, retry, target)
                    if not fail2:
                        yield SkillEvent(kind="answer_chunk",
                                          content=f"**Retry result:**\n\n{retry}")
                    else:
                        yield SkillEvent(kind="answer_chunk", content=(
                            f"The model couldn't produce a {target} translation for this input. "
                            f"It may not have enough {target} training data for this phrase. "
                            f"Consider using a more popular target language, or submit a correction "
                            f"via 'Suggest better' so future similar requests work."
                        ))

        if url_used:
            yield SkillEvent(kind="citations", content={
                "sources": [{"n": 1, "title": "Source page", "url": url_used, "snippet": source_text[:160]}],
            })

        yield SkillEvent(kind="done", content={
            "skill": self.name, "ok": True, "target": target,
            "chars": len(source_text), "from_url": bool(url_used),
            "polished": ctx.use_reasoning, "language_tier": tier,
        })
