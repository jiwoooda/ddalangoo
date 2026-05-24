from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, CreatedAtMixin, IdMixin, TimestampMixin


class Conversation(IdMixin, TimestampMixin, Base):
    """비즈니스 DB에서 하나의 구매 대화 흐름을 묶는 단위다."""

    __tablename__ = "conversations"

    user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("users.id"),
        nullable=False,
        index=True,
    )
    langgraph_thread_id: Mapped[str | None] = mapped_column(String, index=True)
    status: Mapped[str] = mapped_column(String, nullable=False, index=True)
    stage: Mapped[str] = mapped_column(String, nullable=False, index=True)
    keyword: Mapped[str | None] = mapped_column(String)
    summary: Mapped[str | None] = mapped_column(Text)
    summary_message_count: Mapped[int | None] = mapped_column(Integer)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    user = relationship("User")
    messages: Mapped[list["ConversationMessage"]] = relationship(
        back_populates="conversation",
        cascade="all, delete-orphan",
    )


class ConversationMessage(IdMixin, CreatedAtMixin, Base):
    """사용자/assistant/tool 메시지 원문을 분석용으로 저장한다."""

    __tablename__ = "conversation_messages"

    conversation_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("conversations.id"),
        nullable=False,
        index=True,
    )
    role: Mapped[str] = mapped_column(String, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)

    conversation: Mapped["Conversation"] = relationship(back_populates="messages")


class AgentIntent(IdMixin, CreatedAtMixin, Base):
    """Intent Agent가 사용자 요청을 어떻게 해석했는지 저장한다."""

    __tablename__ = "agent_intents"

    conversation_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("conversations.id"),
        nullable=False,
        index=True,
    )
    user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("users.id"),
        nullable=False,
        index=True,
    )
    raw_user_request: Mapped[str] = mapped_column(Text, nullable=False)
    intent: Mapped[str] = mapped_column(String, nullable=False)
    intent_type: Mapped[str] = mapped_column(String, nullable=False)
    stage: Mapped[str | None] = mapped_column(String)
    pending_action_type: Mapped[str | None] = mapped_column(String)
    target_category: Mapped[str | None] = mapped_column(String)
    target_product_name: Mapped[str | None] = mapped_column(String)
    extracted_keywords: Mapped[str | None] = mapped_column(Text)
    confidence: Mapped[float | None]
    needs_clarification: Mapped[bool | None]
    clarification_reason: Mapped[str | None] = mapped_column(Text)

    conversation = relationship("Conversation")
    user = relationship("User")
