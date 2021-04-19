import asyncio

from typing import Callable

from .log import LOG


DeferredAction = Callable[[], None]

class IntegrationDeferralQueue:

    def __init__(self):
        self.queue = \
            asyncio.Queue(maxsize=10)  # type: asyncio.Queue[DeferredAction]

    async def put(self, action: DeferredAction):
        await self.queue.put(action)

    def qsize(self):
        return self.queue.qsize()

    async def start(self):
        LOG.debug('Deferral worker starting.')

        while True:
            LOG.debug('Waiting for deferred action.')

            try:
                fn = await self.queue.get()
                LOG.info('Processing deferred action.')
                await fn()

            except:  # noqa: E722
                LOG.exception('Uncaught error in deferral queue worker loop')
