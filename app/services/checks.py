import re

from app import models

# Phrases that point to a policy clause. Edit these lists freely.
BANNED_PHRASES = {
    "1.1": ["idiot", "stupid", "moron", "loser", "shut up"],
    "2.1": ["i will find you", "kill you", "i will hurt you", "you will pay for this"],
}

LINK_SPAM_THRESHOLD = 3
REPEAT_OFFENDER_THRESHOLD = 2


def _normalize(text):
    """Lowercase and collapse extra spaces, so 'Hi  There' equals 'hi there'."""
    return " ".join(text.lower().split())


def run_checks(db, content):
    """Run plain-code checks on one content item.

    Returns a list of flags: {"check": ..., "clause_id": ..., "detail": ...}.
    This function only returns flags. It never changes the database.
    """
    flags = []
    body = content.body

    # 1. Phrase match (word boundaries, so "class" does not match "ass")
    for clause_id, phrases in BANNED_PHRASES.items():
        for phrase in phrases:
            pattern = r"\b" + re.escape(phrase) + r"\b"
            if re.search(pattern, body, flags=re.IGNORECASE):
                flags.append({
                    "check": "phrase_match",
                    "clause_id": clause_id,
                    "detail": f"Matched phrase: '{phrase}'",
                })

    # 2. Link spam
    links = re.findall(r"https?://\S+", body)
    if len(links) >= LINK_SPAM_THRESHOLD:
        flags.append({
            "check": "link_spam",
            "clause_id": "3.1",
            "detail": f"{len(links)} links found",
        })

    # 3. Repeated content from the same author (excluding this item itself)
    others = (
        db.query(models.Content)
        .filter(models.Content.author == content.author)
        .filter(models.Content.id != content.id)
        .all()
    )
    mine = _normalize(body)
    if any(_normalize(other.body) == mine for other in others):
        flags.append({
            "check": "repeated_content",
            "clause_id": "3.1",
            "detail": "Same text already posted by this author",
        })

    # 4. Repeat offender.
    # This is a SIGNAL, not a violation by itself. The AI and the moderator
    # use it as context. That is why clause_id is None.
    past_actions = (
        db.query(models.ModerationHistory)
        .filter(models.ModerationHistory.author == content.author)
        .count()
    )
    if past_actions >= REPEAT_OFFENDER_THRESHOLD:
        flags.append({
            "check": "repeat_offender",
            "clause_id": None,
            "detail": f"Author has {past_actions} past moderation actions",
        })

    return flags