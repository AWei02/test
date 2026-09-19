# -*- coding: utf-8 -*-
"""Schedule router — CRUD endpoints for scheduled agent tasks."""
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status

from ..access import ResourceKind
from .._manager import SchedulerManager
from ..deps import (
    get_current_user_id,
    get_resource_access_service,
    get_scheduler_manager,
    get_storage,
)
from ._schema import (
    CreateScheduleRequest,
    CreateScheduleResponse,
    ListSchedulesResponse,
    ScheduleSessionsResponse,
    UpdateScheduleRequest,
)
from .._service import ResourceAccessService
from ..storage import (
    StorageBase,
    ScheduleData,
    ScheduleRecord,
    ScheduleSource,
)

schedule_router = APIRouter(
    prefix="/schedule",
    tags=["schedule"],
    responses={404: {"description": "Not found"}},
)


@schedule_router.get(
    "/",
    response_model=ListSchedulesResponse,
    summary="List all schedules",
)
async def list_schedules(
    user_id: str = Depends(get_current_user_id),
    storage: StorageBase = Depends(get_storage),
) -> ListSchedulesResponse:
    """List all schedules owned by the current user.

    Args:
        user_id (`str`): Authenticated user ID.
        storage (`StorageBase`): Storage instance.

    Returns:
        `ListSchedulesResponse`:
            Paginated list of schedule records.
    """
    schedules = await storage.list_schedules(user_id)
    return ListSchedulesResponse(schedules=schedules, total=len(schedules))


@schedule_router.post(
    "/",
    response_model=CreateScheduleResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new schedule",
)
async def create_schedule(
    body: CreateScheduleRequest,
    user_id: str = Depends(get_current_user_id),
    storage: StorageBase = Depends(get_storage),
    access: ResourceAccessService = Depends(get_resource_access_service),
    scheduler: SchedulerManager = Depends(get_scheduler_manager),
) -> CreateScheduleResponse:
    """Create a new schedule and hand it to the scheduler.

    The referenced agent may be either the viewer's own or one shared
    to them through :class:`ResourceAccessPolicyBase`; the schedule
    record itself is always owned by the caller.

    Args:
        body (`CreateScheduleRequest`): Schedule configuration.
        user_id (`str`): Authenticated user ID.
        storage (`StorageBase`): Storage instance.
        access (`ResourceAccessService`): Access service.
        scheduler (`SchedulerManager`): Scheduler manager.

    Returns:
        `CreateScheduleResponse`:
            The ID of the newly created schedule.

    Raises:
        `HTTPException`: 404 if the specified agent or the credential
            referenced by ``chat_model_config`` is not visible to the
            caller; 422 if the cron expression, timezone or activation
            window is invalid.
    """
    # Visibility checks — raise 404 when neither owned nor shared. The
    # schedule fires under the owner's user_id, so re-validating the
    # credential here surfaces the error at creation time rather than
    # silently at the first (possibly much later) scheduled run.
    await access.resolve_agent(user_id, body.agent_id)
    await access.get_resource(
        user_id,
        ResourceKind.CREDENTIAL,
        body.chat_model_config.credential_id,
    )
    if body.project_id:
        from project_files import accessible

        project = accessible(user_id, body.project_id)
        if project.get("agent_id") != body.agent_id:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="The selected project belongs to a different agent.",
            )

    record = ScheduleRecord(
        user_id=user_id,
        agent_id=body.agent_id,
        data=ScheduleData(
            name=body.name,
            description=body.description,
            cron_expression=body.cron_expression,
            timezone=body.timezone,
            enabled=body.enabled,
            ended_at=body.ended_at,
            project_id=body.project_id,
            stateful=body.stateful,
            permission_mode=body.permission_mode,
            chat_model_config=body.chat_model_config,
            source=ScheduleSource.USER,
            started_at=datetime.now(),
        ),
    )

    try:
        scheduler.validate_schedule(record)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc

    await storage.upsert_schedule(user_id, record)
    await scheduler.notify_changed(record.id)

    return CreateScheduleResponse(schedule_id=record.id)


