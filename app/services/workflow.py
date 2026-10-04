from app.services.audit import log_action

# Each status can only move to the statuses listed next to it
ALLOWED_MOVES = {
    "submitted": ["ai_reviewed"],
    "ai_reviewed": ["pending_moderator"],
    "pending_moderator": ["decided"],
    "decided": ["appealed", "final"],
    "appealed": ["second_review"],
    "second_review": ["final"],
}


def change_status(db, content, new_status, actor):
    """Move content to a new status if the workflow allows it.
    Does NOT commit: the caller commits."""
    allowed = ALLOWED_MOVES.get(content.status, [])
    if new_status not in allowed:
        raise ValueError(
            f"Cannot move content from '{content.status}' to '{new_status}'"
        )
    old_status = content.status
    content.status = new_status
    log_action(
        db, actor, "status_changed", "content", content.id,
        f"{old_status} -> {new_status}",
    )