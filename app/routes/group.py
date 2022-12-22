# FastAPI
from fastapi import APIRouter, Body, Depends, HTTPException, status
from fastapi.encoders import jsonable_encoder
from fastapi.responses import Response, JSONResponse
# from fastapi.logger import logger
# pydantic
from pydantic import EmailStr
# Types
from typing import Any, Dict, List
# Beanie
# from beanie import PydanticObjectId
# Local imports
from app.mongo_db import mainDB as Database
from app.models.group import Group
from app.models.user import User
from app.models.user_manager import current_active_user, fastapi_users
from app.exceptions import group as group_exceptions
from app.exceptions import user as user_exceptions
from app.schemas.user import UserReadBasicInfo, UserID
from app.schemas.group import (GroupCreateIn, GroupCreateOut, GroupID,
                               GroupUpdateIn, GroupUpdateOut,
                               GroupAddMembers, GroupReadMembers, GroupMember,
                               GroupReadSimple, GroupReadFull, GroupList)


# APIRouter creates path operations for user module
router = APIRouter(
    prefix="/groups",
    # tags=["Groups"],
    responses={404: {"description": "Not found"}},
)


# TODO: Add api callbacks for group creation, deletion, and modification
# TODO: Add api callbacks for group membership management: add, remove,
# change role


current_superuser = fastapi_users.current_user(active=True, superuser=True)


# List all groups can be used later for search queries
# response_model=List[Group]
@router.get("/", response_description="List all groups", response_model=GroupList, tags=["Groups"])
async def list_groups(user: User = Depends(current_active_user),
                      group_name: str | None = None,
                      member_data: UserID | EmailStr | None = None) -> GroupList:
    query: List[Dict[str, Any]] = []
    if group_name:
        query.append({"name": group_name})
    if member_data:
        member = None
        if member_data.__class__ is EmailStr:
            member = await User.find_one({"email": member_data})
        elif member_data.__class__ is UserID:
            member = await User.find_one({"_id": member_data})

        if member:
            member_id = member.id
        else:
            raise user_exceptions.UserNotFound(member_data)

        query.append({"owner": member_id})
        # TODO: Add member search for other roles
    # NOTE: Users can only see groups they are a member of
    # NOTE: Superusers can see all groups

    if not user.is_superuser:
        query.append({"members": user.id})

    if query:
        search = {"$and": query} if len(query) > 1 else query[0]
        all_groups = await Group.find(search).to_list()
    else:
        all_groups = await Group.find_all().to_list()

    search_result = []

    # Convert Group to GroupReadSimple
    for group in all_groups:
        # Check role of user
        if group.owner == user.id:
            role = "owner"
        elif user.id in group.admins:
            role = "admin"
        else:
            role = "member"

        search_result.append(GroupReadSimple(name=group.name, role=role))

    # return JSONResponse(status_code=status.HTTP_200_OK,
    # content=jsonable_encoder({"groups": search_result}))
    return GroupList(groups=search_result)

    # return all_groups


# Create a new group with user as the owner
@router.post("/",
             response_description="Create new group",
             status_code=status.HTTP_201_CREATED,
             response_model=GroupCreateOut,
             tags=["Groups"])
async def create_group(group: GroupCreateIn = Body(...),
                       user: User = Depends(current_active_user)
                       ) -> GroupCreateOut | JSONResponse:
    # Todo: Check if group name is unique
    # if (await Group.find({"name": name})):
    #     return 400

    # NOTE: The update method is not working for some reason
    # await User.update({"_id": user.id}, {"$push": {"groups": new_group.id}})

    # HACK: Find, update, and save user manually instead
    creator = await User.get(user.id)
    if creator:
        # Add group to user's groups list
        new_group = await Group(name=group.name, description=group.description,
                                owner=user.id, admins=[user.id], members=[user.id]).insert()
        if not new_group:
            print("Group not created")
        #     raise group_exceptions.GroupCreationError(group.name)
        creator.groups.append(new_group.id)
        await creator.save()
    else:
        raise user_exceptions.UserNotFound(user.id)
    created_group = await Group.get(new_group.id)
    if created_group:
        return GroupCreateOut(id=created_group.id, name=created_group.name)
    else:
        return JSONResponse(status_code=status.HTTP_404_NOT_FOUND,
                            content=jsonable_encoder({"error": "Group not found"}))


# Get group by id
@router.get("/{group_id}", response_description="Get group by id",
            response_model=GroupReadFull, tags=["Groups"])