@schedule_router.patch(
    "/{schedule_id}",
    response_model=ScheduleRecord,
    summary="Update a schedule",
)
async def update_schedule(
    schedule_id: str,
    body: UpdateScheduleRequest,
    user_id: str = Depends(get_current_user_id),
    storage: StorageBase = Depends(get_storage),
    scheduler: SchedulerManager = Depends(get_scheduler_manager),
) -> ScheduleRecord:
    """Partially update a schedule.

    Fields omitted from the request body keep their current values.
    Changing ``cron_expression`` or ``timezone`` reschedules the job, and
    ``enable=False`` stops it firing without deleting the record — both
    take effect once the timer-owning node reconciles.

    Args:
        schedule_id (`str`): ID of the schedule to update.
        body (`UpdateScheduleRequest`): Fields to update.
        user_id (`str`): Authenticated user ID.
        storage (`StorageBase`): Storage instance.
        scheduler (`SchedulerManager`): Scheduler manager.

    Returns:
        `ScheduleRecord`:
            The updated schedule record.

    Raises:
        `HTTPException`: 404 if the schedule does not exist; 422 if the
            update leaves an invalid cron expression, timezone or
            activation window.
    """
    existing = await storage.get_schedule(user_id, schedule_id)
    if existing is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Schedule '{schedule_id}' not found.",
        )

    # `ended_at: null` is meaningful: it clears a previously configured
    # end date. Preserve explicitly supplied nulls while ignoring omitted
    # fields in ordinary partial updates.
    updates = body.model_dump(exclude_unset=True)
    if "project_id" in updates and updates["project_id"]:
        from project_files import accessible

        project = accessible(user_id, updates["project_id"])
        if project.get("agent_id") != existing.agent_id:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="The selected project belongs to a different agent.",
            )
    if "project_id" in updates and updates["project_id"] != existing.data.project_id:
        # Existing sessions keep their current binding. New stateful runs use
        # a distinct session id and new runs bind the selected workspace.
        updates["workspace_version"] = existing.data.workspace_version + 1
    updated_data = existing.data.model_copy(update=updates)
    updated_record = existing.model_copy(
        update={"data": updated_data, "updated_at": datetime.now()},
    )

    try:
        scheduler.validate_schedule(updated_record)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc

    await storage.upsert_schedule(user_id, updated_record)
    await scheduler.notify_changed(schedule_id)

    return updated_record


@schedule_router.delete(
    "/{schedule_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a schedule",
)
async def delete_schedule(
    schedule_id: str,
    user_id: str = Depends(get_current_user_id),
    storage: StorageBase = Depends(get_storage),
    scheduler: SchedulerManager = Depends(get_scheduler_manager),
) -> None:
    """Permanently delete a schedule but retain its chat history.

    Existing schedule-created sessions remain visible in normal chat
    history; only the schedule record and its future triggers are removed.

    Args:
        schedule_id (`str`): ID of the schedule to delete.
        user_id (`str`): Authenticated user ID.
        scheduler (`SchedulerManager`): Scheduler manager.

    Raises:
        `HTTPException`: 404 if the schedule does not exist.
    """
    deleted = await storage.delete_schedule(
        user_id, schedule_id, preserve_sessions=True,
    )
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Schedule '{schedule_id}' not found.",
        )
    await scheduler.notify_changed(schedule_id)


@schedule_router.post(
    "/{schedule_id}/run",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Run a schedule immediately",
)
async def run_schedule_now(
    schedule_id: str,
    user_id: str = Depends(get_current_user_id),
    storage: StorageBase = Depends(get_storage),
    scheduler: SchedulerManager = Depends(get_scheduler_manager),
) -> dict[str, bool]:
    """Queue one immediate execution without changing the cron schedule."""
    record = await storage.get_schedule(user_id, schedule_id)
    if record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Schedule not found.")
    if not record.data.enabled:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Disabled schedules cannot run immediately.")
    await scheduler.run_now(record)
    return {"ok": True}


@schedule_router.get(
    "/{schedule_id}/sessions",
    response_model=ScheduleSessionsResponse,
    summary="List execution sessions for a schedule",
)
async def list_schedule_sessions(
    schedule_id: str,
    user_id: str = Depends(get_current_user_id),
    storage: StorageBase = Depends(get_storage),
) -> ScheduleSessionsResponse:
    """Return all sessions triggered by a given schedule.

    Args:
        schedule_id (`str`): ID of the schedule.
        user_id (`str`): Authenticated user ID.
        storage (`StorageBase`): Storage instance.

    Returns:
        `ScheduleSessionsResponse`:
            List of execution sessions ordered by creation time (newest first).

    Raises:
        `HTTPException`: 404 if the schedule does not exist.
    """
    existing = await storage.get_schedule(user_id, schedule_id)
    if existing is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Schedule '{schedule_id}' not found.",
        )

    sessions = await storage.list_sessions_by_schedule(user_id, schedule_id)
    return ScheduleSessionsResponse(sessions=sessions, total=len(sessions))
