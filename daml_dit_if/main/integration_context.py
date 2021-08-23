import asyncio
import os
import sys
import yaml

from dataclasses import dataclass
from datetime import datetime
from functools import wraps
from importlib import import_module
from types import ModuleType
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple, Type

from dazl import AIOPartyClient, Network, Command
from dazl.util.prim_types import to_boolean

from dacite import from_dict, Config

from daml_dit_api import \
    METADATA_INTEGRATION_ENABLED, \
    METADATA_COMMON_RUN_AS_PARTY, \
    METADATA_INTEGRATION_RUN_AS_PARTY, \
    METADATA_INTEGRATION_TYPE_ID, \
    IntegrationRuntimeSpec, \
    IntegrationTypeInfo


from ..api import \
    IntegrationEntryPoint, \
    IntegrationEnvironment, \
    IntegrationEvents

from .integration_deferral_queue import \
    IntegrationDeferralQueue

from .integration_queue_context import \
    IntegrationQueueContext

from .integration_time_context import \
    IntegrationTimeContext

from .integration_webhook_context import \
    IntegrationWebhookContext, WebhookRouteStatus

from .integration_ledger_context import \
    IntegrationLedgerContext, LedgerHandlerStatus

from .common import \
    IntegrationQueueStatus, \
    InvocationStatus, \
    without_return_value, \
    with_marshalling, \
    as_handler_invocation

from .config import Configuration

from .log import FAIL, LOG

from daml_dit_api import PackageMetadata


@dataclass(frozen=True)
class IntegrationStatus:
    running: bool
    start_time: datetime
    error_message: 'Optional[str]'
    error_time: 'Optional[datetime]'
    pending_events: int
    event_queue: 'IntegrationQueueStatus'
    webhooks: 'Sequence[WebhookRouteStatus]'
    ledger_events: 'Sequence[LedgerHandlerStatus]'
    timers: 'Sequence[InvocationStatus]'
    queues: 'Sequence[InvocationStatus]'


def normalize_metadata_field(field_value, field_type_info):
    LOG.debug('Normalizing %r with field_type_info: %r',
              field_value, field_type_info)

    return field_value.strip()


def normalize_metadata(metadata, integration_type):
    LOG.debug('Normalizing metadata %r for integration type: %r',
              metadata, integration_type)

    field_types = {field.id: field for field in integration_type.fields}

    return {field_id: normalize_metadata_field(field_value, field_types.get(field_id))
            for (field_id, field_value)
            in metadata.items()}


def _as_int(value: Any) -> int:
    return int(value)

def parse_qualified_symbol(symbol_text: str):

    try:
        (module_name, sym_name) = symbol_text.split(':')
    except ValueError:
        FAIL(f'Malformed symbol {symbol_text} (Must be [module_name:symbol_name])')

    module = None

    try:
        LOG.debug(f'Searching for module {module_name} in qualified symbol {symbol_text}')
        module = import_module(module_name)
    except:  # noqa
        FAIL(f'Failure importing integration package: {module_name}')

    if module is None:
        FAIL(f'Unknown module {module_name} in {symbol_text}')

    return (module, sym_name)


