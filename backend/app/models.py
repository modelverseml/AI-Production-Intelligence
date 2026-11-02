from datetime import datetime, timezone

from sqlalchemy import String, Integer, Float, ForeignKey, DateTime, Text, JSON
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base

def utc_now():
    return datetime.now(timezone.utc)

class User(Base):

    __tablename__="users"
    id : Mapped[int] = mapped_column(
        Integer, primary_key = True
    )
    email : Mapped[str] = mapped_column(
        String(255), unique = True, index = True
    )
    password_hash : Mapped[str] = mapped_column(
        String(500)
    )
    role : Mapped[str] = mapped_column(
        String(20), default = "viewer"
    )

class Service(Base):
    __tablename__ = "services"
    id : Mapped[int] = mapped_column(
        Integer, primary_key = True
    )
    name : Mapped[str] = mapped_column(
        String(100), unique = True
    )
    dependencies : Mapped[list] = mapped_column(
        JSON, default = list
    )

class Runbook(Base):

    __tablename__ = "runbooks"
    id : Mapped[int] = mapped_column(
        Integer, primary_key = True
    )
    code : Mapped[str] = mapped_column(
        String(40), unique = True
    )
    title : Mapped[str] = mapped_column(String(200))
    # Root-cause category the runbook addresses; "GENERAL" for distractor docs.
    # Used only as a relevance label during evaluation, never by the agent.
    category : Mapped[str] = mapped_column(
        String(60), default = "GENERAL"
    )
    body : Mapped[str] = mapped_column(Text)

class Incident(Base):

    __tablename__ = "incidents"

    id : Mapped[int] = mapped_column(
        Integer, primary_key = True,
    )
    title : Mapped[str] = mapped_column(String(255))
    description : Mapped[str] = mapped_column(Text)

    service_id : Mapped[int] = mapped_column(
        ForeignKey("services.id")
    )
    severity : Mapped[str] = mapped_column(String(20))
    logs : Mapped[list] = mapped_column(JSON)
    metrics : Mapped[dict] = mapped_column(JSON)
    # Benchmark ground-truth label, "service (fault)". Never shown to the agent.
    root_cause : Mapped[str] = mapped_column(
        String(120)
    )
    system : Mapped[str | None] = mapped_column(
        String(60), nullable = True
    )
    # RCAEval case folder. Its name encodes the label, so it is never sent to clients.
    case_id : Mapped[str | None] = mapped_column(
        String(120), nullable = True, unique = True
    )

    created_at : Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default = utc_now
    )

class Investigation(Base):

    __tablename__ = "investigations"

    id : Mapped[int] = mapped_column(
        Integer, primary_key = True
    )
    incident_id : Mapped[int] = mapped_column(
        ForeignKey("incidents.id"), index = True
    )
    user_id : Mapped[int] = mapped_column(
        ForeignKey("users.id")
    )

    predicted_cause : Mapped[str] = mapped_column(
        String(120)
    )
    # "agent" (LLM only) or "hybrid" (LLM + ML ranker prior).
    method : Mapped[str] = mapped_column(
        String(20), default = "hybrid"
    )

    confidence : Mapped[float] = mapped_column(Float)
    explanation : Mapped[str] = mapped_column(Text)
    evidence : Mapped[list] = mapped_column(JSON)
    report : Mapped[dict] = mapped_column(JSON, default = dict)
    verification : Mapped[dict] = mapped_column(JSON, default = dict)
    trace : Mapped[list] = mapped_column(JSON, default = list)
    usage : Mapped[dict] = mapped_column(JSON, default = dict)
    created_at : Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default = utc_now
    )
