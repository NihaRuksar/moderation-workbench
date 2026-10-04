import json
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app import models
from app.database import get_db
from app.services.audit import log_action
from app.services.checks import run_checks
from app.services.policy import get_active_policy

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