async def get_group(group_id: GroupID,
                    user: User = Depends(current_active_user)):
    # find group by id
    group = await Group.get(group_id)
    if group:
        if group.owner == user.id or user.id in group.admins or user.id in group.members:
            owner = await User.get(group.owner)
            if owner:
                email = EmailStr(owner.email)
                name = "{} {}".format(owner.first_name, owner.last_name)
                return GroupReadFull(
                    name=group.name,
                    description=group.description,
                    owner_name=name,
                    owner_email=email)
        else:
            raise group_exceptions.UserNotAuthorized(user, group, "access in")
    else:
        raise group_exceptions.GroupNotFound(group_id)

    return JSONResponse(status_code=status.HTTP_404_NOT_FOUND,
                        content=jsonable_encoder({"error": "Group not found"}))

# Delete a group


@router.delete("/{group_id}",
               response_description="Delete group",
               tags=["Groups"])
async def delete_group(group_id: GroupID, user: User = Depends(current_active_user)) -> Response:
    # Check if user is owner of group

    group = await Group.get(group_id)

    if group is None:
        raise group_exceptions.GroupNotFound(group_id)

    if group.owner != user.id:
        raise group_exceptions.UserNotAuthorized(user, group)
    # Remove group from user's groups list
    user.groups.remove(group_id)
    # Remove group from database
    await group.delete()
    return Response(status_code=status.HTTP_204_NO_CONTENT)

# Update a group


@router.put("/{id}", response_description="Update a group",
            response_class=GroupUpdateOut, tags=["Groups"])
async def update_group(id: str, group: GroupUpdateIn = Body(...)) -> JSONResponse:
    new_group = {k: v for k, v in group.dict().items() if v is not None}

    if len(new_group) >= 1:
        update_result = await Database["groups"].update_one({"_id": id}, {"$set": group})

        if update_result.modified_count == 1:
            if (
                updated_group := await Database["groups"].find_one({"_id": id})
            ) is not None:
                return JSONResponse(updated_group)

    if (existing_group := await Database["groups"].find_one({"_id": id})) is not None:
        return JSONResponse(existing_group)

    raise HTTPException(status_code=404, detail=f"group {id} not found")


# Get the owner of a group
@router.get("/{group_id}/owner",
            response_description="Get group owner",
            response_model=UserReadBasicInfo,
            tags=["Members"])
async def get_group_owner(group_id: GroupID,
                          user: User = Depends(current_active_user)) -> UserReadBasicInfo | None:
    group = await Group.get(group_id)
    if group:
        if (user.id not in group.members) and (not user.is_superuser):
            raise group_exceptions.UserNotAuthorized(user, group, "access in")

        owner = await User.get(group.owner)
        if not owner:
            # This should never happen
            raise user_exceptions.UserNotFound(group.owner)
        return UserReadBasicInfo(
            first_name=owner.first_name,
            last_name=owner.last_name,
            email=EmailStr(
                owner.email))
    else:
        raise group_exceptions.GroupNotFound(group_id)


# Get group admins
@router.get("/{group_id}/admins/",
            response_description="Get list of group administrators",
            response_model=GroupReadMembers,
            tags=["Members"])
async def get_group_admins(group_id: GroupID, user: User = Depends(current_active_user)) -> GroupReadMembers:
    group = await Group.get(group_id)
    users = []
    admins = []
    if group:
        if user.id not in group.members and (not user.is_superuser):
            raise group_exceptions.UserNotAuthorized(user, group, "access in")
        users = await User.find({"_id": {"$in": group.admins}}).to_list()
    else:
        raise group_exceptions.GroupNotFound(group_id)
    # Return list of admins or empty list
    for user in users:
        if user.id != group.owner:
            admins.append(
                GroupMember(
                    email=EmailStr(
                        user.email),
                    first_name=user.first_name,
                    last_name=user.last_name,
                    role="admin"))

    return GroupReadMembers(members=admins)

# Get only members with user privileges


@router.get("/{group_id}/users",
            response_description="Get group members",
            response_model=GroupReadMembers,
            tags=["Members"])
async def get_group_users(group_id: GroupID, user: User = Depends(current_active_user)) -> GroupReadMembers:
    group = await Group.get(group_id)
    users = []
    members = []
    if group:
        if user.id not in group.members and (not user.is_superuser):
            raise group_exceptions.UserNotAuthorized(user, group, "access in")
        filter = [_user for _user in group.members if _user not in group.admins]
        users = await User.find({"_id": {"$in": filter}}).to_list()
    else:
        raise group_exceptions.GroupNotFound(group_id)

    for user in users:
        members.append(
            GroupMember(
                email=EmailStr(
                    user.email),
                first_name=user.first_name,
                last_name=user.last_name,
                role="user"))

    return GroupReadMembers(members=members)

# Get all members of a group


@router.get("/{group_id}/members",
            response_description="Get group members",
            response_model=GroupReadMembers,
            tags=["Members"])