class IntegrationContext:

    def __init__(self,
                 network: 'Network',
                 config: 'Configuration',
                 integration_type: 'IntegrationTypeInfo',
                 type_id: str,
                 integration_spec: 'IntegrationRuntimeSpec',
                 metadata: 'PackageMetadata'):

        self.start_time = datetime.utcnow()

        self.type_id = type_id
        self.network = network
        self.run_as_party = config.run_as_party
        self.integration_type = integration_type
        self.integration_spec = integration_spec
        self.metadata = metadata

        self._party_fallback_to_metadata()

        LOG.info(f'Running as party: {self.run_as_party}')

        self.running = False
        self.error_message = None  # type: Optional[str]
        self.error_time = None  # type: Optional[datetime]

        self.queue = IntegrationDeferralQueue(config)

        self.queue_context = None  # type: Optional[IntegrationQueueContext]
        self.time_context = None  # type: Optional[IntegrationTimeContext]
        self.webhook_context = None  # type: Optional[IntegrationWebhookContext]
        self.ledger_context = None  # type: Optional[IntegrationLedgerContext]
        self.int_toplevel_coro = None

    def _party_fallback_to_metadata(self):

        if self.run_as_party:
            return

        # If the party doesn't come in through the preferred
        # environment variable path, fallback to accepting it through
        # the metadata in one of two named slots. This accomodates the
        # the way integrations historically worked through around late
        # February 2021.

        metadata = self.integration_spec.metadata

        self.run_as_party = \
            metadata.get(METADATA_COMMON_RUN_AS_PARTY) \
            or metadata.get(METADATA_INTEGRATION_RUN_AS_PARTY)

        if self.run_as_party is None:
            FAIL('DAML_LEDGER_PARTY environment variable undefined.')

    def get_integration_entrypoint(
            self,
            integration_type: 'IntegrationTypeInfo') -> 'IntegrationEntryPoint':

        (module, entry_fn_name) = parse_qualified_symbol(integration_type.entrypoint)

        return getattr(module, entry_fn_name)

    def get_integration_env_class(
            self,
            integration_type: 'IntegrationTypeInfo') -> 'Type[IntegrationEnvironment]':

        if integration_type.env_class:
            (module, env_class_name) = parse_qualified_symbol(integration_type.env_class)

            return getattr(module, env_class_name)
        else:
            return IntegrationEnvironment


    async def _load(self):
        metadata = self.integration_spec.metadata

        LOG.info('Starting ledger client for party: %r', self.run_as_party)

        client = self.network.aio_party(self.run_as_party)
        self.client = client

        env_class = self.get_integration_env_class(self.integration_type)
        entry_fn = self.get_integration_entrypoint(self.integration_type)

        metadata = normalize_metadata(metadata, self.integration_type)

        LOG.info("Starting integration with metadata: %r", metadata)

        self.queue_context = IntegrationQueueContext(self.queue, client)
        self.time_context = IntegrationTimeContext(self.queue, client)
        self.ledger_context = IntegrationLedgerContext(self.queue, client, self.metadata.daml_model)
        self.webhook_context = IntegrationWebhookContext(self.queue, client)

        events = IntegrationEvents(
            queue=self.queue_context,
            time=self.time_context,
            ledger=self.ledger_context,
            webhook=self.webhook_context)

        integration_env_data = {
            **metadata,
            'queue': self.queue_context.sink,
            'party': self.run_as_party,
            'daml_model': self.metadata.daml_model
            }

        integration_env = from_dict(
            data_class=env_class,
            data=integration_env_data,
            config=Config(type_hooks={
                bool: to_boolean,
                int: _as_int
            })
        )

        user_coro = entry_fn(integration_env, events)

        int_coros = [
            self.queue.start(),
            self.time_context.start(),
        ]

        if user_coro:
            int_coros.append(user_coro)

        self.int_toplevel_coro = asyncio.gather(*int_coros)


    async def _start(self):
        LOG.info('Starting integration...')

        await self.client.ready()
        LOG.info('...Ledger client ready, processing sweeps...')

        await self.ledger_context.process_sweeps()

        self.running = True
        LOG.info('...sweeps procesed, integration started.')


    def get_status(self) -> 'IntegrationStatus':
        queue_status = self.queue.get_status()

        return IntegrationStatus(
            running=self.running,
            start_time=self.start_time,
            error_message=self.error_message,
            error_time=self.error_time,
            pending_events=queue_status.pending_events,
            event_queue=queue_status,
            webhooks=self.webhook_context.get_status() if self.webhook_context else [],
            ledger_events=self.ledger_context.get_status() if self.ledger_context else [],
            timers=self.time_context.get_status() if self.time_context else [],
            queues=self.queue_context.get_status() if self.queue_context else [])

    async def safe_load(self):
        try:
            await self._load()
        except:  # noqa
            ex = sys.exc_info()[1]

            self.error_message = f'{repr(ex)} - {str(ex)}'
            self.error_time = datetime.utcnow()

            LOG.exception("Failure loading integration.")

    async def safe_start(self):
        try:
            await self._start()
        except:  # noqa
            ex = sys.exc_info()[1]

            self.error_message = f'{repr(ex)} - {str(ex)}'
            self.error_time = datetime.utcnow()

            LOG.exception("Failure starting integration.")

    def get_coro(self):
        return self.int_toplevel_coro
