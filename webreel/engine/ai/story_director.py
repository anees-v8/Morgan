"""
Story Director: turns a Site Brief (the website's own content + screenshots) into a film plan.

    brief  --Gemini (vision + DOM text, structured JSON)-->  plan   (4 scenes, 3 cards, outro line)
    brief  --heuristics (no LLM)-------------------------->  plan   (used when there is no key / quota / on failure)

Whatever produced the plan, `finalize_plan` then enforces the rules the prompt only *asks* for:
labels must exist on the site, numbers must appear in the site's own text, lengths are bounded.
The result is always a usable plan; the journey never depends on the LLM being available.
"""
import asyncio
import difflib
import json
import logging
import re
from typing import Any, Dict, List, Optional, Tuple

from pydantic import BaseModel, Field

from ..config import config
from .gemini_client import GeminiClient
from .site_brief import _path

logger = logging.getLogger("webreel.story")


# ============================================================================ schema
class CardOut(BaseModel):
    category: str = Field(description="Short UPPERCASE label that fits this product, max 22 chars")
    title: str = Field(description="Benefit headline, max 32 chars")
    desc: str = Field(description="One sentence, max 90 chars, using the site's own facts")
    evidence: str = Field(description="Verbatim snippet from the site (or screenshot) that backs this card")


class SceneOut(BaseModel):
    scene_type: str = Field(description="one of: hero, feature, proof, pricing, cta")
    page: str = Field(description="The page the browser is on DURING this scene: 'Home', or the exact opened_by_clicking label of a sub-page (e.g. 'Pricing')")
    title: str = Field(description="On-screen concept label for the scene, max 42 chars")
    goal: str = Field(description="One sentence: what the viewer should understand after this scene")
    scroll_to: str = Field(description="EXACT heading text to scroll into view first, or empty string")
    focus_text: str = Field(description="EXACT heading/feature title the pointer rests on while narrating, or empty string")
    action: str = Field(description="'click' to press target_label at the end of the scene, otherwise 'none'")
    target_label: str = Field(description="EXACT label of a button/link/tab from evidence.actions, or empty string")
    say: str = Field(description="Narration for this scene, 26-34 words")
    card: int = Field(description="Which of the 3 cards (0,1,2) this scene proves")


class PlanOut(BaseModel):
    brand_name: str
    tagline: str = Field(description="Punchy line, max 70 chars, built from the site's own words")
    audience: str
    promise: str
    screenshot_text: List[str] = Field(description="Verbatim text snippets read from the screenshots (OCR) that you used")
    cards: List[CardOut]
    scenes: List[SceneOut]
    outro_say: str = Field(description="Closing line, max 16 words, says the web address naturally")


