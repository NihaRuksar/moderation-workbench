import json
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app import models
from app.database import get_db
from app.services.ai_review import run_ai_review
from app.services.audit import log_action
from app.services.checks import run_checks
from app.services.policy import get_active_policy
from app.services.workflow import change_status

router = APIRouter(prefix="/content", tags=["content"])


class ContentCreate(BaseModel):
    # Strips spaces first, so a body of only spaces fails min_length
    model_config = ConfigDict(str_strip_whitespace=True)

    content_type: Literal["post", "comment", "report"]
    body: str = Field(min_length=1, max_length=5000)
    author: str = Field(min_length=1, max_length=100)
    parent_id: Optional[int] = None


@router.post("")
def submit_content(data: ContentCreate, db: Session = Depends(get_db)):
    # 1. If a parent is given, it must exist
    if data.parent_id is not None:
        parent = db.get(models.Content, data.parent_id)
        if parent is None:
            raise HTTPException(status_code=400, detail="parent_id does not exist")

    # 2. Create the content row. flush() gives it an id without saving permanently
    content = models.Content(
        content_type=data.content_type,
        body=data.body,
        author=data.author,
        parent_id=data.parent_id,
    )
    db.add(content)
    db.flush()

    # 3. Run the plain-code checks
    flags = run_checks(db, content)

    # 4. Save a review that records the flags and the policy version used
    policy = get_active_policy(db)
    review = models.Review(
        content_id=content.id,
        policy_version_id=policy.id,
        deterministic_flags=json.dumps(flags),
    )
    db.add(review)

    # 5. Audit log
    log_action(db, data.author, "content_submitted", "content", content.id,
               f"type={data.content_type}")
    log_action(db, "system", "deterministic_checks_run", "content", content.id,
               f"{len(flags)} flag(s)")

    # 6. One commit for everything
    db.commit()

    # 7. Response
    return {"id": content.id, "status": content.status, "flags": flags}


@router.post("/{content_id}/review")
def review_content(content_id: int, db: Session = Depends(get_db)):
    # 1. The content must exist
    content = db.get(models.Content, content_id)
    if content is None:
        raise HTTPException(status_code=404, detail="Content not found")

    # 2. It must not have been reviewed already
    if content.status != "submitted":
        raise HTTPException(
            status_code=409,
            detail=f"Content is '{content.status}', so it cannot be AI-reviewed again",
        )

    # 3. Find the latest review. Seeded demo items have none, so create one.
    policy = get_active_policy(db)
    review = (
        db.query(models.Review)
        .filter(models.Review.content_id == content.id)
        .order_by(models.Review.id.desc())
        .first()
    )
    if review is None:
        flags = run_checks(db, content)
        review = models.Review(
            content_id=content.id,
            policy_version_id=policy.id,
            deterministic_flags=json.dumps(flags),
        )
        db.add(review)
    else:
        flags = json.loads(review.deterministic_flags)

    # 4. Ask the AI (this never crashes: it falls back if the AI fails)
    result = run_ai_review(db, content, policy, flags)

    # 5. Save the result on the same review row
    review.policy_version_id = policy.id
    review.findings = json.dumps({
        "findings": result["findings"],
        "reasoning": result["reasoning"],
        "validation_notes": result["validation_notes"],
        "ai_used": result["ai_used"],
    })
    review.proposed_action = result["proposed_action"]
    review.severity = result["severity"]
    review.confidence = result["confidence"]
    review.needs_human = result["needs_human"]

    # 6. Move the status forward, one allowed step at a time
    change_status(db, content, "ai_reviewed", "ai")
    change_status(db, content, "pending_moderator", "system")

    # 7. Audit log
    action_name = "ai_review_completed" if result["ai_used"] else "ai_review_fallback"
    log_action(
        db, "ai", action_name, "content", content.id,
        f"action={result['proposed_action']}, severity={result['severity']}, "
        f"confidence={result['confidence']}",
    )

    # 8. One commit, then return everything
    db.commit()
    return {
        "id": content.id,
        "status": content.status,
        "review_id": review.id,
        "policy_version_id": policy.id,
        **result,
    }


@router.get("")
def list_content(db: Session = Depends(get_db)):
    items = db.query(models.Content).order_by(models.Content.id).all()
    return [
        {
            "id": c.id,
            "content_type": c.content_type,
            "author": c.author,
            "status": c.status,
            "body": c.body,
        }
        for c in items
    ]


@router.get("/{content_id}")
def get_content(content_id: int, db: Session = Depends(get_db)):
    content = db.get(models.Content, content_id)
    if content is None:
        raise HTTPException(status_code=404, detail="Content not found")

    # Use the latest review's flags. Seeded demo items have no review yet.
    flags = []
    if content.reviews:
        flags = json.loads(content.reviews[-1].deterministic_flags)

    return {
        "id": content.id,
        "content_type": content.content_type,
        "author": content.author,
        "body": content.body,
        "status": content.status,
        "parent_id": content.parent_id,
        "flags": flags,
    }