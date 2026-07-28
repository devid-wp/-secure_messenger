from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import and_, exists, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_current_user, get_db
from app.models import User, UserBlock
from app.schemas import UserResponse


router = APIRouter(prefix="/users", tags=["users"])


def _block_exists(current_user_id: int):
    return exists(
        select(UserBlock.blocker_id).where(
            or_(
                and_(
                    UserBlock.blocker_id == current_user_id,
                    UserBlock.blocked_id == User.id,
                ),
                and_(
                    UserBlock.blocker_id == User.id,
                    UserBlock.blocked_id == current_user_id,
                ),
            )
        )
    )


@router.get("/search", response_model=list[UserResponse])
async def search_users(
    q: str = Query(min_length=2, max_length=64),
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
):
    normalized_query = q.strip()
    if len(normalized_query) < 2:
        return []
    escaped_query = (
        normalized_query.replace("\\", "\\\\")
        .replace("%", "\\%")
        .replace("_", "\\_")
    )
    return list(
        await session.scalars(
            select(User)
            .where(
                User.id != current_user.id,
                User.is_active.is_(True),
                User.is_placeholder.is_(False),
                ~_block_exists(current_user.id),
                User.login.ilike(f"%{escaped_query}%", escape="\\"),
            )
            .order_by(User.login.asc(), User.id.asc())
            .limit(20)
        )
    )


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
                ~_block_exists(current_user.id),
            )
            .order_by(User.login)
        )
    ).all()
    return users


@router.get("/blocks", response_model=list[UserResponse])
async def list_blocked_users(
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
):
    return list(
        await session.scalars(
            select(User)
            .join(UserBlock, UserBlock.blocked_id == User.id)
            .where(UserBlock.blocker_id == current_user.id)
            .order_by(User.login)
        )
    )


@router.post("/{login}/block", status_code=204)
async def block_user(
    login: str,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
):
    other = await session.scalar(
        select(User).where(
            User.login == login,
            User.is_active.is_(True),
            User.is_placeholder.is_(False),
        )
    )
    if other is None:
        raise HTTPException(status_code=404, detail="User not found")
    if other.id == current_user.id:
        raise HTTPException(status_code=400, detail="Cannot block yourself")
    if await session.get(UserBlock, (current_user.id, other.id)) is None:
        session.add(UserBlock(blocker_id=current_user.id, blocked_id=other.id))
        await session.commit()


@router.delete("/{login}/block", status_code=204)
async def unblock_user(
    login: str,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
):
    other = await session.scalar(select(User).where(User.login == login))
    if other is None:
        raise HTTPException(status_code=404, detail="User not found")
    block = await session.get(UserBlock, (current_user.id, other.id))
    if block is not None:
        await session.delete(block)
        await session.commit()
