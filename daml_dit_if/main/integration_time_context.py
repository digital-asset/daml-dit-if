import asyncio

from dataclasses import dataclass
from typing import List, Tuple, Optional, Callable, Sequence

from dazl import AIOPartyClient, Command

from .log import LOG

from ..api import IntegrationTimeEvents

from .common import \
    InvocationStatus, \
    without_return_value, \
    as_handler_invocation


from .integration_deferral_queue import \
    IntegrationDeferralQueue


@dataclass
class TimerEventStatus(InvocationStatus):
    label: 'Optional[str]'


@dataclass
class IntegrationTimeStatus:
    timers: 'Sequence[TimerEventStatus]'


IntegrationTimerHandler = Callable[[], None]


class IntegrationTimeContext(IntegrationTimeEvents):

    def __init__(self, queue: 'IntegrationDeferralQueue', client: 'AIOPartyClient'):
        self.queue = queue
        self.client = client
        self.intervals = []  # type: List[Tuple[int, IntegrationTimerHandler, TimerEventStatus]]

    def periodic_interval(self, seconds, label: 'Optional[str]' = None):
        def decorator(fn: 'IntegrationTimerHandler'):
            status = TimerEventStatus(
                index=len(self.intervals),
                label=label,
                command_count=0,
                use_count=0,
                error_count=0,
                error_message=None)

            wrapped = without_return_value(
                as_handler_invocation(
                    self.client, status, fn))

            self.intervals.append((seconds, wrapped, status))

            return wrapped
        return decorator

    async def wait_loop(self, seconds, fn):
        LOG.debug('Entering timer wait loop for %r second interval (fn: %r)',
                 seconds, fn)

        try:
            while True:
                LOG.debug('Wait loop waiting %r seconds...', seconds)
                await asyncio.sleep(seconds)
                await self.queue.put(fn)
        except:  # noqa: E722
            LOG.exception('Unexpected error in wait loop (%r, %r).', seconds, fn)

    async def start(self):
        asyncio.gather(*[
            asyncio.create_task(self.wait_loop(seconds, fn))
            for (seconds, fn, status)
            in self.intervals])

    def get_status(self) -> 'IntegrationTimeStatus':
        return IntegrationTimeStatus(
            timers=[status for (_, _, status) in self.intervals])
