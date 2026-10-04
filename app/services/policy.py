import json

from sqlalchemy import func

from app import models
from app.services.ai_review import run_ai_review
from app.services.audit import log_action
from app.services.checks import run_checks


def get_active_policy(db):
    """Return the currently active policy version."""
    policy = (
        db.query(models.PolicyVersion)
        .filter(models.PolicyVersion.is_active.is_(True))
        .first()
    )
    if policy is None:
        raise RuntimeError("No active policy version found. Run the seed first.")
    return policy


def create_new_version(db, actor, notes, changes, remove_clauses):
    """Build a new policy version from the active one and make it active.
    changes: list of dicts with clause_id, title, text, severity_default
             (adds the clause, or replaces it if it already exists).
    remove_clauses: list of clause IDs to leave out of the new version.
    Raises ValueError if a rule is broken. Does NOT commit."""
    current = get_active_policy(db)

    # Start from the active version's rules
    rules = {
        r.clause_id: {
            "title": r.title,
            "text": r.text,
            "severity_default": r.severity_default,
        }
        for r in current.rules
    }

    if not changes and not remove_clauses:
        raise ValueError("A new version needs at least one change or removal")

    changed_ids = {c["clause_id"] for c in changes}
    if len(changed_ids) != len(changes):
        raise ValueError("The same clause_id appears more than once in changes")

    remove_set = set(remove_clauses)
    both = changed_ids & remove_set
    if both:
        raise ValueError(f"Clause(s) {sorted(both)} are both changed and removed")

    unknown = [c for c in remove_set if c not in rules]
    if unknown:
        raise ValueError(f"Cannot remove clause(s) that do not exist: {sorted(unknown)}")

    for change in changes:
        rules[change["clause_id"]] = {
            "title": change["title"],
            "text": change["text"],
            "severity_default": change["severity_default"],
        }
    for clause_id in remove_set:
        del rules[clause_id]

    if not rules:
        raise ValueError("A policy needs at least one rule")

    # Create the new version and switch the active flag
    next_number = (db.query(func.max(models.PolicyVersion.version_number)).scalar() or 0) + 1
    current.is_active = False
    new_version = models.PolicyVersion(
        version_number=next_number, is_active=True, notes=notes
    )
    db.add(new_version)
    db.flush()  # gives the new version an id

    for clause_id, rule in rules.items():
        db.add(models.PolicyRule(
            policy_version_id=new_version.id,
            clause_id=clause_id,
            title=rule["title"],
            text=rule["text"],
            severity_default=rule["severity_default"],
        ))

    log_action(
        db, actor, "policy_version_created", "policy_version", new_version.id,
        f"v{current.version_number} -> v{new_version.version_number}; "
        f"changed={sorted(changed_ids)}; removed={sorted(remove_set)}; notes={notes}",
    )
    return new_version


def _latest_review(db, content_id):
    return (
        db.query(models.Review)
        .filter(models.Review.content_id == content_id)
        .order_by(models.Review.id.desc())
        .first()
    )


def reevaluate_unresolved(db, actor):
    """Re-review every item waiting for a moderator whose latest review used an
    older policy version. Each item gets a NEW review row, and the old one is kept.
    Each item is committed separately, so a stopped run can simply be run again."""
    policy = get_active_policy(db)
    valid_clauses = {r.clause_id for r in policy.rules}

    waiting = (
        db.query(models.Content)
        .filter(models.Content.status == "pending_moderator")
        .order_by(models.Content.id)
        .all()
    )

    results = []
    for content in waiting:
        try:
            old = _latest_review(db, content.id)
            if old is None or old.policy_version_id == policy.id:
                continue  # nothing to do for this item

            old_version = db.get(models.PolicyVersion, old.policy_version_id)

            # Fresh code checks, keeping only flags for clauses that still exist
            flags = [
                f for f in run_checks(db, content)
                if not f.get("clause_id") or f["clause_id"] in valid_clauses
            ]
            result = run_ai_review(db, content, policy, flags)

            new_review = models.Review(
                content_id=content.id,
                policy_version_id=policy.id,
                deterministic_flags=json.dumps(flags),
                findings=json.dumps({
                    "findings": result["findings"],
                    "reasoning": result["reasoning"],
                    "validation_notes": result["validation_notes"],
                    "ai_used": result["ai_used"],
                }),
                proposed_action=result["proposed_action"],
                severity=result["severity"],
                confidence=result["confidence"],
                needs_human=result["needs_human"],
            )
            db.add(new_review)

            entry = {
                "content_id": content.id,
                "old_policy_version": old_version.version_number,
                "new_policy_version": policy.version_number,
                "old_action": old.proposed_action,
                "new_action": result["proposed_action"],
                "old_severity": old.severity,
                "new_severity": result["severity"],
                "ai_used": result["ai_used"],
            }
            entry["changed"] = (
                entry["old_action"] != entry["new_action"]
                or entry["old_severity"] != entry["new_severity"]
            )

            log_action(
                db, "system", "item_reevaluated", "content", content.id,
                f"policy v{entry['old_policy_version']} -> v{entry['new_policy_version']}; "
                f"action {entry['old_action']} -> {entry['new_action']}; "
                f"severity {entry['old_severity']} -> {entry['new_severity']}; "
                f"ai_used={result['ai_used']}",
            )
            db.commit()
            results.append(entry)

        except Exception as error:
            db.rollback()
            results.append({"content_id": content.id, "error": type(error).__name__})

    if results:
        log_action(
            db, actor, "reevaluation_completed", "policy_version", policy.id,
            f"{len(results)} item(s) processed under v{policy.version_number}",
        )
        db.commit()
    return results