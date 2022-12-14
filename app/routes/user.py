from fastapi import APIRouter, Depends
from app.models.user import User
from app.models.user_manager import current_active_user
from beanie import PydanticObjectId
from app.exceptions import user as user_exceptions
from app.utils.user import get_user_groups


#APIRouter creates path operations for user module
router = APIRouter(
    prefix="/users",
    tags=["Users"],
    responses={404: {"description": "Not found"}},
)


# List all groups that a user is a member of
@router.get("/groups", response_description="List all groups that a user is a member of")
async def list_user_groups(user_id: PydanticObjectId | None = None, user: User = Depends(current_active_user)):
    if user_id:
        search = await User.find_one({"_id": user_id})
        if search:
            user = search    
        else:
            raise user_exceptions.UserNotFound(user_id)
        
    return await get_user_groups(user)