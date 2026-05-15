"""
scripts/transcript_parser.py

Phase 1, Step 2 — Parse raw transcript text into structured sections.

Takes each file in data/raw/ and produces a structured JSON in data/processed/
with three zones:
  - prepared_remarks  : CEO/CFO scripted opening
  - guidance          : forward-looking statements section
  - qa                : Q&A exchange (analyst questions + exec responses)
  - metadata          : speaker names, section boundaries, quality flags

Run:
    python scripts/transcript_parser.py
    python scripts/transcript_parser.py --ticker JPM
    python scripts/transcript_parser.py --show JPM_2023-01-13_01234567.json
"""

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from config import DATA_PROCESSED, DATA_RAW, MIN_TRANSCRIPT_CHARS

# ── Section boundary patterns ─────────────────────────────────────────────────
# Listed in priority order — first match wins for each boundary

PREPARED_HEADERS = [
    r"prepared\s+remarks",
    r"presentation",
    r"opening\s+remarks",
    r"opening\s+statements",
    r"management\s+discussion",
    r"formal\s+remarks",
]

QA_HEADERS = [
    r"question[\s\-]+and[\s\-]+answer",
    r"q\s*&\s*a\s+session",
    r"q\s*and\s*a",
    r"questions?\s+and\s+answers?",
    r"analyst\s+q\s*&\s*a",
    r"open(?:ing)?\s+(?:the\s+)?floor\s+(?:to\s+)?(?:questions?|q\s*&\s*a)",
    r"operator.*please\s+(?:go\s+ahead|open\s+the\s+line|begin)",
]

GUIDANCE_HEADERS = [
    r"full[\s\-]year\s+20\d\d\s+(?:outlook|guidance|targets?)",
    r"fy\s*20\d\d\s+(?:outlook|guidance|targets?)",
    r"^(?:financial\s+)?outlook\s*$",
    r"forward[\s\-]looking\s+(?:guidance|statements?)",
    r"(?:fiscal|full)[\s\-]year\s+(?:20\d\d\s+)?guidance",
    r"^guidance\s+(?:update|summary|range)\s*$",
    r"^(?:20\d\d\s+)?full[\s\-]year\s+outlook\s*$",
]

CLOSING_HEADERS = [
    r"^thank\s+you\s+for\s+(?:your\s+)?(?:participation|attending)\s*[.\!]?\s*$",
    r"that\s+concludes\s+(?:today['']s|our|this)\s+(?:call|conference)",
    r"this\s+concludes\s+(?:the\s+)?(?:question|q\s*&\s*a)",
    r"end\s+of\s+(?:the\s+)?(?:call|conference\s+call|transcript)",
]

# Speaker line pattern — "FirstName LastName - Title" or "OPERATOR:" style
SPEAKER_PATTERN = re.compile(
    r"^(?P<name>[A-Z][a-zA-Z\s\-\.]{2,40})"
    r"(?:\s*[-–—:]\s*"
    r"(?P<title>[A-Za-z][A-Za-z\s\-\,\.&]{2,60}))?\s*$"
)

# Analyst question indicators
ANALYST_INDICATORS = [
    r"\banalyst\b", r"\bmanaging\s+director\b", r"\bequity\s+research\b",
    r"\bsecurities\b", r"\bbank\b.*\bresearch\b", r"\bpartners\b.*\bresearch\b",
    r"my\s+(?:first|second|next|follow[\s\-]up)\s+question",
    r"i\s+(?:wanted?|'d\s+like)\s+to\s+(?:ask|follow\s+up)",
]
ANALYST_RE = re.compile("|".join(ANALYST_INDICATORS), re.IGNORECASE)

