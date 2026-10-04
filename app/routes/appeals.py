from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app import models
from app.database import get_db
from app.routes.queue import latest_review, review_details
from app.services.appeals import create_appeal, resolve_appeal

router = APIRouter(prefix="/appeals", tags=["appeals"])


class AppealCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    content_id: int
    author: str = Field(min_length=1, max_length=100)
    reason: str = Field(min_length=1, max_length=3000)
    evidence: Optional[str] = Field(default=None, max_length=3000)


class AppealResolve(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    second_reviewer: str = Field(min_length=1, max_length=100)
    outcome: Literal["upheld", "overturned", "modified"]
    final_action: Optional[Literal["no_action", "warn", "remove_content"]] = None
    note: str = Field(min_length=1, max_length=2000)


@router.post("")
def submit_appeal(data: AppealCreate, db: Session = Depends(get_db)):
    content = db.get(models.Content, data.content_id)
    if content is None:
        raise HTTPException(status_code=404, detail="Content not found")

    if content.status != "decided":
        raise HTTPException(
            status_code=409,
            detail=f"Content is '{content.status}', so it cannot be appealed now",
        )

    if data.author.lower() != content.author.lower():
        raise HTTPException(status_code=403, detail="Only the content author can appeal")

    review = latest_review(db, content.id)
    decision = review.decisions[-1] if review and review.decisions else None
    if decision is None:
        raise HTTPException(status_code=409, detail="This content has no decision to appeal")

    try:
        appeal = create_appeal(db, content, decision, data.author, data.reason, data.evidence)
    except ValueError as error:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(error))

    db.commit()
    return {
        "appeal_id": appeal.id,
        "content_id": content.id,
        "appeal_status": appeal.status,
        "content_status": content.status,
    }


@router.get("")
def list_appeals(db: Session = Depends(get_db)):
    """Appeals waiting for a second reviewer, oldest first."""
    appeals = (
        db.query(models.Appeal)
        .filter(models.Appeal.status == "pending_second_review")
        .order_by(models.Appeal.id)
        .all()
    )
    rows = []
    for appeal in appeals:
        decision = appeal.decision
        content = decision.review.content
        rows.append({
            "appeal_id": appeal.id,
            "content_id": content.id,
            "author": content.author,
            "original_moderator": decision.moderator,
            "original_final_action": decision.final_action,
            "reason_preview": appeal.reason[:100],
            "submitted_at": appeal.created_at,
        })
    return rows


@router.get("/{appeal_id}")
def get_appeal(appeal_id: int, db: Session = Depends(get_db)):
    """The full story: original decision, appeal evidence, and final outcome."""
    appeal = db.get(models.Appeal, appeal_id)
    if appeal is None:
        raise HTTPException(status_code=404, detail="Appeal not found")

    decision = appeal.decision
    review = decision.review
    content = review.content
    parent = db.get(models.Content, content.parent_id) if content.parent_id else None

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
        "original_review": review_details(review),
        "original_decision": {
            "decision_id": decision.id,
            "moderator": decision.moderator,
            "action": decision.action,
            "final_action": decision.final_action,
            "note": decision.note,
            "policy_version_id": decision.policy_version_id,
        },
        "appeal": {
            "appeal_id": appeal.id,
            "status": appeal.status,
            "reason": appeal.reason,
            "evidence": appeal.evidence,
            "submitted_at": appeal.created_at,
        },
        "outcome": (
            {
                "second_reviewer": appeal.second_reviewer,
                "outcome": appeal.outcome,
                "final_action": appeal.final_action,
                "note": appeal.outcome_note,
            }
            if appeal.outcome else None
        ),
        # The action in force right now
        "current_final_action": appeal.final_action or decision.final_action,
    }


@router.post("/{appeal_id}/resolve")
def resolve(appeal_id: int, data: AppealResolve, db: Session = Depends(get_db)):
    appeal = db.get(models.Appeal, appeal_id)
    if appeal is None:
        raise HTTPException(status_code=404, detail="Appeal not found")

    if appeal.status != "pending_second_review":
        raise HTTPException(status_code=409, detail="This appeal has already been resolved")

    decision = appeal.decision
    content = decision.review.content

    try:
        resolve_appeal(
            db, appeal, content, decision,
            data.second_reviewer, data.outcome, data.final_action, data.note,
        )
    except ValueError as error:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(error))

    db.commit()  # outcome, history fix, status change, and audit log saved together
    return {
        "appeal_id": appeal.id,
        "content_id": content.id,
        "content_status": content.status,
        "outcome": appeal.outcome,
        "final_action": appeal.final_action,
        "second_reviewer": appeal.second_reviewer,
    }