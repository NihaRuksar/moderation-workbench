from app import models


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