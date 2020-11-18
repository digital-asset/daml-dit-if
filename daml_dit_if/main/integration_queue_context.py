import asyncio

from dataclasses import dataclass
from typing import Any, Dict, List, Tuple, Optional, Callable, Sequence

from dazl import AIOPartyClient, Command

from .log import LOG

from ..api import IntegrationQueueEvents, IntegrationQueueSink

from .common import \
    InvocationStatus, \
    without_return_value, \
    as_handler_invocation


@dataclass
class QueueEventStatus(InvocationStatus):
    queue_name: 'str'


@dataclass
class IntegrationQueueStatus:
    queues: 'Sequence[QueueEventStatus]'


IntegrationQueueHandler = Callable[[Any], Sequence[Command]]

IntegrationQueueDict = Dict[str, Tuple[IntegrationQueueHandler, QueueEventStatus]]

class IntegrationQueueSinkImpl(IntegrationQueueSink):

    def __init__(self,
                 queues: IntegrationQueueDict):
        self.queues = queues

    async def put(self, message: 'Any', queue_name: 'str' = 'default'):

        LOG.info('Queue put: %r', message)

        if queue_name not in self.queues:
            raise Exception(f'Unknown queue: {queue_name} (valid: {list(self.queues.keys())}) ')

        (handler, _ ) = self.queues[queue_name]

        LOG.info('Queue put handler: %r', handler)

        await handler(message)

class IntegrationQueueContext(IntegrationQueueEvents):

    def __init__(self, client: 'AIOPartyClient'):
        self.queue = \
            asyncio.Queue(maxsize=1)  # type: asyncio.Queue[IntegrationQueueHandler]
        self.client = client
        self.queues = {}  # type: IntegrationQueueDict
        self.sink = IntegrationQueueSinkImpl(self.queues)

    def message(self, queue_name: 'str' = 'default'):
        def decorator(fn: 'IntegrationQueueHandler'):
            status = QueueEventStatus(
                index=len(self.queues),
                queue_name=queue_name,
                command_count=0,
                use_count=0,
                error_count=0,
                error_message=None)

            wrapped = without_return_value(
                as_handler_invocation(
                    self.client, status, fn))

            if queue_name in self.queues:
                raise Exception(f'Duplicate queue name: {queue_name}')

            LOG.info('Registering handler for queue messages: %r', queue_name)

            async def enqueue_wrapped(message):
                async def doit():
                    await wrapped(message)

                await self.queue.put(doit)

            self.queues[queue_name]=(enqueue_wrapped, status)

            return wrapped
        return decorator

    async def worker(self):
        LOG.info('Queue context worker starting...')
        while True:
            LOG.debug('...waiting for queue event.')
            fn = await self.queue.get()
            try:
                LOG.debug('...received queue event...')
                commands = await fn()

                if commands:
                    LOG.debug('Submitting ledger commands: %r', commands)
                    await self.client.submit(commands)

            except:  # noqa: E722
                LOG.exception('Uncaught error in queue context worker loop')

    async def start(self):
        worker_task = asyncio.create_task(self.worker())

        asyncio.gather(worker_task)

    def get_status(self) -> 'IntegrationQueueStatus':
        return IntegrationQueueStatus(
            queues=[status for (_, status) in self.queues.values()])