# Executive response indicators
EXEC_INDICATORS = [
    r"\bchief\s+executive\b", r"\bceo\b", r"\bcfo\b", r"\bcoo\b",
    r"\bpresident\b", r"\beverett\b", r"\bchairman\b",
    r"thank\s+you\s+(?:for\s+(?:that|your)\s+question)",
    r"(?:great|good|sure|absolutely)\s*[,\.]?\s*(?:so\s+)?(?:i\s+think|we\s+)",
]
EXEC_RE = re.compile("|".join(EXEC_INDICATORS), re.IGNORECASE)


# ── Utility ───────────────────────────────────────────────────────────────────

def _matches_any(patterns: list[str], text: str) -> bool:
    for p in patterns:
        if re.search(p, text, re.IGNORECASE):
            return True
    return False


def _line_is_section_header(line: str) -> tuple[str, bool]:
    """
    Returns (section_name, is_header).
    section_name: 'prepared' | 'qa' | 'guidance' | 'closing' | ''
    """
    clean = line.strip()
    if len(clean) > 120 or len(clean) < 3:
        return "", False

    if _matches_any(QA_HEADERS, clean):
        return "qa", True
    if _matches_any(PREPARED_HEADERS, clean):
        return "prepared", True
    if _matches_any(GUIDANCE_HEADERS, clean):
        return "guidance", True
    if _matches_any(CLOSING_HEADERS, clean):
        return "closing", True
    return "", False


def _is_speaker_line(line: str) -> bool:
    """Heuristic: is this line introducing a new speaker?"""
    clean = line.strip()
    if not clean or len(clean) > 80:
        return False

    # Exclude lines that start with common sentence words — not speaker names
    NON_SPEAKER_STARTS = (
        "and ", "but ", "we ", "i ", "the ", "our ", "it ", "this ", "that ",
        "as ", "so ", "in ", "for ", "thank ", "good ", "great ", "sure ",
        "there ", "with ", "on ", "of ", "at ", "by ", "if ", "my ", "your ",
    )
    if any(clean.lower().startswith(p) for p in NON_SPEAKER_STARTS):
        return False

    # All-caps name line (common in SEC transcripts)
    if re.match(r"^[A-Z][A-Z\s\-\.]{3,50}$", clean):
        return True
    # Name — Title format
    if re.search(r"^[A-Z][a-zA-Z\s]{2,30}\s*[-–—]\s*[A-Za-z]", clean):
        return True
    # OPERATOR: prefix
    if re.match(r"^OPERATOR\s*:", clean, re.IGNORECASE):
        return True
    return False


# ── Core parser ───────────────────────────────────────────────────────────────