# ============================================================================ prompt
SYSTEM_PROMPT = r"""
You are the creative director and scriptwriter of a studio that makes 45-60 second product films from a real website. A narrator speaks over a screen recording while a mouse pointer moves and clicks on the site's own pages. Plan {N} scenes that let a stranger understand what this product does, who it is for and why they should try it, using ONLY what the website itself says.

WHAT YOU RECEIVE
1. EVIDENCE (JSON): the site's own headings with the text under each, its visible buttons/links/tabs (each with `kind` and `can_click`), prices and statistics with the sentence around them, and the text of its key sub-pages.
2. SCREENSHOTS of the same site (top of the home page, then further down). Read ALL text visible in them (OCR). Hero images and product mock-ups often contain the best proof (dashboard labels, numbers, feature names) that the DOM text lacks. If a screenshot and the DOM disagree, trust the DOM.

ABSOLUTE RULES
R1 GROUNDING. Every fact, number, price, percentage, feature name, audience or integration you write must appear in EVIDENCE or be readable in a screenshot. Never invent customers, awards, speeds, uptime, user counts or comparisons. If the site gives no number, use none. Write numbers exactly as the site does (an amount shown as ₹2,500 stays ₹2,500). List every snippet you used from screenshots, verbatim, in `screenshot_text`.
R2 EXACT REFERENCES. `target_label`, `scroll_to` and `focus_text` must be copied character-for-character from EVIDENCE (actions[].label or headings[].text), or be "" when nothing fits. Never paraphrase or shorten them.
R3 ONE BROWSER SESSION that starts on the home page. After a click that opens another page, later scenes happen on THAT page: their `scroll_to`/`focus_text` must come from that page's headings (listed under pages[]). Only `can_click: true` items are really clicked; a `can_click: false` item is shown as a press only (good for the final call to action).
R4 CHOOSE CHAPTERS THAT TELL THE STORY: a tab that changes the content, a Features/Product page, the Pricing page. Never choose Login, Sign up, Contact, Careers, legal pages or language switchers.
R5 ON-SCREEN TRUTH. In every scene the narration describes what the viewer SEES at that moment: the page the browser is on (set `page`), the section scrolled to, the element the pointer rests on. Track the browser: it starts on "Home"; after a scene ends with a real click that opens a sub-page, the NEXT scene's `page` is that sub-page and its narration must be about THAT page's content (e.g. after clicking Pricing, talk about plans and prices, not about features from the home page). A scene's `scroll_to` / `focus_text` / `target_label` must exist on its own `page`.
R6 NO ADDED CLAIMS. Do not add adjectives or promises the site does not make (risk-free, secure, instant, unlimited, guaranteed, best, fastest, trusted) unless that word or its clear equivalent is in the EVIDENCE. Describe what the product does and what it costs, in the site's own terms.

HOW TO WRITE (this is what makes it good)
- Voice: a sharp, friendly person explaining the product to one friend across a table. Second person ("you"), plain words, short spoken sentences (max ~14 words each). Contractions are fine. It must sound spoken, not like a brochure.
- Scene 1 (hook): open with the customer's problem or the single most striking promise on the page, in the site's own words. Do NOT open with "Meet X" or "Introducing X". Then one sentence saying what the product is. Say the product name once.
- Middle scenes (proof): ONE idea each. Name the exact thing on screen using the site's own vocabulary (a tab name, a feature heading), state the concrete outcome, then lead into the action ("Open Pricing.", "Switch to Teachers."). The click happens at the END of the scene's narration, so the last sentence should set it up.
- Last scene (decision): the plans/price/next step if the site shows them (real numbers only), otherwise the clearest benefit; it ends on the action the site wants (book a demo / start free), as a press.
- Vary rhythm and the first word of every scene. No scene may start with "With", "Whether", "From", "Imagine", "Introducing" or "Meet".
- BANNED: unlock, revolutionize, transform, effortless(ly), elevate, accelerate, ultimate, unparalleled, world-class, one-stop, reimagine, redefine, seamless(ly), game-changer, cutting-edge, state-of-the-art, next-level, supercharge, empower, leverage, robust, holistic, streamline, "in today's fast-paced world", "all-in-one solution", "take it to the next level", "built from the ground up", "like never before", "the future of".
- Length: each `say` is 26-34 words (about 11-14 seconds at 2.4 words per second). Count them. `outro_say` is at most 16 words and speaks the web address naturally ("campusweb dot co dot in").
- Cards: three benefit cards shown beside the video, ranked by importance for THIS audience. Each card is an OUTCOME the customer gets (time saved, money kept, mistakes avoided, work made easier), not a price or a feature list; at most one card may be about price. `category` = short uppercase label specific to this product (max 22 chars, e.g. "SAVES HOURS", "GET PAID FASTER"; never "FEATURE" or "BENEFIT"), `title` max 32 chars, `desc` max 90 chars, `evidence` = verbatim snippet from the site. Each scene's `card` (0,1,2) says which card it proves: scene 1 -> 0, then 1, 2, and the last scene -> 2.
- Pointer: `focus_text` makes the pointer rest on something the narrator is describing (use it in most scenes, never on decoration or empty image areas). `action: "click"` + `target_label` presses a control at the end of the scene. A scene may have both, one, or neither.
- Output language: {LANGUAGE}. Keep product names, prices and UI labels exactly as the site writes them.

STYLE REFERENCE (an invented product; copy the tone, never the content)
 scene 1: "Month-end shouldn't eat your weekend. LedgerLeaf reads your bank feed and books every transaction for you, so the dashboard is ready before your coffee is."
 scene 2: "Every invoice carries its own status, so you always know who still owes you. Open Reports and watch the whole month land on one page."

SELF-CHECK before answering: every number is in the evidence; every label is copied exactly and exists on that scene's `page`; the narration of each scene matches its `page`; no banned words or added claims; every `say` has 26-34 words; scenes differ in rhythm; scene 1 does not start with "Meet".
""".strip()


