from app import models
from app.database import Base, SessionLocal, engine


def seed():
    """Create the tables and add policy v1 and demo data. Safe to run twice."""
    Base.metadata.create_all(engine)
    db = SessionLocal()
    try:
        # If a policy already exists, the database is seeded. Do nothing.
        if db.query(models.PolicyVersion).count() > 0:
            return

        # 1. Policy version 1 (the active one)
        policy = models.PolicyVersion(
            version_number=1,
            is_active=True,
            notes="Initial community policy",
        )
        db.add(policy)
        db.flush()  # sends the row to the database so policy.id is available

        # 2. Rules for policy v1
        rules = [
            ("1.1", "Harassment",
            "Content must not insult, demean, or intimidate a specific person, or repeatedly target them after they have asked for it to stop.",
            "medium"),
            ("1.2", "Hate speech",
            "Content must not attack or dehumanize people because of race, ethnicity, religion, caste, gender, sexual orientation, disability, or nationality.",
            "high"),
            ("2.1", "Threats of violence",
            "Content must not threaten, encourage, or celebrate violence or serious harm against any person or group.",
            "high"),
            ("2.2", "Doxxing",
            "Content must not share private personal information about someone without their consent, such as home address, phone number, or workplace.",
            "high"),
            ("3.1", "Spam",
            "Content must not be repeated, unsolicited, or contain multiple promotional links posted only to drive traffic.",
            "low"),
            ("3.2", "Self-promotion",
            "Promotion of your own products or services is allowed only in the designated promotion area, and not in replies or unrelated posts.",
            "low"),
            ("4.1", "Harmful misinformation",
            "Content must not present clearly false claims as fact where they could cause real harm, such as dangerous health or safety advice.",
            "medium"),
            ("4.2", "Impersonation",
            "Content must not pretend to be another person, a moderator, or an official organization in a misleading way.",
            "medium"),
        ]
        for clause_id, title, text, severity in rules:
            db.add(
                models.PolicyRule(
                    policy_version_id=policy.id,
                    clause_id=clause_id,
                    title=title,
                    text=text,
                    severity_default=severity,
                )
            )

        # 3. Demo content
        post = models.Content(
            content_type="post",
            body="Has anyone tried the new library update? It fixed my bug.",
            author="alice",
        )
        db.add(post)
        db.flush()

        db.add_all([
            models.Content(
                content_type="comment",
                body="You are an idiot and everyone here hates you.",
                author="bob",
                parent_id=post.id,
            ),
            models.Content(
                content_type="post",
                body="BUY CHEAP WATCHES NOW!!! http://spam1.test http://spam2.test http://spam3.test",
                author="spammer_sam",
            ),
            models.Content(
                content_type="comment",
                body="I know where you live and I will find you.",
                author="dave",
                parent_id=post.id,
            ),
            models.Content(
                content_type="report",
                body="Reporting bob's comment above for harassment.",
                author="alice",
                parent_id=post.id,
            ),
        ])

        # 4. Moderation history (lets the repeat-offender check work later)
        db.add_all([
            models.ModerationHistory(author="spammer_sam", action="warning"),
            models.ModerationHistory(author="spammer_sam", action="content_removed"),
        ])

        # 5. First audit log entry
        db.add(
            models.AuditLog(
                actor="system",
                action="seed_database",
                entity_type="policy_version",
                entity_id=policy.id,
                details="Seeded policy v1 with 7 rules and demo content",
            )
        )

        db.commit()
    finally:
        db.close()


if __name__ == "__main__":
    seed()
    print("Seed complete")