def parse_transcript(text: str) -> dict:
    """
    Parse raw transcript text into structured sections.

    Returns:
        {
          sections: {prepared_remarks, guidance, qa},
          qa_turns: [{speaker, text, is_analyst, is_executive}],
          speakers: [str],
          quality: {has_prepared, has_qa, has_guidance, section_count, qa_turn_count}
        }
    """
    lines = [l.rstrip() for l in text.splitlines()]

    # ── Pass 1: identify section boundaries ──────────────────────────────────
    # Build a list of (line_index, section_name) for each detected header
    boundaries: list[tuple[int, str]] = []
    for i, line in enumerate(lines):
        section, is_header = _line_is_section_header(line)
        if is_header:
            # Avoid duplicate adjacent detections
            if not boundaries or boundaries[-1][1] != section:
                boundaries.append((i, section))

    # ── Pass 2: assign lines to sections ─────────────────────────────────────
    section_texts: dict[str, list[str]] = {
        "prepared_remarks": [],
        "guidance": [],
        "qa": [],
    }

    # Default: if no prepared header found, assume everything before Q&A is prepared
    if not any(s == "prepared" for _, s in boundaries):
        first_qa = next((i for i, s in boundaries if s == "qa"), len(lines))
        boundaries = [(0, "prepared")] + boundaries

    # Build a fast lookup: line_index → section_name
    boundary_map = {bl: bs for bl, bs in boundaries}

    current_section = "prepared_remarks"
    for i, line in enumerate(lines):
        if i in boundary_map:
            section = boundary_map[i]
            if section == "qa":
                current_section = "qa"
            elif section == "guidance":
                current_section = "guidance"
            elif section == "prepared":
                current_section = "prepared_remarks"
            elif section == "closing":
                current_section = None
            # Don't append the header line itself, skip to next
            continue

        if current_section:
            section_texts[current_section].append(line)

    # ── Pass 3: extract Q&A turns ─────────────────────────────────────────────
    qa_turns = _extract_qa_turns(section_texts["qa"])

    # ── Pass 4: guidance extraction within prepared if no explicit section ────
    if not section_texts["guidance"]:
        section_texts["guidance"] = _extract_guidance_sentences(
            section_texts["prepared_remarks"]
        )

    # ── Quality flags ─────────────────────────────────────────────────────────
    quality = {
        "has_prepared": len(section_texts["prepared_remarks"]) > 5,
        "has_qa": len(section_texts["qa"]) > 5,
        "has_guidance": len(section_texts["guidance"]) >= 1,
        "section_count": len([v for v in section_texts.values() if v]),
        "qa_turn_count": len(qa_turns),
        "prepared_char_count": sum(len(l) for l in section_texts["prepared_remarks"]),
        "qa_char_count": sum(len(l) for l in section_texts["qa"]),
    }

    # ── Collect unique speaker names ──────────────────────────────────────────
    speakers = list({t["speaker"] for t in qa_turns if t["speaker"]})

    return {
        "sections": {
            "prepared_remarks": "\n".join(section_texts["prepared_remarks"]).strip(),
            "guidance": "\n".join(section_texts["guidance"]).strip(),
            "qa": "\n".join(section_texts["qa"]).strip(),
        },
        "qa_turns": qa_turns,
        "speakers": speakers,
        "quality": quality,
    }


def _extract_qa_turns(qa_lines: list[str]) -> list[dict]:
    """
    Parse Q&A lines into a list of speaker turns.
    Each turn: {speaker, text, is_analyst, is_executive}

    A new turn begins whenever a speaker line is detected, even if it's
    the same speaker as the previous turn (they may speak multiple times).
    """
    turns: list[dict] = []
    current_speaker = ""
    current_lines: list[str] = []

    def _flush():
        if current_lines:
            turn_text = " ".join(current_lines).strip()
            if len(turn_text) > 20:
                turns.append(_classify_turn(current_speaker, turn_text))

    for line in qa_lines:
        if _is_speaker_line(line):
            _flush()
            current_speaker = line.strip()
            current_lines = []
        else:
            stripped = line.strip()
            if stripped:
                current_lines.append(stripped)

    _flush()
    return turns


def _classify_turn(speaker: str, text: str) -> dict:
    """Determine if a Q&A turn is from an analyst or executive."""
    speaker_lower = speaker.lower()
    text_start = text[:300].lower()

    # Analyst: either their title/firm is in the speaker line, or they ask a question
    is_analyst = bool(ANALYST_RE.search(speaker)) or bool(
        re.search(
            r"\b(?:my|a)\s+(?:first|second|next|follow[\s\-]up)\s+question|"
            r"i\s+(?:wanted?|'d\s+like)\s+to\s+(?:ask|follow)",
            text_start,
            re.IGNORECASE,
        )
    )
    is_executive = (
        bool(EXEC_RE.search(speaker)) or bool(EXEC_RE.search(text_start))
    ) and not ANALYST_RE.search(speaker)

    return {
        "speaker": speaker,
        "text": text,
        "is_analyst": is_analyst,
        "is_executive": is_executive,
    }


