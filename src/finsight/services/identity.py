"""Local identity verification and short-lived, signed access tokens."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from re import fullmatch
from uuid import UUID, uuid4

import jwt
from pwdlib import PasswordHash
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from finsight.domain.access_control import Principal, Role, WorkspaceMembership
from finsight.infrastructure.database.models.document import Document
from finsight.infrastructure.database.models.knowledge_base import (
    KnowledgeBase,
    KnowledgeBaseDocument,
    KnowledgeBaseGrant,
)
from finsight.infrastructure.database.models.user_account import UserAccount
from finsight.infrastructure.database.models.workspace import Workspace, WorkspaceMember

_HASHER = PasswordHash.recommended()
_DUMMY_HASH = _HASHER.hash("this-account-does-not-exist")
_ISSUER = "finsight"
_AUDIENCE = "finsight-api"


class InvalidCredentials(ValueError):
    """Do not reveal whether the account, password, or token was wrong."""


class DuplicateAccount(ValueError):
    """An account already uses this normalized email."""


def _normalize_email(email: str) -> str:
    normalized = email.strip().casefold()
    if len(normalized) > 320 or not fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", normalized):
        raise ValueError("invalid email address")
    return normalized


class IdentityService:
    def __init__(self, session_factory: Callable[[], Session]) -> None:
        self._session_factory = session_factory

    def provision(self, email: str, password: str) -> UUID:
        normalized = _normalize_email(email)
        if not 12 <= len(password) <= 1024:
            raise ValueError("password must contain 12 to 1024 characters")
        account = UserAccount(email=normalized, password_hash=_HASHER.hash(password))
        with self._session_factory() as session:
            session.add(account)
            try:
                session.commit()
            except IntegrityError as error:
                session.rollback()
                raise DuplicateAccount("account already exists") from error
            return account.id

    def verify_password(self, email: str, password: str) -> UUID:
        try:
            normalized = _normalize_email(email)
        except ValueError as error:
            raise InvalidCredentials("invalid credentials") from error
        with self._session_factory() as session:
            account = session.scalar(select(UserAccount).where(UserAccount.email == normalized))
            stored_hash = account.password_hash if account is not None else _DUMMY_HASH
            verified = _HASHER.verify(password, stored_hash)
            if account is None or not account.is_active or not verified:
                raise InvalidCredentials("invalid credentials")
            return account.id

    def resolve(self, user_id: UUID) -> Principal:
        with self._session_factory() as session:
            account = session.get(UserAccount, user_id)
            if account is None or not account.is_active:
                raise InvalidCredentials("invalid credentials")
            memberships = session.scalars(
                select(WorkspaceMember).where(WorkspaceMember.user_id == user_id)
            ).all()
            grants = session.execute(
                select(KnowledgeBase.id, KnowledgeBase.workspace_id)
                .join(KnowledgeBaseGrant, KnowledgeBaseGrant.knowledge_base_id == KnowledgeBase.id)
                .where(KnowledgeBaseGrant.user_id == user_id)
            ).all()
            return Principal(
                user_id=account.id,
                memberships=tuple(
                    WorkspaceMembership(
                        workspace_id=item.workspace_id,
                        role=item.role,
                        knowledge_base_ids=tuple(
                            knowledge_base_id
                            for knowledge_base_id, workspace_id in grants
                            if workspace_id == item.workspace_id
                        ),
                    )
                    for item in memberships
                ),
            )

    def create_workspace(self, name: str) -> UUID:
        normalized = name.strip()
        if not 2 <= len(normalized) <= 120:
            raise ValueError("workspace name must contain 2 to 120 characters")
        workspace = Workspace(name=normalized)
        with self._session_factory() as session:
            session.add(workspace)
            try:
                session.commit()
            except IntegrityError as error:
                session.rollback()
                raise ValueError("workspace already exists") from error
            return workspace.id

    def user_id_for_email(self, email: str) -> UUID:
        normalized = _normalize_email(email)
        with self._session_factory() as session:
            account = session.scalar(select(UserAccount).where(UserAccount.email == normalized))
            if account is None:
                raise ValueError("user does not exist")
            return account.id

    def assign_role(self, user_id: UUID, workspace_id: UUID, role: Role) -> None:
        with self._session_factory() as session:
            if session.get(UserAccount, user_id) is None or session.get(Workspace, workspace_id) is None:
                raise ValueError("user or workspace does not exist")
            membership = session.get(WorkspaceMember, (user_id, workspace_id))
            if membership is None:
                session.add(WorkspaceMember(user_id=user_id, workspace_id=workspace_id, role=role))
            else:
                membership.role = role
            session.commit()

    def create_knowledge_base(self, workspace_id: UUID, name: str) -> UUID:
        normalized = name.strip()
        if not 2 <= len(normalized) <= 120:
            raise ValueError("knowledge base name must contain 2 to 120 characters")
        with self._session_factory() as session:
            if session.get(Workspace, workspace_id) is None:
                raise ValueError("workspace does not exist")
            base = KnowledgeBase(workspace_id=workspace_id, name=normalized)
            session.add(base)
            try:
                session.commit()
            except IntegrityError as error:
                session.rollback()
                raise ValueError("knowledge base already exists") from error
            return base.id

    def grant_knowledge_base(self, user_id: UUID, knowledge_base_id: UUID) -> None:
        with self._session_factory() as session:
            base = session.get(KnowledgeBase, knowledge_base_id)
            if base is None or session.get(WorkspaceMember, (user_id, base.workspace_id)) is None:
                raise ValueError("user is not a member of the knowledge base workspace")
            if session.get(KnowledgeBaseGrant, (user_id, knowledge_base_id)) is None:
                session.add(KnowledgeBaseGrant(user_id=user_id, knowledge_base_id=knowledge_base_id))
                session.commit()

    def link_document(self, knowledge_base_id: UUID, document_id: int) -> None:
        with self._session_factory() as session:
            if session.get(KnowledgeBase, knowledge_base_id) is None or session.get(Document, document_id) is None:
                raise ValueError("knowledge base or document does not exist")
            if session.get(KnowledgeBaseDocument, (knowledge_base_id, document_id)) is None:
                session.add(KnowledgeBaseDocument(
                    knowledge_base_id=knowledge_base_id, document_id=document_id
                ))
                session.commit()


class TokenCodec:
    def __init__(self, secret: str, *, ttl_minutes: int = 30) -> None:
        if len(secret.encode("utf-8")) < 32:
            raise ValueError("token signing secret must be at least 32 bytes")
        if not 1 <= ttl_minutes <= 120:
            raise ValueError("token lifetime must be between 1 and 120 minutes")
        self._secret = secret
        self.ttl_minutes = ttl_minutes

    def issue(self, user_id: UUID, *, now: datetime | None = None) -> str:
        issued = now or datetime.now(UTC)
        return jwt.encode(
            {
                "sub": str(user_id),
                "iss": _ISSUER,
                "aud": _AUDIENCE,
                "iat": issued,
                "nbf": issued,
                "exp": issued + timedelta(minutes=self.ttl_minutes),
                "jti": str(uuid4()),
            },
            self._secret,
            algorithm="HS256",
        )

    def verify(self, token: str) -> UUID:
        try:
            claims = jwt.decode(
                token,
                self._secret,
                algorithms=["HS256"],
                issuer=_ISSUER,
                audience=_AUDIENCE,
                options={"require": ["sub", "iss", "aud", "iat", "nbf", "exp", "jti"]},
            )
            return UUID(claims["sub"])
        except (jwt.InvalidTokenError, ValueError, TypeError, KeyError) as error:
            raise InvalidCredentials("invalid credentials") from error


class AuthenticationService:
    def __init__(self, identity: IdentityService, tokens: TokenCodec) -> None:
        self.identity = identity
        self.tokens = tokens

    def login(self, email: str, password: str) -> str:
        return self.tokens.issue(self.identity.verify_password(email, password))

    def resolve(self, token: str) -> Principal:
        return self.identity.resolve(self.tokens.verify(token))
