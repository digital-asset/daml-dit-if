import asyncio

from dataclasses import dataclass

from typing import Callable

from .log import LOG

from .common import IntegrationQueueStatus, InvocationStatus

from .config import Configuration

DeferredAction = Callable[[], None]


@dataclass
class IntegrationQueueAction:
    action: 'DeferredAction'
    status: 'InvocationStatus'


class IntegrationDeferralQueue:

    def __init__(self, config: 'Configuration'):
        self.total_events = 0
        self.skipped_events = 0
        self.queue_size = config.queue_size

        self.queue = \
            asyncio.Queue(maxsize=self.queue_size)  # type: asyncio.Queue[IntegrationQueueAction]

    async def put(self, action: DeferredAction, status: InvocationStatus):
        self.total_events = self.total_events + 1

        try:
            self.queue.put_nowait(IntegrationQueueAction(
                action=action,
                status=status))

        except asyncio.QueueFull:
            self.skipped_events = self.skipped_events + 1
            LOG.error('Work queue overrun, skipping event: %r', status)
            raise

    def get_status(self) -> 'IntegrationQueueStatus':
        return IntegrationQueueStatus(
            total_events=self.total_events,
            pending_events=self.queue.qsize(),
            skipped_events=self.skipped_events,
            queue_size=self.queue_size)

    async def start(self):
        LOG.info('Queue worker starting.')

        while True:
            LOG.debug('Waiting for queue entry.')

            try:
                entry = await self.queue.get()

                LOG.info('Processing queue entry: %r', entry.status.label)
                await entry.action()

            except:  # noqa: E722
                LOG.exception('Uncaught error in queue worker loop')
