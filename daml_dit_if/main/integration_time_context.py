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


@dataclass
class TimerEventStatus(InvocationStatus):
    label: 'Optional[str]'


@dataclass
class IntegrationTimeStatus:
    timers: 'Sequence[TimerEventStatus]'


IntegrationTimerHandler = Callable[[], Sequence[Command]]


class IntegrationTimeContext(IntegrationTimeEvents):

    def __init__(self, client: 'AIOPartyClient'):
        self.queue = \
            asyncio.Queue(maxsize=1)  # type: asyncio.Queue[IntegrationTimerHandler]
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

    async def worker(self):
        LOG.debug('Time context worker starting.')

        while True:
            LOG.debug('Waiting for time event.')

            try:
                fn = await self.queue.get()
                LOG.info('Received time event.')
                commands = await fn()

                if commands:
                    LOG.info('Submitting time event ledger commands: %r', commands)
                    await self.client.submit(commands)

            except:  # noqa: E722
                LOG.exception('Uncaught error in time context worker loop')

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
        worker_task = asyncio.create_task(self.worker())

        wait_tasks = [asyncio.create_task(self.wait_loop(seconds, fn))
                      for (seconds, fn, status)
                      in self.intervals]

        asyncio.gather(*[worker_task, *wait_tasks])

    def get_status(self) -> 'IntegrationTimeStatus':
        return IntegrationTimeStatus(
            timers=[status for (_, _, status) in self.intervals])
