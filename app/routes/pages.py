import re
from pathlib import Path
from typing import Optional
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app import models
from app.database import get_db
from app.routes import appeals as appeal_routes
from app.routes import content as content_routes
from app.routes import policy as policy_routes
from app.routes import queue as queue_routes
from app.services.policy import get_active_policy

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

# Which badge color each value gets (neutral gray, with red and amber for alerts)
BADGE_COLORS = {
    "high": "red", "remove_content": "red",
    "medium": "amber", "warn": "amber", "escalate": "amber", "uncertain": "amber",
    "pending_moderator": "amber", "appealed": "amber", "second_review": "amber",
    "pending_second_review": "amber", "overturned": "amber", "modified": "amber",
    "low": "gray", "no_action": "gray", "submitted": "gray", "ai_reviewed": "gray",
    "confirmed": "dark", "decided": "dark", "final": "dark", "upheld": "dark",
}


def badge(value):
    return BADGE_COLORS.get(str(value), "gray")


def pretty(value):
    return str(value).replace("_", " ")


def fmt_dt(value):
    return value.strftime("%d %b %Y, %H:%M") + " UTC" if value else ""


templates.env.globals["badge"] = badge
templates.env.filters["pretty"] = pretty
templates.env.filters["dt"] = fmt_dt

# include_in_schema=False keeps these pages out of /docs
router = APIRouter(prefix="/ui", include_in_schema=False)


def render(request, name, active, **context):
    kind = request.query_params.get("kind", "ok")
    context["active"] = active
    context["msg"] = request.query_params.get("msg")
    context["kind"] = kind if kind in ("ok", "error", "warn") else "ok"
    return templates.TemplateResponse(request, name, context)


def go(url, message, kind="ok"):
    """Redirect to a page and show a message banner there."""
    separator = "&" if "?" in url else "?"
    query = urlencode({"msg": message, "kind": kind})
    return RedirectResponse(f"{url}{separator}{query}", status_code=303)


def error_text(error):
    """Turn an API error into a short message for the banner."""
    if isinstance(error, HTTPException):
        return str(error.detail)
    parts = []
    for item in error.errors():
        field = ".".join(str(p) for p in item["loc"])
        parts.append(f"{field}: {item['msg']}")
    return "; ".join(parts)


def _numbers(db):
    """Map a policy version id to its version number, for showing 'v2'."""
    return {v.id: v.version_number for v in db.query(models.PolicyVersion).all()}


# ---------- Queue and content ----------

@router.get("/queue")
def queue_page(request: Request, db: Session = Depends(get_db)):
    rows = queue_routes.get_queue(db)
    pending_appeals = len(appeal_routes.list_appeals(db))
    return render(request, "queue.html", "queue", rows=rows, pending_appeals=pending_appeals)


@router.get("/content")
def content_page(request: Request, db: Session = Depends(get_db)):
    items = content_routes.list_content(db)
    return render(request, "content_list.html", "content", items=items)


@router.get("/submit")
def submit_page(request: Request):
    return render(request, "submit.html", "submit")


@router.post("/submit")
def submit_action(
    content_type: str = Form(""),
    author: str = Form(""),
    body: str = Form(""),
    parent_id: str = Form(""),
    db: Session = Depends(get_db),
):
    parent_text = parent_id.strip()
    if parent_text and not parent_text.isdigit():
        return go("/ui/submit", "Parent ID must be a number", "error")
    try:
        data = content_routes.ContentCreate(
            content_type=content_type,
            body=body,
            author=author,
            parent_id=int(parent_text) if parent_text else None,
        )
        result = content_routes.submit_content(data, db)
    except (HTTPException, ValidationError) as error:
        return go("/ui/submit", error_text(error), "error")
    return go(
        f"/ui/content/{result['id']}",
        f"Submitted. The automatic checks raised {len(result['flags'])} flag(s).",
    )


