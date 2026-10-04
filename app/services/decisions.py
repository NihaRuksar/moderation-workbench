from app import models
from app.services.audit import log_action
from app.services.workflow import change_status

# Outcomes that count against the author's record
HISTORY_NAMES = {"warn": "warning", "remove_content": "content_removed"}


def resolve_final_action(review, action, final_action, note):
    """Work out the final action from the moderator's choice.
    Raises ValueError if the choice breaks a rule."""
    if action in ("approve", "reject") and final_action is not None:
        raise ValueError("final_action can only be set when action is 'modify'")

    if action == "approve":
        if review.proposed_action == "escalate":
            raise ValueError(
                "The AI proposed 'escalate', so there is nothing to approve. "
                "Use 'modify' and choose a final_action."
            )
        return review.proposed_action

    if not note:
        raise ValueError(f"A note is required when action is '{action}'")

    if action == "reject":
        return "no_action"

    # modify
    if final_action is None:
        raise ValueError("final_action is required when action is 'modify'")
    return final_action


def record_decision(db, content, review, moderator, action, final_action, note):
    """Save the moderator's decision. Does NOT commit: the route commits."""
    final = resolve_final_action(review, action, final_action, note)

    decision = models.Decision(
        review_id=review.id,
        moderator=moderator,
        action=action,
        final_action=final,
        note=note or None,
        policy_version_id=review.policy_version_id,  # the version the review used
    )
    db.add(decision)
    db.flush()  # gives the decision an id

    # Record warnings and removals so the repeat-offender check can see them
    if final in HISTORY_NAMES:
        db.add(models.ModerationHistory(
            author=content.author,
            action=HISTORY_NAMES[final],
            content_id=content.id,
        ))

    change_status(db, content, "decided", moderator)

    log_action(
        db, moderator, "decision_made", "decision", decision.id,
        f"content={content.id}, action={action}, final_action={final}, "
        f"policy_version={review.policy_version_id}",
    )
    return decision