from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_current_user, get_db
from app.models import User
from app.schemas import UserResponse


router = APIRouter(prefix="/users", tags=["users"])


@router.get("", response_model=list[UserResponse])
async def list_users(
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
):
    users = (
        await session.scalars(
            select(User)
            .where(
                User.id != current_user.id,
                User.is_active.is_(True),
                User.is_placeholder.is_(False),
            )
            .order_by(User.login)
        )
    ).all()
    return users
