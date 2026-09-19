"""Regression check: a UI end date becomes CronTrigger's final local day."""
import asyncio
from datetime import datetime

from agentscope.app._manager._scheduler._scheduler_manager import SchedulerManager
from agentscope.app.storage import ScheduleData, ScheduleRecord, ChatModelConfig
from agentscope.app._router._schema._schedule import CreateScheduleRequest, UpdateScheduleRequest

record = ScheduleRecord(
    user_id='schedule-test-user', agent_id='schedule-test-agent',
    data=ScheduleData(
        name='ends', cron_expression='30 10 * * *', timezone='Asia/Shanghai',
        started_at=datetime(2026, 9, 16, 10, 30),
        ended_at=datetime(2026, 9, 23, 23, 59, 59),
        chat_model_config=ChatModelConfig(type='test', model='test', credential_id='test', parameters={}),
    ),
)
trigger = SchedulerManager.validate_schedule(record)
previous = datetime(2026, 9, 23, 10, 30, tzinfo=trigger.timezone)
assert trigger.get_next_fire_time(previous, previous) is None
assert trigger.end_date.day == 23 and trigger.end_date.hour == 23
request = CreateScheduleRequest(name='api', cron_expression='30 10 * * *', timezone='Asia/Shanghai', agent_id='a', chat_model_config=ChatModelConfig(type='test', model='test', credential_id='test', parameters={}), ended_at='2026-09-23T23:59:59')
assert request.ended_at and request.ended_at.day == 23
assert UpdateScheduleRequest(ended_at=None).model_dump(exclude_unset=True) == {'ended_at': None}
record.data.enabled = False
try:
    asyncio.run(SchedulerManager.run_now(None, record))
    raise AssertionError('disabled schedule unexpectedly ran')
except ValueError as exc:
    assert 'disabled' in str(exc)
print('PASS schedule end date is retained through the scheduler and stops after the selected day')