# ============================================================================ text utils
BANNED = re.compile(
    r"\b(unlock\w*|revolutioni[sz]\w*|revolution\w*|seamless\w*|game-?changer|cutting-edge|state-of-the-art|next-level|"
    r"supercharg\w*|empower\w*|leverag\w*|robust|holistic|streamlin\w*|transform\w*|effortless\w*|elevat\w*|"
    r"ultimate|unparalleled|world-class|one-stop|reimagin\w*|redefin\w*|accelerat\w*)\b", re.I)
_SENT = re.compile(r"(?<=[.!?])\s+")


def sentences(text: str) -> List[str]:
    return [s.strip() for s in _SENT.split((text or "").strip()) if s.strip()]


def word_count(text: str) -> int:
    return len((text or "").split())


def trim_to_words(text: str, limit: int) -> str:
    """Whole sentences up to `limit` words; if the first sentence is too long, cut at a clause boundary."""
    out, n = [], 0
    for s in sentences(text):
        w = word_count(s)
        if n + w > limit and out:
            break
        out.append(s)
        n += w
    res = " ".join(out) if out else (text or "").strip()
    if word_count(res) > limit:
        res = " ".join(res.split()[:limit]).rstrip(",;:-") + "."
    return res


def clip_chars(text: str, limit: int) -> str:
    text = re.sub(r"\s+", " ", (text or "").strip())
    if len(text) <= limit:
        return text
    cut = text[: limit - 1].rsplit(" ", 1)[0].rstrip(",;:-–— ")
    return cut + "…"


def spoken_host(host: str) -> str:
    return (host or "").replace("www.", "").replace(".", " dot ")


def _norm(s: str) -> str:
    return re.sub(r"[\s ]+", " ", (s or "").strip()).casefold()


