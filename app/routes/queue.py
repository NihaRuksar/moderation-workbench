import json
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app import models
from app.database import get_db
from app.services.decisions import record_decision

router = APIRouter(prefix="/queue", tags=["queue"])

SEVERITY_RANK = {"high": 3, "medium": 2, "low": 1}


class DecisionCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    moderator: str = Field(min_length=1, max_length=100)
    action: Literal["approve", "reject", "modify"]
    final_action: Optional[Literal["no_action", "warn", "remove_content"]] = None
    note: Optional[str] = Field(default=None, max_length=2000)


def latest_review(db, content_id):
    return (
        db.query(models.Review)
        .filter(models.Review.content_id == content_id)
        .order_by(models.Review.id.desc())
        .first()
    )


def review_details(review):
    """Turn a Review row into a clean dict. The saved findings are JSON text."""
    saved = json.loads(review.findings) if review.findings else {}
    if not isinstance(saved, dict):  # an un-reviewed row holds "[]"
        saved = {}
    return {
        "review_id": review.id,
        "policy_version_id": review.policy_version_id,
        "deterministic_flags": json.loads(review.deterministic_flags),
        "findings": saved.get("findings", []),
        "reasoning": saved.get("reasoning", ""),
        "validation_notes": saved.get("validation_notes", []),
        "ai_used": saved.get("ai_used"),
        "proposed_action": review.proposed_action,
        "severity": review.severity,
        "confidence": review.confidence,
        "needs_human": review.needs_human,
    }


@router.get("")
def get_queue(db: Session = Depends(get_db)):
    """Items waiting for a moderator. Highest severity first, then those that
    need human judgment, then oldest first."""
    items = (
        db.query(models.Content)
        .filter(models.Content.status == "pending_moderator")
        .all()
    )
    rows = []
    for content in items:
        review = latest_review(db, content.id)
        if review is None:
            continue
        rows.append({
            "id": content.id,
            "content_type": content.content_type,
            "author": content.author,
            "preview": content.body[:100],
            "proposed_action": review.proposed_action,
            "severity": review.severity,
            "confidence": review.confidence,
            "needs_human": review.needs_human,
            "submitted_at": content.created_at,
        })
    rows.sort(key=lambda r: (
        -SEVERITY_RANK.get(r["severity"], 0),
        -int(r["needs_human"]),
        r["id"],
    ))
    return rows


@router.get("/{content_id}")
def get_queue_item(content_id: int, db: Session = Depends(get_db)):
    """Everything a moderator needs to decide: content, parent, AI review, decision."""
    content = db.get(models.Content, content_id)
    if content is None:
        raise HTTPException(status_code=404, detail="Content not found")

    review = latest_review(db, content.id)
    if review is None:
        raise HTTPException(status_code=404, detail="This content has no review yet")

    parent = db.get(models.Content, content.parent_id) if content.parent_id else None
    decision = review.decisions[-1] if review.decisions else None

    return {
        "content": {
            "id": content.id,
            "content_type": content.content_type,
            "author": content.author,
            "body": content.body,
            "status": content.status,
        },
        "parent": (
            {"id": parent.id, "author": parent.author, "body": parent.body}
            if parent else None
        ),
        "review": review_details(review),
        "decision": (
            {
                "decision_id": decision.id,
                "moderator": decision.moderator,
                "action": decision.action,
                "final_action": decision.final_action,
                "note": decision.note,
                "policy_version_id": decision.policy_version_id,
            }
            if decision else None
        ),
    }


@router.post("/{content_id}/decision")
def make_decision(content_id: int, data: DecisionCreate, db: Session = Depends(get_db)):
    content = db.get(models.Content, content_id)
    if content is None:
        raise HTTPException(status_code=404, detail="Content not found")

    if content.status != "pending_moderator":
        raise HTTPException(
            status_code=409,
            detail=f"Content is '{content.status}', so it is not waiting for a decision",
        )

    review = latest_review(db, content.id)
    if review is None:
        raise HTTPException(status_code=409, detail="This content has no review yet")

    if data.moderator.lower() == content.author.lower():
        raise HTTPException(
            status_code=403, detail="A moderator cannot decide on their own content"
        )

    try:
        decision = record_decision(
            db, content, review,
            data.moderator, data.action, data.final_action, data.note,
        )
    except ValueError as error:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(error))

    db.commit()  # one commit for the decision, history, status change, and audit log
    return {
        "decision_id": decision.id,
        "content_id": content.id,
        "status": content.status,
        "action": decision.action,
        "final_action": decision.final_action,
        "policy_version_id": decision.policy_version_id,
    }