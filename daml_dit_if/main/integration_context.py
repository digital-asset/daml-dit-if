import asyncio
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

from .integration_queue_context import \
    IntegrationQueueContext, IntegrationQueueStatus

from .integration_time_context import \
    IntegrationTimeContext, IntegrationTimeStatus

from .integration_webhook_context import \
    IntegrationWebhookContext, IntegrationWebhookStatus

from .integration_ledger_context import \
    IntegrationLedgerContext, IntegrationLedgerStatus

from .common import \
    InvocationStatus, \
    without_return_value, \
    with_marshalling, \
    as_handler_invocation

from .config import Configuration

from .log import LOG


@dataclass(frozen=True)
class IntegrationStatus:
    running: bool
    start_time: datetime
    error_message: 'Optional[str]'
    error_time: 'Optional[datetime]'
    webhooks: 'Optional[IntegrationWebhookStatus]'
    ledger: 'Optional[IntegrationLedgerStatus]'
    timers: 'Optional[IntegrationTimeStatus]'



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
        raise Exception(f'Malformed symbol {symbol_text} (Must be [module_name:symbol_name])')

    module = None

    try:
        LOG.info(f'Searching for module {module_name} in qualified symbol {symbol_text}')
        module = import_module(module_name)
    except:  # noqa
        LOG.exception(f'Failure importing integration package: {module_name}')

    if module is None:
        raise Exception(f'Unknown module {module_name} in {symbol_text}')

    return (module, sym_name)


class IntegrationContext:

    def __init__(self,
                 network: 'Network',
                 integration_type: 'IntegrationTypeInfo',
                 type_id: str,
                 integration_spec: 'IntegrationRuntimeSpec'):

        self.start_time = datetime.utcnow()

        self.type_id = type_id
        self.network = network
        self.integration_type = integration_type
        self.integration_spec = integration_spec

        self.running = False
        self.error_message = None  # type: Optional[str]
        self.error_time = None  # type: Optional[datetime]

        self.queue_context = None  # type: Optional[IntegrationQueueContext]
        self.time_context = None  # type: Optional[IntegrationTimeContext]
        self.webhook_context = None  # type: Optional[IntegrationWebhookContext]
        self.ledger_context = None  # type: Optional[IntegrationLedgerContext]
        self.int_toplevel_coro = None

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


    async def _load_and_start(self):
        metadata = self.integration_spec.metadata
        LOG.info('=== REGISTERING INTEGRATION: %r', self.integration_spec)

        run_as_party = metadata.get(METADATA_COMMON_RUN_AS_PARTY)

        if run_as_party is None:
            LOG.info("Falling back to old-style integration 'run as' party.")
            run_as_party = metadata.get(METADATA_INTEGRATION_RUN_AS_PARTY)

        if run_as_party is None:
            raise Exception("No 'run as' party specified for integration.")

        client = self.network.aio_party(run_as_party)

        env_class = self.get_integration_env_class(self.integration_type)
        entry_fn = self.get_integration_entrypoint(self.integration_type)

        metadata = normalize_metadata(metadata, self.integration_type)

        LOG.info("Starting integration with metadata: %r", metadata)

        self.queue_context = IntegrationQueueContext(client)
        self.time_context = IntegrationTimeContext(client)
        self.ledger_context = IntegrationLedgerContext(client)
        self.webhook_context = IntegrationWebhookContext(client)

        events = IntegrationEvents(
            queue=self.queue_context,
            time=self.time_context,
            ledger=self.ledger_context,
            webhook=self.webhook_context)

        integration_env_data = {
            **metadata,
            'queue': self.queue_context.sink,
            'party': run_as_party
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

        LOG.info("Waiting for ledger client to become ready")
        await client.ready()

        await self.ledger_context.process_sweeps()

        self.running = True
        LOG.info("Integration ready")

        int_coros = [
            self.queue_context.start(),
            self.time_context.start(),
            self.ledger_context.start()
        ]

        if user_coro:
            int_coros.append(user_coro)

        self.int_toplevel_coro = asyncio.gather(*int_coros)

    def get_status(self) -> 'IntegrationStatus':
        return IntegrationStatus(
            running=self.running,
            start_time=self.start_time,
            error_message=self.error_message,
            error_time=self.error_time,
            webhooks=self.webhook_context.get_status() if self.webhook_context else None,
            ledger=self.ledger_context.get_status() if self.ledger_context else None,
            timers=self.time_context.get_status() if self.time_context else None)

    async def safe_load_and_start(self):
        try:
            await self._load_and_start()
        except:  # noqa
            ex = sys.exc_info()[1]

            self.error_message = f'{repr(ex)} - {str(ex)}'
            self.error_time = datetime.utcnow()

            LOG.exception("Failure starting integration.")

    def get_coro(self):
        return self.int_toplevel_coro
