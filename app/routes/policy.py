from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app import models
from app.database import get_db
from app.services.policy import create_new_version, get_active_policy, reevaluate_unresolved

router = APIRouter(prefix="/policy", tags=["policy"])


class RuleChange(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    clause_id: str = Field(min_length=1, max_length=20)
    title: str = Field(min_length=1, max_length=200)
    text: str = Field(min_length=1, max_length=2000)
    severity_default: Literal["low", "medium", "high"]


class PolicyCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    created_by: str = Field(min_length=1, max_length=100)
    notes: str = Field(min_length=1, max_length=2000)
    changes: list[RuleChange] = []
    remove_clauses: list[str] = []


@router.get("")
def list_versions(db: Session = Depends(get_db)):
    versions = (
        db.query(models.PolicyVersion)
        .order_by(models.PolicyVersion.version_number)
        .all()
    )
    return [
        {
            "version_number": v.version_number,
            "is_active": v.is_active,
            "rule_count": len(v.rules),
            "notes": v.notes,
            "created_at": v.created_at,
        }
        for v in versions
    ]


@router.post("")
def create_version(data: PolicyCreate, db: Session = Depends(get_db)):
    # Step 1: create and activate the new version, then save it
    try:
        new_version = create_new_version(
            db,
            data.created_by,
            data.notes,
            [change.model_dump() for change in data.changes],
            data.remove_clauses,
        )
    except ValueError as error:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(error))
    db.commit()

    # Step 2: re-evaluate the items that are still waiting for a moderator
    results = reevaluate_unresolved(db, data.created_by)

    return {
        "version_number": new_version.version_number,
        "policy_version_id": new_version.id,
        "rule_count": len(new_version.rules),
        "reevaluated_count": len(results),
        "reevaluated": results,
    }


@router.post("/reevaluate")
def reevaluate(db: Session = Depends(get_db)):
    """Finish re-evaluation for items still on an older version. Safe to run twice."""
    policy = get_active_policy(db)
    results = reevaluate_unresolved(db, "system")
    return {
        "active_version": policy.version_number,
        "reevaluated_count": len(results),
        "reevaluated": results,
    }


@router.get("/{version_number}")
def get_version(version_number: int, db: Session = Depends(get_db)):
    version = (
        db.query(models.PolicyVersion)
        .filter(models.PolicyVersion.version_number == version_number)
        .first()
    )
    if version is None:
        raise HTTPException(status_code=404, detail="Policy version not found")
    return {
        "version_number": version.version_number,
        "is_active": version.is_active,
        "notes": version.notes,
        "rules": [
            {
                "clause_id": r.clause_id,
                "title": r.title,
                "text": r.text,
                "severity_default": r.severity_default,
            }
            for r in version.rules
        ],
    }