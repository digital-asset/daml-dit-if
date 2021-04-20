import asyncio

from dataclasses import dataclass

from typing import Callable

from .log import LOG

from .common import InvocationStatus

DeferredAction = Callable[[], None]


@dataclass
class IntegrationQueueAction:
    action: 'DeferredAction'
    status: 'InvocationStatus'


class IntegrationDeferralQueue:

    def __init__(self):
        self.queue = \
            asyncio.Queue(maxsize=10)  # type: asyncio.Queue[IntegrationQueueAction]

    async def put(self, action: DeferredAction, status: InvocationStatus):
        await self.queue.put(IntegrationQueueAction(
            action=action,
            status=status))

    def qsize(self):
        return self.queue.qsize()

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