@router.get("/content/{content_id}")
def content_detail(content_id: int, request: Request, db: Session = Depends(get_db)):
    content = db.get(models.Content, content_id)
    if content is None:
        return go("/ui/content", "Content not found", "error")

    parent = db.get(models.Content, content.parent_id) if content.parent_id else None
    review = queue_routes.latest_review(db, content.id)
    details = queue_routes.review_details(review) if review else None
    decision = review.decisions[-1] if review and review.decisions else None
    appeal = decision.appeals[-1] if decision and decision.appeals else None
    numbers = _numbers(db)

    # Clause titles from the policy version this review used
    titles = {}
    if review:
        version = db.get(models.PolicyVersion, review.policy_version_id)
        titles = {rule.clause_id: rule.title for rule in version.rules}

    history = [
        {
            "id": r.id,
            "version": numbers.get(r.policy_version_id),
            "action": r.proposed_action,
            "severity": r.severity,
            "created_at": r.created_at,
        }
        for r in sorted(content.reviews, key=lambda r: r.id)
    ]

    can_appeal = (
        content.status == "decided"
        and decision is not None
        and decision.final_action in ("warn", "remove_content")
    )
    active = "queue" if content.status == "pending_moderator" else "content"

    return render(
        request, "content_detail.html", active,
        content=content,
        parent=parent,
        review=details,
        flags=details["deterministic_flags"] if details else [],
        decision=decision,
        appeal=appeal,
        numbers=numbers,
        titles=titles,
        history=history,
        can_review=content.status == "submitted",
        can_decide=content.status == "pending_moderator",
        can_appeal=can_appeal,
    )


@router.post("/content/{content_id}/review")
def review_action(content_id: int, db: Session = Depends(get_db)):
    url = f"/ui/content/{content_id}"
    try:
        result = content_routes.review_content(content_id, db)
    except HTTPException as error:
        return go(url, error_text(error), "error")
    if result["ai_used"]:
        return go(url, "AI review finished. A moderator must now decide.")
    return go(
        url,
        "The AI was unavailable, so a safe fallback result was saved. A human must review this item.",
        "warn",
    )


@router.post("/content/{content_id}/decision")
def decision_action(
    content_id: int,
    moderator: str = Form(""),
    action: str = Form(""),
    final_action: str = Form(""),
    note: str = Form(""),
    db: Session = Depends(get_db),
):
    url = f"/ui/content/{content_id}"
    try:
        data = queue_routes.DecisionCreate(
            moderator=moderator,
            action=action,
            final_action=final_action or None,
            note=note or None,
        )
        result = queue_routes.make_decision(content_id, data, db)
    except (HTTPException, ValidationError) as error:
        return go(url, error_text(error), "error")
    return go(url, f"Decision saved. Final action: {pretty(result['final_action'])}.")


@router.post("/content/{content_id}/appeal")
def appeal_action(
    content_id: int,
    author: str = Form(""),
    reason: str = Form(""),
    evidence: str = Form(""),
    db: Session = Depends(get_db),
):
    url = f"/ui/content/{content_id}"
    try:
        data = appeal_routes.AppealCreate(
            content_id=content_id,
            author=author,
            reason=reason,
            evidence=evidence or None,
        )
        result = appeal_routes.submit_appeal(data, db)
    except (HTTPException, ValidationError) as error:
        return go(url, error_text(error), "error")
    return go(
        f"/ui/appeals/{result['appeal_id']}",
        "Appeal submitted. It is waiting for a second reviewer.",
    )


# ---------- Appeals ----------

@router.get("/appeals")
def appeals_page(request: Request, db: Session = Depends(get_db)):
    pending = appeal_routes.list_appeals(db)
    resolved = []
    done = (
        db.query(models.Appeal)
        .filter(models.Appeal.status == "decided")
        .order_by(models.Appeal.id.desc())
        .all()
    )
    for appeal in done:
        content = appeal.decision.review.content
        resolved.append({
            "appeal_id": appeal.id,
            "content_id": content.id,
            "author": content.author,
            "second_reviewer": appeal.second_reviewer,
            "outcome": appeal.outcome,
            "final_action": appeal.final_action,
        })
    return render(request, "appeals.html", "appeals", pending=pending, resolved=resolved)