def _extract_guidance_sentences(prepared_lines: list[str]) -> list[str]:
    """
    Fallback: extract guidance-sounding sentences from prepared remarks
    when there's no explicit guidance section.
    """
    guidance_patterns = [
        r"\bwe\s+expect\b", r"\bwe\s+anticipate\b", r"\bwe\s+(?:are\s+)?(?:targeting|guiding)\b",
        r"\bfull[\s\-]year\b.*\b(?:\$|percent|basis\s+points?)\b",
        r"\bguidance\s+(?:of|is|remains?|range)\b",
        r"\b(?:fiscal|calendar)\s+20\d\d\b.*\b(?:revenue|eps|earnings|growth)\b",
        r"\b(?:revenue|earnings|eps)\b.*\b(?:range|between|of\s+approximately)\b",
    ]
    pattern = re.compile("|".join(guidance_patterns), re.IGNORECASE)

    guidance_lines = []
    for line in prepared_lines:
        if pattern.search(line) and len(line) > 40:
            guidance_lines.append(line)

    return guidance_lines


# ── File processing ───────────────────────────────────────────────────────────

def process_raw_file(raw_path: Path, force: bool = False) -> dict | None:
    """
    Parse one raw JSON file → save to data/processed/.
    Returns the processed record or None if skipped.
    """
    DATA_PROCESSED.mkdir(parents=True, exist_ok=True)
    out_path = DATA_PROCESSED / raw_path.name

    if out_path.exists() and not force:
        return None

    with open(raw_path, encoding="utf-8") as f:
        raw = json.load(f)

    text = raw.get("text", "")
    if len(text) < MIN_TRANSCRIPT_CHARS:
        print(f"  [SKIP] {raw_path.name} — too short")
        return None

    parsed = parse_transcript(text)

    record = {
        **{k: v for k, v in raw.items() if k != "text"},  # preserve metadata
        "raw_char_count": len(text),
        **parsed,
    }

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(record, f, indent=2, ensure_ascii=False)

    q = parsed["quality"]
    print(
        f"  [OK]  {raw_path.name} — "
        f"prepared={q['prepared_char_count']:,}c  "
        f"qa_turns={q['qa_turn_count']}  "
        f"guidance={'yes' if q['has_guidance'] else 'no'}"
    )
    return record


def process_all(ticker_filter: str | None = None, force: bool = False):
    raw_files = sorted(DATA_RAW.glob("*.json"))
    if ticker_filter:
        raw_files = [f for f in raw_files if f.name.startswith(ticker_filter.upper())]

    if not raw_files:
        print(f"No raw files found in {DATA_RAW}")
        return

    print(f"Processing {len(raw_files)} files...")
    ok, skipped = 0, 0
    for path in raw_files:
        result = process_raw_file(path, force=force)
        if result:
            ok += 1
        else:
            skipped += 1

    print(f"\nDone — {ok} processed, {skipped} skipped (already done or too short)")


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Parse raw EDGAR transcripts into structured JSON")
    parser.add_argument("--ticker", help="Process only this ticker")
    parser.add_argument("--force", action="store_true", help="Re-process even if output exists")
    parser.add_argument("--show", help="Parse a single file and print section summary")
    args = parser.parse_args()

    if args.show:
        path = DATA_RAW / args.show
        if not path.exists():
            path = DATA_PROCESSED / args.show
        with open(path) as f:
            raw = json.load(f)
        result = parse_transcript(raw.get("text", raw.get("sections", {}).get("prepared_remarks", "")))
        print(json.dumps(result["quality"], indent=2))
        print(f"\nPrepared remarks ({result['quality']['prepared_char_count']:,} chars):")
        print(result["sections"]["prepared_remarks"][:500], "...")
        print(f"\nQ&A turns: {result['quality']['qa_turn_count']}")
        for turn in result["qa_turns"][:3]:
            role = "ANALYST" if turn["is_analyst"] else "EXEC" if turn["is_executive"] else "?"
            print(f"  [{role}] {turn['speaker']}: {turn['text'][:120]}...")
    else:
        process_all(ticker_filter=args.ticker, force=args.force)
