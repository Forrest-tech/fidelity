from fastapi import APIRouter, Depends

from .models import User
from .schemas import UserCreate, UserRead, UserUpdate
from .users import backend, current_user, fastapi_users, require_role
from .models import Role

router = APIRouter()
router.include_router(fastapi_users.get_auth_router(backend), prefix="/auth", tags=["auth"])
# User management is admin-only.
router.include_router(
    fastapi_users.get_users_router(UserRead, UserUpdate),
    prefix="/users", tags=["users"], dependencies=[Depends(require_role())],
)
router.include_router(
    fastapi_users.get_register_router(UserRead, UserCreate),
    prefix="/users", tags=["users"], dependencies=[Depends(require_role())],
)


@router.get("/me", response_model=UserRead, tags=["auth"])
async def me(user: User = Depends(current_user)):
    return user


# ------------------------------------------------------------------ first-run setup
# While no user exists, the sign-in page offers to create the first administrator. As soon as one
# user exists these endpoints refuse, so they cannot be used to add accounts later.
from fastapi import HTTPException  # noqa: E402
from pydantic import BaseModel, EmailStr  # noqa: E402
from sqlalchemy import func, select  # noqa: E402

from ..orm import SessionLocal  # noqa: E402


class SetupIn(BaseModel):
    email: EmailStr
    password: str


async def _user_count() -> int:
    async with SessionLocal() as s:
        return (await s.execute(select(func.count()).select_from(User))).scalar_one()


@router.get("/setup", tags=["auth"])
async def setup_status():
    return {"needs_setup": await _user_count() == 0}


@router.post("/setup", status_code=201, tags=["auth"])
async def setup_first_admin(body: SetupIn):
    if await _user_count() > 0:
        raise HTTPException(status_code=409, detail="setup is already complete")
    from fastapi_users.db import SQLAlchemyUserDatabase
    from fastapi_users.exceptions import InvalidPasswordException
    from .users import UserManager
    async with SessionLocal() as s:
        mgr = UserManager(SQLAlchemyUserDatabase(s, User))
        try:
            await mgr.create(UserCreate(email=body.email, password=body.password, role=Role.admin, is_verified=True))
        except InvalidPasswordException as e:
            raise HTTPException(status_code=422, detail=str(e.reason))
    return {"created": body.email, "role": "admin"}