@router.get("/appeals/{appeal_id}")
def appeal_detail(appeal_id: int, request: Request, db: Session = Depends(get_db)):
    try:
        data = appeal_routes.get_appeal(appeal_id, db)
    except HTTPException as error:
        return go("/ui/appeals", error_text(error), "error")
    return render(request, "appeal_detail.html", "appeals", data=data, numbers=_numbers(db))


@router.post("/appeals/{appeal_id}/resolve")
def resolve_action(
    appeal_id: int,
    second_reviewer: str = Form(""),
    outcome: str = Form(""),
    final_action: str = Form(""),
    note: str = Form(""),
    db: Session = Depends(get_db),
):
    url = f"/ui/appeals/{appeal_id}"
    try:
        data = appeal_routes.AppealResolve(
            second_reviewer=second_reviewer,
            outcome=outcome,
            final_action=final_action or None,
            note=note,
        )
        appeal_routes.resolve(appeal_id, data, db)
    except (HTTPException, ValidationError) as error:
        return go(url, error_text(error), "error")
    return go(url, "Appeal resolved. The item is now final.")


# ---------- Policy ----------

@router.get("/policy")
def policy_page(request: Request, v: Optional[int] = None, db: Session = Depends(get_db)):
    versions = policy_routes.list_versions(db)
    active = get_active_policy(db)
    number = v if v is not None else active.version_number
    try:
        selected = policy_routes.get_version(number, db)
    except HTTPException:
        return go("/ui/policy", "That policy version does not exist", "error")
    return render(request, "policy.html", "policy", versions=versions, selected=selected)


@router.post("/policy/new")
def policy_new_action(
    created_by: str = Form(""),
    notes: str = Form(""),
    clause_id: str = Form(""),
    title: str = Form(""),
    text: str = Form(""),
    severity_default: str = Form("medium"),
    remove_clauses: str = Form(""),
    db: Session = Depends(get_db),
):
    changes = []
    if clause_id.strip():
        changes.append({
            "clause_id": clause_id,
            "title": title,
            "text": text,
            "severity_default": severity_default,
        })
    removals = [c.strip() for c in remove_clauses.split(",") if c.strip()]
    try:
        data = policy_routes.PolicyCreate(
            created_by=created_by,
            notes=notes,
            changes=[policy_routes.RuleChange(**c) for c in changes],
            remove_clauses=removals,
        )
        result = policy_routes.create_version(data, db)
    except (HTTPException, ValidationError) as error:
        return go("/ui/policy", error_text(error), "error")
    return go(
        "/ui/policy",
        f"Policy v{result['version_number']} is now active. "
        f"{result['reevaluated_count']} waiting item(s) were re-evaluated.",
    )


@router.post("/policy/reevaluate")
def policy_reevaluate_action(db: Session = Depends(get_db)):
    result = policy_routes.reevaluate(db)
    return go(
        "/ui/policy",
        f"Re-evaluated {result['reevaluated_count']} item(s) under v{result['active_version']}.",
    )


# ---------- Audit trail ----------

@router.get("/audit")
def audit_page(request: Request, content_id: Optional[int] = None, db: Session = Depends(get_db)):
    entries = db.query(models.AuditLog).order_by(models.AuditLog.id.desc()).all()
    if content_id is not None:
        # Entries about this item: its own, plus decisions and appeals that mention it
        pattern = re.compile(rf"content={content_id}\b")
        entries = [
            e for e in entries
            if (e.entity_type == "content" and e.entity_id == content_id)
            or (e.details and pattern.search(e.details))
        ]
        entries.reverse()  # oldest first reads as a timeline
    return render(
        request, "audit.html", "audit",
        entries=entries[:300],
        content_id=content_id,
    )