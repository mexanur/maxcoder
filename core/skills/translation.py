"""
TranslationSkill — Level 1 capability (translate text or web pages).

Detects translation intent and routes through a focused prompt that:
  - Returns clean translation (no preamble, no commentary)
  - Preserves formatting / code blocks
  - Honors the user's thinking toggle for tricky / nuanced translation
"""
from __future__ import annotations
import re
from typing import AsyncIterator

from core.skills.base import Skill, SkillContext, SkillEvent
from core.skills._synthesize import synthesize
from core.web_navigator    import fetch_smart
from core.skills.web_fetch import _extract_explicit_urls
from core.generator        import generate, stream as llm_stream
from core.translation_memory import (
    load_glossary, format_glossary_for_prompt,
    find_relevant_examples, format_examples_for_prompt,
    available_languages,
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
    _TRIGGER_RE = re.compile(
        rf"\b(translate|translation|"
        rf"how\s+do\s+(?:you|i)\s+say|how\s+to\s+say|what\s+does\s+\".+\"\s+mean|"
        rf"in\s+(?:{lang_alt})|"
        rf"convert\s+(?:this|it)\s+to)\b",
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


def _glossary_for(target: str) -> str:
    """Return the relevant glossary for the target language.

    Priority: translation_memory (data/translations/glossaries/<lang>.json) →
              built-in GLOSSARIES dict → empty.
    """
    # First check translation memory (user-extensible)
    tm_gloss = load_glossary(target)
    if tm_gloss:
        return format_glossary_for_prompt(tm_gloss, max_terms=60)
    # Fall back to static built-in
    return GLOSSARIES.get(target.title(), "")


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
    glossary = _glossary_for(target) or "   (No specific glossary — apply general native-fluency rules.)"
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


_TRANSLATE_USER = """TASK: Translate the English source below into {target}.

DO NOT:
  • Return the English source (even with grammar corrections)
  • Add a preamble like "Here is the translation:"
  • Explain or comment

DO:
  • Output ONLY the {target} translation, nothing else.
  • Use the {target} script throughout.
  • If the source has a typo or grammar issue, still translate the INTENDED meaning.

{instructions}

English source:
---
{source}
---

Now output the {target} translation:"""


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


def _build_polish_prompt(target: str) -> str:
    glossary = _glossary_for(target) or "   (Apply general native-fluency rules for this language.)"
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
    # Token-level near-identity
    src_tokens = set(re.findall(r"[a-z]{3,}", src))
    drf_tokens = set(re.findall(r"[a-z]{3,}", drf_low))
    if src_tokens and len(src_tokens & drf_tokens) / max(len(src_tokens), 1) > 0.85:
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
            options={"num_predict": 1500, "temperature": 0.3, "num_ctx": 4096},
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
        {"role": "system", "content": _build_polish_prompt(target)},
        {"role": "user",   "content": _POLISH_USER.format(target=target,
                                                            source=source[:4000],
                                                            draft=draft[:5000])},
    ]
    try:
        return (await generate(
            msgs, model=model,
            options={"num_predict": 2000, "temperature": 0.15, "num_ctx": 8192},
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
        return bool(_TRIGGER_RE.search(ctx.query))

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
                draft_msgs, model=ctx.model,
                options={"num_predict": 2500, "temperature": 0.2, "num_ctx": 8192},
            ):
                draft += tok
                yield SkillEvent(kind="status", content={
                    "skill": self.name, "stage": "task_thinking_delta", "index": 0,
                    "title": f"draft → {target}", "delta": tok,
                })
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
            async for tok in llm_stream(
                draft_msgs, model=ctx.model,
                options={"num_predict": 2500, "temperature": 0.2, "num_ctx": 8192},
            ):
                collected += tok
                yield SkillEvent(kind="answer_chunk", content=tok)

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
