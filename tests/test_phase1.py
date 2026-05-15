"""
tests/test_phase1.py

Unit tests for Phase 1: scraper utilities, transcript parser, price fetcher.
Run: pytest tests/test_phase1.py -v
"""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from scripts.transcript_parser import (
    _extract_guidance_sentences,
    _extract_qa_turns,
    _is_speaker_line,
    _line_is_section_header,
    parse_transcript,
)
from scripts.edgar_scraper import get_cik


# ── Parser unit tests ─────────────────────────────────────────────────────────

class TestSectionHeaders:
    def test_qa_header_detected(self):
        assert _line_is_section_header("Question-and-Answer Session") == ("qa", True)
        assert _line_is_section_header("Q&A Session") == ("qa", True)
        assert _line_is_section_header("Questions and Answers") == ("qa", True)

    def test_prepared_header_detected(self):
        assert _line_is_section_header("Prepared Remarks") == ("prepared", True)
        assert _line_is_section_header("Opening Remarks") == ("prepared", True)

    def test_guidance_header_detected(self):
        assert _line_is_section_header("Full-Year 2024 Outlook") == ("guidance", True)
        assert _line_is_section_header("FY 2024 Guidance") == ("guidance", True)

    def test_closing_header_detected(self):
        result = _line_is_section_header("That concludes today's conference call")
        assert result == ("closing", True)

    def test_normal_text_not_header(self):
        assert _line_is_section_header("Revenue grew 12% year-over-year.") == ("", False)
        assert _line_is_section_header("") == ("", False)


class TestSpeakerLine:
    def test_all_caps_name(self):
        assert _is_speaker_line("JOHN SMITH") is True

    def test_name_with_title(self):
        assert _is_speaker_line("Jane Doe - Chief Financial Officer") is True

    def test_operator(self):
        assert _is_speaker_line("OPERATOR:") is True

    def test_normal_sentence(self):
        assert _is_speaker_line("Revenue increased by 15% in the quarter.") is False

    def test_too_long(self):
        long_line = "A" * 90
        assert _is_speaker_line(long_line) is False


class TestQaTurns:
    SAMPLE_QA = """
JOHN ANALYST - Goldman Sachs
I wanted to ask about your net interest margin guidance for next year.

JANE CEO - Chief Executive Officer
Thank you for that question. We expect NIM to compress by about 10 basis points.

JOHN ANALYST - Goldman Sachs
And as a follow-up question, what is your outlook on loan growth?

JANE CEO - Chief Executive Officer
We are targeting mid-single-digit loan growth in fiscal 2024.
""".strip().splitlines()

    def test_extracts_turns(self):
        turns = _extract_qa_turns(self.SAMPLE_QA)
        assert len(turns) == 4

    def test_analyst_classified(self):
        turns = _extract_qa_turns(self.SAMPLE_QA)
        assert turns[0]["is_analyst"] is True
        assert turns[2]["is_analyst"] is True

    def test_exec_classified(self):
        turns = _extract_qa_turns(self.SAMPLE_QA)
        assert turns[1]["is_executive"] is True

    def test_speaker_names_extracted(self):
        turns = _extract_qa_turns(self.SAMPLE_QA)
        assert any("JOHN" in t["speaker"] for t in turns)
        assert any("JANE" in t["speaker"] for t in turns)


class TestGuidanceExtraction:
    def test_extracts_guidance_sentences(self):
        lines = [
            "Our team worked hard this quarter.",
            "We expect full-year revenue of approximately $4.2 billion.",
            "We anticipate EPS between $3.10 and $3.30.",
            "The weather was sunny last Tuesday.",
            "We are targeting mid-single-digit loan growth in fiscal 2024.",
        ]
        result = _extract_guidance_sentences(lines)
        assert len(result) == 3
        assert all("expect" in r or "anticipate" in r or "targeting" in r for r in result)


class TestFullParser:
    SAMPLE_TRANSCRIPT = """
Prepared Remarks

JANE SMITH
Good morning and thank you for joining our Q3 2023 earnings call.
We reported revenue of $2.1 billion, up 8% year-over-year.
We expect full-year 2023 revenue between $8.2 and $8.5 billion.
We anticipate net interest margin of approximately 3.2% for the full year.

Question-and-Answer Session

BOB JONES - JPMorgan Securities
Thank you. I wanted to ask about your credit quality outlook.

JANE SMITH - CEO
Great question. We feel confident in our credit quality metrics.

BOB JONES - JPMorgan Securities
And as a follow-up question, what is your loan growth target?

JANE SMITH - CEO
We are targeting 5 to 7 percent growth in our loan portfolio.
"""

    def test_sections_populated(self):
        result = parse_transcript(self.SAMPLE_TRANSCRIPT)
        assert len(result["sections"]["prepared_remarks"]) > 50
        assert len(result["sections"]["qa"]) > 50

    def test_qa_turns_extracted(self):
        result = parse_transcript(self.SAMPLE_TRANSCRIPT)
        assert result["quality"]["qa_turn_count"] >= 2

    def test_guidance_extracted(self):
        result = parse_transcript(self.SAMPLE_TRANSCRIPT)
        assert result["quality"]["has_guidance"]

    def test_quality_flags(self):
        result = parse_transcript(self.SAMPLE_TRANSCRIPT)
        q = result["quality"]
        assert q["has_prepared"] is True
        assert q["has_qa"] is True

    def test_speakers_collected(self):
        result = parse_transcript(self.SAMPLE_TRANSCRIPT)
        assert len(result["speakers"]) >= 1


# ── Scraper unit tests ────────────────────────────────────────────────────────

class TestCikResolution:
    """These make real network calls — mark slow."""

    @pytest.mark.slow
    def test_known_ticker_resolves(self):
        cik = get_cik("JPM")
        assert cik is not None
        assert len(cik) == 10  # zero-padded

    @pytest.mark.slow
    def test_unknown_ticker_returns_none(self):
        cik = get_cik("NOTAREALTHING99")
        assert cik is None


# ── Price fetcher unit tests ──────────────────────────────────────────────────

class TestReturnCalc:
    """Isolated tests — mock out yfinance to avoid network calls."""

    def test_positive_return(self):
        import pandas as pd
        from unittest.mock import patch

        mock_df = pd.DataFrame(
            {"Close": [100.0, 103.0, 105.0, 106.0]},
            index=pd.to_datetime(["2023-01-10", "2023-01-11", "2023-01-12", "2023-01-13"]),
        )

        with patch("scripts.price_fetcher.get_price_history", return_value=mock_df):
            from scripts.price_fetcher import get_return
            r = get_return("FAKE", "2023-01-10", 1)
            assert r == pytest.approx(0.03, abs=0.001)

    def test_negative_return(self):
        import pandas as pd
        from unittest.mock import patch

        mock_df = pd.DataFrame(
            {"Close": [100.0, 95.0, 93.0, 92.0]},
            index=pd.to_datetime(["2023-01-10", "2023-01-11", "2023-01-12", "2023-01-13"]),
        )

        with patch("scripts.price_fetcher.get_price_history", return_value=mock_df):
            from scripts.price_fetcher import get_return
            r = get_return("FAKE", "2023-01-10", 1)
            assert r == pytest.approx(-0.05, abs=0.001)

    def test_missing_data_returns_none(self):
        import pandas as pd
        from unittest.mock import patch

        empty_df = pd.DataFrame()

        with patch("scripts.price_fetcher.get_price_history", return_value=empty_df):
            from scripts.price_fetcher import get_return
            r = get_return("FAKE", "2023-01-10", 1)
            assert r is None
