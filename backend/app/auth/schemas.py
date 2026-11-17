import uuid

from fastapi_users import schemas

from .models import Role


class UserRead(schemas.BaseUser[uuid.UUID]):
    role: Role


class UserCreate(schemas.BaseUserCreate):
    role: Role = Role.viewer


class UserUpdate(schemas.BaseUserUpdate):
    role: Role | None = None