async def get_group_members(group_id: GroupID, user: User = Depends(current_active_user)) -> GroupReadMembers:
    group = await Group.get(group_id)
    users = []
    members = []

    if group:
        if user.id not in group.members and (not user.is_superuser):
            raise group_exceptions.UserNotAuthorized(user, group, "access in")
        users = await User.find({"_id": {"$in": group.members}}).to_list()
    else:
        raise group_exceptions.GroupNotFound(group_id)

    for user in users:
        if user.id == group.owner:
            role = "owner"
        elif user.id in group.admins:
            role = "admin"
        else:
            role = "user"
        members.append(
            GroupMember(
                email=EmailStr(
                    user.email),
                first_name=user.first_name,
                last_name=user.last_name,
                role=role))

    return GroupReadMembers(members=members)


# Add user or multiple users to a group
@router.post("/{group_id}/members",
             response_description="Add user(s) to a group",
             tags=["Members"])
async def add_user_to_group(group_id: GroupID, InputModel: GroupAddMembers,
                            user: User = Depends(current_active_user)) -> JSONResponse:
    """
    Add member(s) to a group. The front-end application must do validation to ensure
    that the user exists in the database and is not already a member of the group.
    This function also does the same validation checks; However, no users will be added
    if any error occurs.

    The function takes a list of JSON objects(Models) with email of the new user and the
    role(privilege level) in the group.

    Possible outcomes:
     - The function will return a list of emails of users that were not found in the database.
     - The function will return an error if a user is already a member of the group
     - The function will successfully add the users to the group

    """

    # TODO: Check if only one email is provided

    # Check if user is an admin of the group
    if (group := await Group.get(group_id)) is not None:
        if user.id not in group.admins:
            raise group_exceptions.UserNotAuthorized(user, group)
    else:
        raise group_exceptions.GroupNotFound(group_id)

    # Copy emails to a dictionary
    email_dict = {}
    for member in InputModel.members:
        email_dict[str(member.email)] = member.role

    # Get the users from the database
    new_members = {}
    new_admins = []
    email_list = list(email_dict.keys())
    async for user in User.find({"email": {"$in": email_list}}):
        if user:
            new_members[user.id] = user
            if email_dict[user.email] == "admin":
                new_admins.append(user.id)
            email_list.remove(user.email)
        else:
            raise user_exceptions.UserNotFound(user.email)

    # Check if all emails are valid
    if email_list:
        raise HTTPException(status_code=404,
                            detail=f"Users with emails {email_list} not found")

    # Check if users are already in the group
    for _, (i, new_user) in enumerate(new_members.items()):
        if new_user.id in group.members:
            raise group_exceptions.UserAlreadyExists(new_user, group)

    await group.update({"$push": {"members": {"$each": list(new_members.keys())}, "admins": {"$each": new_admins}}})
    await User.find({"_id": {"$in": list(new_members.keys())}}).update({"$push": {"groups": group_id}})
    return JSONResponse(status_code=status.HTTP_201_CREATED, content={
                        "message": "Users have been added to group"})


# Remove a member from a group
@router.delete("/{group_id}/member/{email}",
               response_description="Remove a member from a group",
               tags=["Members"])
async def remove_user(group_id: GroupID, email: EmailStr, user: User = Depends(current_active_user)) -> Response:
    # Check if user is an admin of the group
    if (group := await Group.get(group_id)) is not None:
        # Check if user is an admin of the group
        if user.id not in group.admins:
            raise group_exceptions.UserNotAuthorized(
                user, group, "remove users from")
        # Prohibit the user from removing themselves
        # TODO: Check if this is necessary, because the should be able to leave the group
        if user.email == email:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="You cannot remove yourself from the group")
        # Prohibit the user from removing the owner of the group
        if group.owner == user.id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="You cannot remove the owner of the group")
        # Check if user exists
        if (deleted_user := await User.find_one({"email": email})) is not None:
            # Check if user is in the group
            if deleted_user.id not in group.members:
                raise group_exceptions.UserNotInGroup(deleted_user, group)
            else:
                # Remove user from group and group from user
                await User.update({"_id": deleted_user.id}, {"$pull": {"groups": group_id}})
                await Group.update({"_id": group_id},
                                   {"$pull": {"members": deleted_user.id, "admins": deleted_user.id}})

                # Check that the user has been removed from the group
                if (group := await Group.get(group_id)) is not None:
                    if deleted_user.id in group.members or deleted_user.id in group.admins:
                        raise HTTPException(
                            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                            detail="User was not removed from the group")
                return Response(status_code=status.HTTP_204_NO_CONTENT)
        else:
            raise user_exceptions.UserNotFound(email)
    else:
        raise group_exceptions.GroupNotFound(group_id)
