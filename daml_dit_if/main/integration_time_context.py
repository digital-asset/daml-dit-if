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


IntegrationTimerHandler = Callable[[], None]


class IntegrationTimeContext(IntegrationTimeEvents):

    def __init__(self, queue: 'IntegrationDeferralQueue', client: 'AIOPartyClient'):
        self.queue = queue
        self.client = client
        self.intervals = []  # type: List[Tuple[int, IntegrationTimerHandler,InvocationStatus]]

    def periodic_interval(self, seconds, label: 'Optional[str]' = None):
        label_text = label or 'Periodic Interval'
        def decorator(fn: 'IntegrationTimerHandler'):
            status = InvocationStatus(
                index=len(self.intervals),
                label=f'{label} ({seconds}s)',
                command_count=0,
                use_count=0,
                error_count=0,
                error_message=None,
                error_time=None)

            wrapped = without_return_value(
                as_handler_invocation(
                    self.client, status, fn))

            self.intervals.append((seconds, wrapped, status))

            return wrapped
        return decorator

    async def wait_loop(self, seconds, fn, status):
        LOG.debug('Entering timer wait loop for %r second interval (fn: %r)',
                 seconds, fn)

        try:
            while True:
                LOG.debug('Wait loop waiting %r seconds...', seconds)
                await asyncio.sleep(seconds)

                try:
                    await self.queue.put(fn, status)

                except asyncio.QueueFull:
                    LOG.debug('Ignoring full event queue and continuing timer loop')
                    pass

        except:  # noqa: E722
            LOG.exception('Unexpected error in wait loop (%r, %r).', seconds, fn)

    async def start(self):
        asyncio.gather(*[
            asyncio.create_task(self.wait_loop(seconds, fn, status))
            for (seconds, fn, status)
            in self.intervals])

    def get_status(self) -> 'Sequence[InvocationStatus]':
        return [status for (_, _, status) in self.intervals]
