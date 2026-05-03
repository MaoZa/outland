from datetime import datetime
from sqlalchemy import String, Integer, Boolean, DateTime, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from . import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    hashed_password: Mapped[str] = mapped_column(String(255))
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    containers: Mapped[list["Container"]] = relationship(back_populates="user")
    quota: Mapped["Quota"] = relationship(back_populates="user", uselist=False)


class Container(Base):
    __tablename__ = "containers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    uuid: Mapped[str] = mapped_column(String(36), unique=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    agent_id: Mapped[str] = mapped_column(String(255), nullable=False)
    container_id: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(50), default="running")
    resolution: Mapped[str] = mapped_column(String(20), default="720x1280")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    user: Mapped["User"] = relationship(back_populates="containers")


class Quota(Base):
    __tablename__ = "quotas"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), unique=True, nullable=False)
    max_containers: Mapped[int] = mapped_column(Integer, default=1)

    user: Mapped["User"] = relationship(back_populates="quota")


class AgentState(Base):
    __tablename__ = "agent_states"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    agent_id: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    url: Mapped[str] = mapped_column(String(255))
    last_heartbeat: Mapped[float] = mapped_column(nullable=False)


class ExternalDevice(Base):
    __tablename__ = "external_devices"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    uuid: Mapped[str] = mapped_column(String(36), unique=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    agent_id: Mapped[str] = mapped_column(String(255), nullable=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    adb_host: Mapped[str] = mapped_column(String(255), nullable=False)
    adb_port: Mapped[int] = mapped_column(Integer, default=5555)
    rsa_key_path: Mapped[str] = mapped_column(String(512), nullable=True)
    status: Mapped[str] = mapped_column(String(50), default="active")
    resolution: Mapped[str] = mapped_column(String(20), default="720x1280")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
