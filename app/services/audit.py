from app import models


def log_action(db, actor, action, entity_type, entity_id=None, details=None):
    """Add an audit log row. Does NOT commit: the caller commits,
    so the log entry and the action it describes are saved together."""
    entry = models.AuditLog(
        actor=actor,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        details=details,
    )
    db.add(entry)
    return entry