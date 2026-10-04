from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


def now():
    """Current time in UTC. Used as the default for every created_at column."""
    return datetime.now(timezone.utc)


class PolicyVersion(Base): #Each version of the policy, and which one is active
    __tablename__ = "policy_versions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    version_number: Mapped[int] = mapped_column(Integer, unique=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)

    rules: Mapped[list["PolicyRule"]] = relationship(back_populates="policy_version")


class PolicyRule(Base): #The rules (clause ID, title, text) belonging to one policy version
    __tablename__ = "policy_rules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    policy_version_id: Mapped[int] = mapped_column(ForeignKey("policy_versions.id"))
    clause_id: Mapped[str] = mapped_column(String(20))  # for example "3.2"
    title: Mapped[str] = mapped_column(String(200))
    text: Mapped[str] = mapped_column(Text)
    severity_default: Mapped[str] = mapped_column(String(20), default="medium")  # low / medium / high
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)

    policy_version: Mapped["PolicyVersion"] = relationship(back_populates="rules")


class Content(Base): #Posts, comments, and user reports, with a status showing where each is in the workflow
    __tablename__ = "content"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    content_type: Mapped[str] = mapped_column(String(20))  # post / comment / report
    body: Mapped[str] = mapped_column(Text)
    author: Mapped[str] = mapped_column(String(100))
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("content.id"), nullable=True)
    # status: submitted / ai_reviewed / pending_moderator / decided /
    #         appealed / second_review / final
    status: Mapped[str] = mapped_column(String(30), default="submitted")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)

    reviews: Mapped[list["Review"]] = relationship(back_populates="content")


class ModerationHistory(Base): #Past actions against an author (used for repeat-offender checks)
    __tablename__ = "moderation_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    author: Mapped[str] = mapped_column(String(100))
    action: Mapped[str] = mapped_column(String(50))  # for example warning, removed
    content_id: Mapped[int | None] = mapped_column(ForeignKey("content.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class Review(Base): #The AI and code findings for one piece of content: cited clauses, severity, confidence, proposed action, and a "needs human" flag
    __tablename__ = "reviews"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    content_id: Mapped[int] = mapped_column(ForeignKey("content.id"))
    policy_version_id: Mapped[int] = mapped_column(ForeignKey("policy_versions.id"))
    findings: Mapped[str] = mapped_column(Text, default="[]")  # JSON text from the AI
    deterministic_flags: Mapped[str] = mapped_column(Text, default="[]")  # JSON text from code checks
    proposed_action: Mapped[str] = mapped_column(String(50), default="no_action")
    severity: Mapped[str] = mapped_column(String(20), default="low")  # low / medium / high
    confidence: Mapped[float] = mapped_column(Float, default=0.0)  # 0.0 to 1.0
    needs_human: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)

    content: Mapped["Content"] = relationship(back_populates="reviews")
    decisions: Mapped[list["Decision"]] = relationship(back_populates="review")


class Decision(Base): #The moderator's approve, reject, or modify, and the final action
    __tablename__ = "decisions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    review_id: Mapped[int] = mapped_column(ForeignKey("reviews.id"))
    moderator: Mapped[str] = mapped_column(String(100))
    action: Mapped[str] = mapped_column(String(20))  # approve / reject / modify
    final_action: Mapped[str] = mapped_column(String(50))  # what actually happens
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    policy_version_id: Mapped[int] = mapped_column(ForeignKey("policy_versions.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)

    review: Mapped["Review"] = relationship(back_populates="decisions")
    appeals: Mapped[list["Appeal"]] = relationship(back_populates="decision")


class Appeal(Base): #The author's appeal, the second reviewer, and the outcome
    __tablename__ = "appeals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    decision_id: Mapped[int] = mapped_column(ForeignKey("decisions.id"))
    reason: Mapped[str] = mapped_column(Text)
    evidence: Mapped[str | None] = mapped_column(Text, nullable=True)
    # status: pending_second_review / decided
    status: Mapped[str] = mapped_column(String(30), default="pending_second_review")
    second_reviewer: Mapped[str | None] = mapped_column(String(100), nullable=True)
    outcome: Mapped[str | None] = mapped_column(String(20), nullable=True)  # upheld / overturned / modified
    final_action: Mapped[str | None] = mapped_column(String(50), nullable=True)  # the action in force after the appeal
    outcome_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)

    decision: Mapped["Decision"] = relationship(back_populates="appeals")


class AuditLog(Base): #A record of every action, with who did it and when
    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    actor: Mapped[str] = mapped_column(String(100))  # a username, "system" or "ai"
    action: Mapped[str] = mapped_column(String(100))
    entity_type: Mapped[str] = mapped_column(String(50))
    entity_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    details: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)  # this is the timestamp