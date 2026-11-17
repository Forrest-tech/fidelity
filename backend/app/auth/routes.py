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
