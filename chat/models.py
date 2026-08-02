from sqlalchemy import (
    Column, Text, Integer, ForeignKey, CheckConstraint, Date
)
from sqlalchemy.orm import declarative_base

Base = declarative_base()

class Member(Base):
    __tablename__ = "members"

    id = Column(Text, primary_key=True)
    password_hash = Column(Text, nullable=False)
    name = Column(Text, nullable=False, unique=True)
    salt = Column(Text, nullable=False)
    created_at = Column(Date)


class RefreshToken(Base):
    __tablename__ = "refresh_tokens"

    jti = Column(Text, primary_key=True)
    user_id = Column(Text, ForeignKey("members.id"), nullable=False)
    expires_at = Column(Date, nullable=False)
    revoked = Column(Integer, nullable=False, default=0)


class Chat(Base):
    __tablename__ = "chats"

    chat_id = Column(Text, primary_key=True)
    user_id = Column(Text, ForeignKey("members.id"), primary_key=True)
    other_id = Column(Text, ForeignKey("members.id"))


class GlobalMessage(Base):
    __tablename__ = "global_messages"

    id = Column(Integer, primary_key=True, autoincrement=True)
    sender_id = Column(Text, ForeignKey("members.id"), nullable=False)
    sender = Column(Text, nullable=False)
    text = Column(Text, nullable=False)
    timestamp = Column(Date, nullable=False)


class P2PMessage(Base):
    __tablename__ = "p2p_messages"

    id = Column(Integer, primary_key=True, autoincrement=True)
    chat_id = Column(Text, nullable=False)
    sender_id = Column(Text, nullable=False)
    sender = Column(Text, nullable=False)
    text = Column(Text, nullable=False)
    timestamp = Column(Date, nullable=False)


class MessageAttachment(Base):
    __tablename__ = "message_attachments"
    __table_args__ = (
        CheckConstraint("message_type IN ('global', 'p2p')"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    message_id = Column(Integer, nullable=False)
    message_type = Column(Text, nullable=False)
    url = Column(Text, nullable=False)
    mime = Column(Text)
    original_name = Column(Text)