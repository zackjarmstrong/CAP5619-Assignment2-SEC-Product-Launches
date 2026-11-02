"""Free launch-language ranking; scores are not verification decisions."""
import re


def score_release(text):
    """Rank launch language near the start of a press release.

    This helps prioritize documents for human/LLM review, but cannot
    determine whether a launch is original or an old announcement.
    """
    lead = re.sub(r"\s+", " ", text).strip()[:5000]
    opening = lead[:1600]
    score = 0
    notes = []

    if re.search(
        r"\b(?:announc\w*\s+(?:the\s+)?launch\s+of|"
        r"(?:officially\s+)?launch(?:es|ed)\s+(?:its\s+|a\s+|the\s+)?|"
        r"introduc(?:es|ed)|unveil(?:s|ed)|debut(?:s|ed)|commercial\s+launch)\b",
        opening, re.I
    ):
        score += 5
        notes.append("launch wording near start")

    if re.search(
        r"\b(?:new\s+(?:product|platform|service|solution|software|app|offering|"
        r"technology|line)|commercial(?:ly)?\s+(?:available|launched)|now available)\b",
        opening, re.I
    ):
        score += 3
        notes.append("product/availability wording near start")

    if re.search(r"\b(?:product launch|launch of|new product|introduced)\b", lead, re.I):
        score += 1
        notes.append("launch terms in early text")

    if re.search(
        r"\b(?:earnings|financial results|quarterly results|"
        r"fourth quarter|third quarter|second quarter|first quarter|"
        r"year-end results|fiscal year results)\b",
        opening, re.I
    ):
        score -= 5
        notes.append("financial-results language near start")

    if re.search(
        r"\b(?:development agreement|prototype|plans to launch|"
        r"intends to launch|future launch|under development)\b",
        opening, re.I
    ):
        score -= 3
        notes.append("development/future wording near start")

    priority = "Higher" if score >= 5 else "Medium" if score >= 2 else "Lower"
    return score, priority, "; ".join(notes) or "No strong launch cues near start"



def main():
    import sys
    from run_pipeline import main as run
    run(["--mode", "screen", *sys.argv[1:]])


if __name__ == "__main__":
    main()
