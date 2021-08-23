import sys
import collections

from asyncio import wait_for
from dataclasses import dataclass
from datetime import datetime
from functools import wraps
from typing import Optional

from dazl import AIOPartyClient

from ..api import IntegrationResponse

from .log import LOG



@dataclass(frozen=True)
class IntegrationQueueStatus:
    queue_size: int
    total_events: int
    pending_events: int
    skipped_events: int


@dataclass
class InvocationStatus:
    index: int
    label: 'Optional[str]'
    command_count: int
    use_count: int
    error_count: int
    error_message: 'Optional[str]'
    error_time: 'Optional[datetime]'

def without_return_value(fn):

    @wraps(fn)
    async def wrapped(*args, **kwargs):
        await fn(*args, **kwargs)

    return wrapped


def with_marshalling(mfn, fn):

    @wraps(fn)
    async def wrapped(arg):
        await fn(mfn(arg))

    return wrapped


def normalize_integration_response(response):
    LOG.debug('Normalizing integration response: %r', response)

    if isinstance(response, IntegrationResponse):
        LOG.debug('Integration Response passthrough')
        return response

    commands = []
    if isinstance(response, collections.Sequence):
        commands = response
    elif response:
        commands = [response]
    else:
        commands = []

    LOG.debug('Integration response with ledger commands: %r', commands)

    return IntegrationResponse(commands=commands)


def as_handler_invocation(client: 'AIOPartyClient', inv_status: 'InvocationStatus', fn):
    @wraps(fn)
    async def wrapped(*args, **kwargs):
        LOG.debug('Invoking for invocation status: %r', inv_status)
        inv_status.use_count += 1

        response = None
        try:
            response = normalize_integration_response(
                await fn(*args, **kwargs))

            if response.commands:
                LOG.debug('Submitting ledger commands (timeout=%r sec): %r',
                          response.command_timeout, response.commands)

                inv_status.command_count += len(response.commands)

                await wait_for(
                    client.submit(response.commands),
                    response.command_timeout
                )

            return response

        except Exception:
            inv_status.error_count += 1
            inv_status.error_message = repr(sys.exc_info()[1])
            inv_status.error_time = datetime.utcnow()
            LOG.exception('Error while processing: ' + inv_status.error_message)

    return wrapped
