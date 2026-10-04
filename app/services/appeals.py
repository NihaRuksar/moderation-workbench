from app import models
from app.services.audit import log_action
from app.services.decisions import HISTORY_NAMES
from app.services.workflow import change_status

APPEALABLE_ACTIONS = {"warn", "remove_content"}


def create_appeal(db, content, decision, author, reason, evidence):
    """Create an appeal and send it to second review.
    Does NOT commit: the route commits."""
    if decision.final_action not in APPEALABLE_ACTIONS:
        raise ValueError("Only a warning or a removal can be appealed")

    appeal = models.Appeal(
        decision_id=decision.id,
        reason=reason,
        evidence=evidence or None,
    )
    db.add(appeal)
    db.flush()  # gives the appeal an id

    change_status(db, content, "appealed", author)
    change_status(db, content, "second_review", "system")

    log_action(
        db, author, "appeal_submitted", "appeal", appeal.id,
        f"content={content.id}, decision={decision.id}",
    )
    return appeal


def resolve_appeal(db, appeal, content, decision, reviewer, outcome, final_action, note):
    """Record the second reviewer's outcome.
    Raises ValueError if a rule is broken. Does NOT commit."""
    # The second review must be independent
    if reviewer.lower() == decision.moderator.lower():
        raise ValueError(
            "The second reviewer must be a different person than the original moderator"
        )
    if reviewer.lower() == content.author.lower():
        raise ValueError("The author cannot review their own appeal")

    # Work out the action that is in force after the appeal
    if outcome != "modified" and final_action is not None:
        raise ValueError("final_action can only be set when outcome is 'modified'")

    if outcome == "upheld":
        new_final = decision.final_action
    elif outcome == "overturned":
        new_final = "no_action"
    else:  # modified
        if final_action is None:
            raise ValueError("final_action is required when outcome is 'modified'")
        if final_action == decision.final_action:
            raise ValueError(
                "That is the same as the original action. Use outcome 'upheld' instead."
            )
        new_final = final_action

    appeal.second_reviewer = reviewer
    appeal.outcome = outcome
    appeal.final_action = new_final
    appeal.outcome_note = note
    appeal.status = "decided"

    # Correct the author's record if the action changed.
    # The audit log keeps the full history of what happened.
    if new_final != decision.final_action:
        (
            db.query(models.ModerationHistory)
            .filter(models.ModerationHistory.content_id == content.id)
            .filter(models.ModerationHistory.action.in_(list(HISTORY_NAMES.values())))
            .delete(synchronize_session=False)
        )
        if new_final in HISTORY_NAMES:
            db.add(models.ModerationHistory(
                author=content.author,
                action=HISTORY_NAMES[new_final],
                content_id=content.id,
            ))

    change_status(db, content, "final", reviewer)

    log_action(
        db, reviewer, "appeal_resolved", "appeal", appeal.id,
        f"content={content.id}, outcome={outcome}, "
        f"original_action={decision.final_action}, final_action={new_final}",
    )