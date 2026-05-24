from sqlalchemy import BigInteger, Boolean, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, CreatedAtMixin, IdMixin


class AgentEvent(IdMixin, CreatedAtMixin, Base):
    """Agent 실행 순서, 라우팅, 실패 지점을 추적하는 내부 실행 로그다."""

    __tablename__ = "agent_events"

    conversation_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("conversations.id"),
        nullable=False,
        index=True,
    )
    agent_name: Mapped[str] = mapped_column(String, nullable=False, index=True)
    event_type: Mapped[str] = mapped_column(String, nullable=False, index=True)
    input_summary: Mapped[str | None] = mapped_column(Text)
    output_summary: Mapped[str | None] = mapped_column(Text)
    error_message: Mapped[str | None] = mapped_column(Text)
    latency_ms: Mapped[int | None] = mapped_column(Integer)

    conversation = relationship("Conversation")


class ExternalApiLog(IdMixin, CreatedAtMixin, Base):
    """외부 API, 크롤링, MCP tool 호출 결과 요약을 저장한다."""

    __tablename__ = "external_api_logs"

    user_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("users.id"))
    conversation_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("conversations.id"))
    provider: Mapped[str] = mapped_column(String, nullable=False, index=True)
    api_name: Mapped[str] = mapped_column(String, nullable=False)
    request_summary: Mapped[str | None] = mapped_column(Text)
    response_summary: Mapped[str | None] = mapped_column(Text)
    status_code: Mapped[int | None] = mapped_column(Integer)
    success: Mapped[bool] = mapped_column(Boolean, nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text)
    latency_ms: Mapped[int | None] = mapped_column(Integer)

    user = relationship("User")
    conversation = relationship("Conversation")
