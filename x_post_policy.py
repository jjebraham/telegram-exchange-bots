"""One mandatory link/length policy for every X send, using official twitter-text."""
import json
from pathlib import Path
import re
import subprocess

WHATSAPP_TEXT = "حواله روی خط واتسپ"


def inspect_text(text):
    result = subprocess.run(
        ["node", str(Path(__file__).parent / "x_text" / "validate.cjs")],
        input=json.dumps(text), text=True, encoding="utf-8", capture_output=True,
        check=True, timeout=15,
    )
    return json.loads(result.stdout)


def validate_text(text):
    result = inspect_text(text)
    if result["urls"] or re.search(r"https?://|www\.", text, re.I):
        raise ValueError("X posts must contain no links")
    if not result["valid"] or result["weightedLength"] > 280:
        raise ValueError(f"Invalid X post: {result['weightedLength']} weighted characters")
    return result["text"]


def finish(text, *, gold=False):
    text = text.strip()
    if not gold:
        text += "\n\n" + WHATSAPP_TEXT
    # Preserve all prices, rows and mandatory footer. Only remove numeric grouping
    # separators when larger prices exhaust the budget. Never truncate a quote.
    if inspect_text(text)["weightedLength"] > 280:
        text = re.sub(r"(?<=\d),(?=\d{3}(?:\D|$))", "", text)
    return validate_text(text)
