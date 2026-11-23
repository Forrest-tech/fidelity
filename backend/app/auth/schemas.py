import uuid

from fastapi_users import schemas

from .models import Role


class UserRead(schemas.BaseUser[uuid.UUID]):
    role: Role
    approval: str | None = None


class UserCreate(schemas.BaseUserCreate):
    role: Role = Role.viewer


class UserUpdate(schemas.BaseUserUpdate):
    role: Role | None = None