_UNITS = {"zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9,
          "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15, "sixteen": 16,
          "seventeen": 17, "eighteen": 18, "nineteen": 19, "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50,
          "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90}
_SCALES = {"hundred": 100, "thousand": 1_000, "million": 1_000_000, "billion": 1_000_000_000}
_SUFFIX = {"k": 1_000, "m": 1_000_000, "b": 1_000_000_000, "thousand": 1_000, "million": 1_000_000, "billion": 1_000_000_000}


def _num_tokens(text: str) -> List[str]:
    return [t.replace(",", "") for t in re.findall(r"\d[\d,]*(?:\.\d+)?", text or "")]


def digit_values(text: str) -> List[float]:
    """Every number written with digits (20K+ -> 20000, 1.4M -> 1400000, 1,250 -> 1250), plus the raw figure."""
    out: List[float] = []
    for m in re.finditer(r"(\d[\d,]*(?:\.\d+)?)\s?(k|m|b|thousand|million|billion)?\b", text or "", re.I):
        try:
            v = float(m.group(1).replace(",", ""))
        except ValueError:
            continue
        out.append(v)
        if m.group(2):
            out.append(v * _SUFFIX[m.group(2).lower()])
    return out


def spoken_values(text: str) -> List[float]:
    """Numbers a narrator would SAY: 'twenty thousand' -> 20000, 'two hundred fifty' -> 250, 'ten' -> 10."""
    words = re.findall(r"[a-z]+", (text or "").lower())
    vals: List[float] = []
    cur, total, seen = 0, 0, False
    for w in words + [""]:
        if w in _UNITS:
            cur += _UNITS[w]
            seen = True
        elif w in _SCALES and seen:
            if w == "hundred":
                cur = max(cur, 1) * 100
            else:
                total += max(cur, 1) * _SCALES[w]
                cur = 0
        else:
            if seen:
                vals.append(float(total + cur))
            cur, total, seen = 0, 0, False
    return vals


def _same(a: float, b: float) -> bool:
    return abs(a - b) <= 1e-6 * max(1.0, abs(a), abs(b))


# ============================================================================ evidence
def _pack_page(b: Dict[str, Any], body_chars: int, n_headings: int = 34) -> Dict[str, Any]:
    return {
        "url": b["url"], "title": b["title"],
        "headings": [{"level": h["level"], "text": h["text"], "under": h["blurb"][:200]} for h in b["headings"][:n_headings]],
        "numbers": [{"value": n["value"], "context": n["context"]} for n in b["numbers"][:16]],
        "text_excerpt": b["body_text"][:body_chars],
    }


def _pack_actions(b: Dict[str, Any], limit: int, kinds: Optional[Tuple[str, ...]] = None) -> List[Dict[str, Any]]:
    out = []
    for a in b["actions"]:
        if not a.get("story_ok", True) or a["kind"] == "faq":
            continue
        if kinds and a["kind"] not in kinds:
            continue
        out.append({"label": a["label"], "kind": a["kind"], "can_click": a["can_click"],
                    "location": "navigation" if a.get("inNav") else "page"})
        if len(out) >= limit:
            break
    return out


def build_evidence(brief: Dict[str, Any]) -> Dict[str, Any]:
    home = _pack_page(brief, 3200)
    home["actions"] = _pack_actions(brief, 34)
    ev: Dict[str, Any] = {
        "brand_name_guess": brief["brand_name"], "web_address": brief["host"], "site_language": brief.get("lang", ""),
        "meta_description": brief["meta"].get("description", ""), "home": home, "pages": [],
    }
    for pg in brief.get("pages", []):
        p = _pack_page(pg, 1800, 24)
        p["opened_by_clicking"] = pg.get("via_label", "")
        p["actions"] = _pack_actions(pg, 10, ("cta", "tab"))
        ev["pages"].append(p)
    return ev


def _corpus(brief: Dict[str, Any], extra: List[str]) -> str:
    parts = [brief["body_text"], brief["title"], brief["meta"].get("description", "")]
    for b in [brief] + list(brief.get("pages", [])):
        parts += [b["body_text"], b["title"]]
        parts += [h["text"] + " " + h["blurb"] for h in b["headings"]]
        parts += [n["context"] for n in b["numbers"]]
    parts += extra
    return _norm(" ".join(parts))


# ============================================================================ resolution + enforcement
class _Resolver:
    def __init__(self, brief: Dict[str, Any], pages: Optional[List[Dict[str, Any]]] = None):
        self.brief = brief
        pages = pages if pages is not None else [brief] + list(brief.get("pages", []))
        self.headings = [h["text"] for b in pages for h in b["headings"]]
        self.actions = [a for b in pages for a in b["actions"] if a.get("story_ok", True) and a["kind"] != "faq"]

    @staticmethod
    def _closest(value: str, options: List[str], cutoff: float = 0.86) -> Optional[str]:
        if not value:
            return None
        nv = _norm(value)
        for o in options:
            if _norm(o) == nv:
                return o
        m = difflib.get_close_matches(nv, [_norm(o) for o in options], n=1, cutoff=cutoff)
        if m:
            for o in options:
                if _norm(o) == m[0]:
                    return o
        return None

    def heading(self, value: str) -> str:
        return self._closest(value, self.headings) or ""

    def action(self, value: str) -> Optional[Dict[str, Any]]:
        label = self._closest(value, [a["label"] for a in self.actions])
        if not label:
            return None
        cands = [a for a in self.actions if a["label"] == label]
        return sorted(cands, key=lambda a: (not a["can_click"], a["y"]))[0]


_CORPUS_NUMS: Dict[int, List[float]] = {}


def _corpus_numbers(corpus: str) -> List[float]:
    key = hash(corpus)
    if key not in _CORPUS_NUMS:
        if len(_CORPUS_NUMS) > 8:
            _CORPUS_NUMS.clear()
        _CORPUS_NUMS[key] = digit_values(corpus)
    return _CORPUS_NUMS[key]


def _enforce_grounding(say: str, corpus: str, report: List[str]) -> str:
    """Drop any sentence quoting a number (as digits OR words) that the site's own text does not contain."""
    nums = _corpus_numbers(corpus)
    kept = []
    for s in sentences(say):
        claimed = [v for v in digit_values(s) if v >= 10] + [v for v in spoken_values(s) if v >= 10]
        bad = [v for v in claimed if not any(_same(v, n) for n in nums)]
        if bad:
            report.append(f"dropped unsupported number(s) {[int(v) if v == int(v) else v for v in bad]}: {s[:70]}")
            continue
        kept.append(s)
    return " ".join(kept)


def finalize_plan(raw: Dict[str, Any], brief: Dict[str, Any], source: str) -> Dict[str, Any]:
    """Validate/normalise a plan from any source into the exact shape the pipeline consumes."""
    report: List[str] = []
    rs = _Resolver(brief)
    corpus = _corpus(brief, [t for t in (raw.get("screenshot_text") or []) if isinstance(t, str)])
    fallback = heuristic_plan(brief)
    union = rs
    current: Optional[Dict[str, Any]] = brief            # the page the browser is on as the story unfolds (None = unknown)

    def pool_resolver(page: Optional[Dict[str, Any]]) -> "_Resolver":
        return _Resolver(page, [page]) if page is not None else union

    # ---- cards (exactly 3)
    cards = []
    for c in (raw.get("cards") or [])[:3]:
        title, desc = clip_chars(c.get("title", ""), 32), clip_chars(c.get("desc", ""), 90)
        if not title or not desc:
            continue
        if (digit_values(title) or spoken_values(title)) and not _enforce_grounding(title, corpus, report):
            title = clip_chars(fallback["cards"][min(len(cards), 2)]["title"], 32)
        if digit_values(desc) or spoken_values(desc):
            desc = _enforce_grounding(desc, corpus, report) or fallback["cards"][min(len(cards), 2)]["desc"]
        cat = clip_chars((c.get("category") or "").upper(), 22)
        if cat in ("", "FEATURE", "BENEFIT", "KEY BENEFIT", "KEY FEATURE", "FEATURES", "BENEFITS"):
            cat = fallback["cards"][min(len(cards), 2)]["category"]
        cards.append({"category": cat,
                      "title": title, "desc": clip_chars(desc, 90), "evidence": clip_chars(c.get("evidence", ""), 160)})
    for fb in fallback["cards"]:
        if len(cards) >= 3:
            break
        cards.append(fb)

    # ---- scenes
    scenes: List[Dict[str, Any]] = []
    n_target = max(3, min(5, config.story_scenes))
    for i, s in enumerate((raw.get("scenes") or [])[:n_target]):
        say = trim_to_words(re.sub(r"\s+", " ", s.get("say", "")).strip(), 38)
        say = _enforce_grounding(say, corpus, report)
        if BANNED.search(say):
            clean = " ".join(x for x in sentences(say) if not BANNED.search(x))
            if word_count(clean) >= 18:
                report.append(f"scene {i + 1}: removed sentence(s) with banned words")
                say = clean
            else:
                report.append(f"scene {i + 1}: banned word(s) present: {sorted(set(m.group(0).lower() for m in BANNED.finditer(say)))}")
        here = pool_resolver(current)
        scroll_to = here.heading(s.get("scroll_to", ""))
        focus = here.heading(s.get("focus_text", ""))
        for key, val, got in (("scroll_to", s.get("scroll_to", ""), scroll_to), ("focus_text", s.get("focus_text", ""), focus)):
            if val and not got:
                report.append(f"scene {i + 1}: {key} '{val[:40]}' is not on the page the browser is on at that point; dropped")
        target = here.action(s.get("target_label", "")) if (s.get("action") == "click" and s.get("target_label")) else None
        if s.get("action") == "click" and s.get("target_label") and not target:
            report.append(f"scene {i + 1}: target '{s.get('target_label')}' is not on the page the browser is on; click removed")
        next_page = current
        if target and target["can_click"] and target.get("href"):
            tp = _path(target["href"])
            if tp != _path(current["url"] if current else ""):
                match = next((pg for pg in brief.get("pages", []) if _path(pg["url"]) == tp), None)
                next_page = match                       # None = a page we did not scout: later scenes are checked loosely
        if word_count(say) < 14:                      # too thin after grounding: use the extractive line
            fb = fallback["scenes"][min(i, len(fallback["scenes"]) - 1)]
            report.append(f"scene {i + 1}: narration too short after checks; used extractive line")
            say = fb["say"]
        current = next_page
        scenes.append({
            "scene_type": (s.get("scene_type") or "feature").lower().strip(),
            "page": s.get("page", ""),
            "title": clip_chars(s.get("title", "") or f"Scene {i + 1}", 42),
            "goal": clip_chars(s.get("goal", ""), 160),
            "scroll_to": scroll_to, "focus_text": focus,
            "target_label": target["label"] if target else "",
            "can_click": bool(target and target["can_click"]),
            "target_href": (target or {}).get("href", ""),
            "action": "click" if target else "none",
            "say": say,
            "card": int(max(0, min(2, s.get("card", min(i, 2))))) if isinstance(s.get("card", 0), int) else min(i, 2),
        })
    for fb in fallback["scenes"]:
        if len(scenes) >= 3:
            break
        scenes.append(fb)

    brand = clip_chars(raw.get("brand_name") or brief["brand_name"], 40)
    tagline = clip_chars(raw.get("tagline") or "", 70)
    if not tagline or ((digit_values(tagline) or spoken_values(tagline)) and not _enforce_grounding(tagline, corpus, report)):
        tagline = fallback["tagline"]
    outro = trim_to_words(raw.get("outro_say") or "", 18) or fallback["outro_say"]
    if _enforce_grounding(outro, corpus, report) != outro:
        outro = fallback["outro_say"]
    if brief["host"].split(".")[0].lower() not in outro.lower().replace(" dot ", "."):
        outro = trim_to_words(outro, 12).rstrip(".!? ") + f" at {spoken_host(brief['host'])}."
    return {
        "source": source, "brand_name": brand,
        "tagline": tagline,
        "audience": clip_chars(raw.get("audience", ""), 120), "promise": clip_chars(raw.get("promise", ""), 160),
        "cards": cards, "scenes": scenes, "outro_say": outro,
        "brand_rgb": brief.get("brand_rgb"), "language": config.narration_language,
        "report": report,
    }


# ============================================================================ heuristic (no-LLM) plan
def _dedupe(text: str) -> str:
    """'X X' -> 'X' (sites often render a heading twice for screen readers / animations)."""
    t = re.sub(r"\s+", " ", (text or "").strip())
    words = t.split()
    n = len(words)
    if n >= 4 and n % 2 == 0 and _norm(" ".join(words[: n // 2])) == _norm(" ".join(words[n // 2:])):
        return " ".join(words[: n // 2])
    out = []
    for sent in sentences(t):
        if not out or _norm(sent) != _norm(out[-1]):
            out.append(sent)
    return " ".join(out)


def _is_prose(text: str) -> bool:
    """Real copy, not UI-mock debris ("Karri · 2min ago", "vehicle_state", "Jun 25 POWERING THE...")."""
    if any(ch in text for ch in ("→", "·", "⋅", "•", "|", "{", "}", "©", "_", "<", ">")):
        return False
    words = text.split()
    caps = sum(1 for w in words if w[:1].isupper())
    shouting = sum(1 for w in words if len(w) > 2 and w.isupper())
    if re.match(r"^\W*(?:[A-Z][a-z]{2,8}\.?\s+\d{1,2}\b|\d{1,2}[:/.-]\d{1,2})", text):     # a date / time stamp
        return False
    return (len(words) >= 7 and shouting < 3 and caps / max(1, len(words)) < 0.55
            and bool(re.search(r"[a-z]{3,}\s+[a-z]{2,}", text)))


def _heading_ok(t: str, h1_norm: str) -> bool:
    t = t.strip()
    if len(t) < 10 or len(t) > 70 or len(t.split()) < 2 or not t[0].isalpha():
        return False
    if sum(1 for w in t.split() if len(w) > 2 and w.isupper()) >= 3:
        return False
    nt = _norm(t)
    return nt != h1_norm and nt not in h1_norm and h1_norm not in nt


def _good_headings(brief: Dict[str, Any], min_level: int = 2, need_prose: bool = True) -> List[Dict[str, Any]]:
    h1 = next((h for h in brief["headings"] if h["level"] == 1), None)
    h1n = _norm(_dedupe(h1["text"])) if h1 else ""
    seen, out = set(), []
    for h in brief["headings"]:
        if h["level"] < min_level or h["level"] == 1 or not _heading_ok(_dedupe(h["text"]), h1n) or _norm(h["text"]) in seen:
            continue
        if need_prose and not _is_prose(h["blurb"]):
            continue
        seen.add(_norm(h["text"]))
        out.append(dict(h, text=_dedupe(h["text"])))
    return out


def heuristic_plan(brief: Dict[str, Any]) -> Dict[str, Any]:
    """Extractive plan straight from the page: the site's own headline, its own feature headings, real prices.
    A safety net for "no key / no quota" - Gemini (vision + wording) is what makes the story good."""
    host = brief["host"]
    name = brief["brand_name"]
    h1 = next((h for h in brief["headings"] if h["level"] == 1), None)
    h1_text = _dedupe(h1["text"]) if h1 else ""
    meta = brief["meta"].get("description") or brief["meta"].get("ogDescription") or ""
    lead = clip_chars(sentences(meta)[0], 140) if meta else ""
    tagline = clip_chars(lead or h1_text or f"{name} - {host}", 70)

    prose_feats = _good_headings(brief, 3) or _good_headings(brief, 2)
    title_feats = _good_headings(brief, 2, need_prose=False)          # real section titles, even without a paragraph
    feats = prose_feats + [f for f in title_feats if _norm(f["text"]) not in {_norm(x["text"]) for x in prose_feats}]
    feats = feats[:6]
    labels = ["WHAT YOU GET", "WHY IT HELPS", "ALSO INCLUDED"]
    cards = []
    for i, f in enumerate(feats[:3]):
        desc = sentences(f["blurb"])[0] if _is_prose(f["blurb"]) else f"{f['text'].rstrip('.!?,;: ')}, built into {name}."
        cards.append({"category": labels[i], "title": clip_chars(f["text"], 32),
                      "desc": clip_chars(desc, 90), "evidence": clip_chars(f["blurb"] or f["text"], 160)})
    if len(cards) < 3:                       # fall back to real sentences from the page copy
        pool = [x for x in sentences(brief["body_text"]) if _is_prose(x) and 40 <= len(x) <= 160]
        for x in pool:
            if len(cards) >= 3:
                break
            if all(_norm(x) not in _norm(c["evidence"]) and _norm(c["desc"]) != _norm(x) for c in cards):
                cards.append({"category": labels[len(cards)], "title": clip_chars(" ".join(x.split()[:5]).rstrip(",.;:"), 32),
                              "desc": clip_chars(x, 90), "evidence": clip_chars(x, 160)})
    while len(cards) < 3:
        cards.append({"category": labels[len(cards)], "title": clip_chars(name, 32),
                      "desc": clip_chars(lead or f"See {name} in action.", 90), "evidence": ""})

    def action_of(kinds, category=None):
        for a in brief["actions"]:
            if a.get("story_ok") and a["kind"] in kinds and (category is None or a["nav_category"] == category):
                return a
        return None

    scenes: List[Dict[str, Any]] = []
    hook = (h1_text or name).rstrip(".!? ") + "."
    second = lead if lead and _norm(lead).rstrip(".") != _norm(hook).rstrip(".") else ""
    scenes.append({"scene_type": "hero", "title": clip_chars(h1_text or name, 42), "goal": "State the promise",
                   "scroll_to": "", "focus_text": h1_text, "target_label": "", "can_click": False,
                   "target_href": "", "action": "none",
                   "say": trim_to_words(f"{hook} {second}".strip() if second else f"{hook} See how {name} works.", 34), "card": 0})

    tab = action_of(("tab",))
    for i, f in enumerate(feats[:2]):
        body = f["blurb"] if _is_prose(f["blurb"]) else f"Here's how {name} handles it."
        step = {"scene_type": "feature", "title": clip_chars(f["text"], 42), "goal": f["text"], "scroll_to": f["text"],
                "focus_text": f["text"], "target_label": "", "can_click": False, "target_href": "", "action": "none",
                "say": trim_to_words(f"{f['text'].rstrip('.!? ')}. {body}", 34), "card": min(i + 1, 2)}
        if i == 0 and tab:
            step.update(target_label=tab["label"], can_click=tab["can_click"], action="click",
                        say=trim_to_words(step["say"], 28) + f" Switch to {tab['label']}.")
        scenes.append(step)

    pricing = action_of(("nav", "link", "cta"), "pricing") or action_of(("nav", "link"), "features")
    price = next((n for p in brief.get("pages", []) if p.get("category") == "pricing" for n in p["numbers"]
                  if re.search(r"[₹$€£]|Rs", n["value"])), None) or \
        next((n for n in brief["numbers"] if re.search(r"[₹$€£]|Rs", n["value"])), None)
    cta = action_of(("cta",))
    if pricing:
        say = f"Pricing is simple, and it starts at {price['value']}. Open the plans and see what fits." if price \
            else "Ready to see the plans? Open Pricing and pick what fits."
        scenes.append({"scene_type": "pricing", "title": "Plans and pricing", "goal": "Show the plans", "scroll_to": "",
                       "focus_text": "", "target_label": pricing["label"], "can_click": pricing["can_click"],
                       "target_href": pricing.get("href", ""), "action": "click", "say": say, "card": 2})
    elif cta:
        scenes.append({"scene_type": "cta", "title": clip_chars(cta["label"], 42), "goal": "Call to action", "scroll_to": "",
                       "focus_text": "", "target_label": cta["label"], "can_click": cta["can_click"],
                       "target_href": cta.get("href", ""), "action": "click",
                       "say": f"Want to see it with your own data? {cta['label']} and take it for a spin.", "card": 2})
    return {"source": "heuristic", "brand_name": name, "tagline": tagline, "audience": "", "promise": lead,
            "cards": cards, "scenes": scenes, "outro_say": f"Try {name} today at {spoken_host(host)}.",
            "brand_rgb": brief.get("brand_rgb"), "language": config.narration_language, "report": []}


# ============================================================================ director
REPAIR_FLAGS = ("too short", "unsupported number", "banned word", "not on the page", "dropped", "removed sentence")


def _issues(plan: Dict[str, Any]) -> List[str]:
    return [r for r in plan.get("report", []) if any(f in r for f in REPAIR_FLAGS)]


class StoryDirector:
    def __init__(self, client: Optional[GeminiClient] = None):
        self.client = client or GeminiClient()

    def _system(self) -> str:
        n = max(3, min(5, config.story_scenes))
        return SYSTEM_PROMPT.replace("{N}", str(n)).replace("{LANGUAGE}", config.narration_language)

    def _call(self, brief: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        n = max(3, min(5, config.story_scenes))
        evidence = json.dumps(build_evidence(brief), ensure_ascii=False, separators=(",", ":"))
        parts: List[Any] = [
            f"EVIDENCE (the website's own content):\n{evidence}\n\n"
            f"The {len(brief.get('screenshots', []))} screenshots below show the home page from the top downwards. "
            f"Plan exactly {n} scenes."
        ]
        for img in brief.get("screenshots", [])[:3]:
            parts.append((img, "image/jpeg"))
        return self.client.generate_json(self._system(), parts, PlanOut, temperature=0.8)

    def _repair(self, brief: Dict[str, Any], previous: Dict[str, Any], issues: List[str]) -> Optional[Dict[str, Any]]:
        """One targeted second pass: show the model its own plan plus exactly what the checker rejected."""
        evidence = json.dumps(build_evidence(brief), ensure_ascii=False, separators=(",", ":"))
        parts: List[Any] = [
            f"EVIDENCE (the website's own content):\n{evidence}\n\n"
            f"YOUR PREVIOUS PLAN:\n{json.dumps(previous, ensure_ascii=False, separators=(',', ':'))}\n\n"
            "An automatic checker rejected these things:\n" + "\n".join(f"- {x}" for x in issues[:10]) +
            "\n\nReturn the COMPLETE corrected plan in the same schema. Keep everything that was already good. "
            "Fix each rejected item using only the EVIDENCE: copy labels exactly, put each scene on the right `page`, "
            "remove unsupported numbers/claims, and keep every `say` at 26-34 words."
        ]
        return self.client.generate_json(self._system(), parts, PlanOut, temperature=0.5)

    async def plan(self, brief: Dict[str, Any]) -> Dict[str, Any]:
        raw, source = None, "heuristic"
        if self.client.enabled:
            raw = await asyncio.to_thread(self._call, brief)
            if raw:
                source = f"gemini:{self.client.last_model}"
        if not raw:
            raw = heuristic_plan(brief)
            if self.client.enabled:
                logger.warning("Gemini plan unavailable (%s); using page-text plan", "; ".join(self.client.errors[-3:]))
        plan = finalize_plan(raw, brief, source)

        issues = _issues(plan)
        if source.startswith("gemini") and issues:
            fixed_raw = await asyncio.to_thread(self._repair, brief, raw, issues)
            if fixed_raw:
                fixed = finalize_plan(fixed_raw, brief, source + "+repair")
                if len(_issues(fixed)) < len(issues):
                    fixed["first_pass_issues"] = issues
                    plan = fixed
        plan["llm_errors"] = list(self.client.errors)
        return plan
