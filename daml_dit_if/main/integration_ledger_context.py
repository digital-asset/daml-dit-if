import asyncio
from dataclasses import dataclass
from typing import Any, Callable, List, Optional, Sequence, Tuple

from dazl import AIOPartyClient
from dazl.model.core import ContractMatch
from dazl.model.reading import ContractCreateEvent
from dazl.model.writing import EventHandlerResponse

from dazl.damlast.lookup import parse_type_con_name
from dazl.damlast.util import package_ref

from daml_dit_api import \
    DamlModelInfo

from ..api import \
    ensure_package_id, \
    IntegrationLedgerEvents, \
    IntegrationLedgerContractCreateEvent, \
    IntegrationLedgerContractArchiveEvent, \
    IntegrationLedgerTransactionStartEvent, \
    IntegrationLedgerTransactionEndEvent

from .common import \
    InvocationStatus, \
    without_return_value, \
    as_handler_invocation, \
    with_marshalling

from .log import LOG

from .integration_deferral_queue import \
    IntegrationDeferralQueue


Sweep = Tuple[Any,
              Optional[ContractMatch],
              Callable[[ContractCreateEvent], EventHandlerResponse]]


PendingHandlerCall = Callable[[], None]


@dataclass
class LedgerHandlerStatus(InvocationStatus):
    template_id: 'Optional[str]'
    sweep_enabled: bool
    flow_enabled: bool


class IntegrationLedgerContext(IntegrationLedgerEvents):
    def __init__(self, queue: 'IntegrationDeferralQueue', client: 'AIOPartyClient', daml_model: 'Optional[DamlModelInfo]'):
        self.queue = queue

        self.client = client
        self.handlers = []  # type: List[LedgerHandlerStatus]
        self.sweeps = [] # type: List[Sweep]
        self.init_handlers = []  # type: List[PendingHandlerCall]
        self.ready_handlers = []  # type: List[PendingHandlerCall]
        self.daml_model = daml_model

        LOG.info('Environment DAML Model: %r', self.daml_model)

    def _notice_handler(
            self, label: str, template_id: 'Optional[str]',
            sweep_enabled: bool, flow_enabled: bool) -> 'LedgerHandlerStatus':

        handler_status = \
            LedgerHandlerStatus(
                index=len(self.handlers),
                label=label,
                template_id=template_id,
                command_count=0,
                use_count=0,
                error_count=0,
                error_message=None,
                error_time=None,
                sweep_enabled=sweep_enabled,
                flow_enabled=flow_enabled)

        self.handlers.append(handler_status)

        return handler_status

    async def process_sweeps(self):
        LOG.debug("Invoking sweep initialization handlers")

        for init_handler in self.init_handlers:
            await init_handler()

        for (template, match, wfunc) in self.sweeps:
            LOG.debug('Processing sweep for %r', template)

            for (cid, cdata) in self.client.find_active(template, match).items():
                LOG.debug('Sweep contract: %r => %r', cid, cdata)


                await wfunc(IntegrationLedgerContractCreateEvent(
                    initial=True,
                    cid=cid,
                    cdata=cdata))

        LOG.debug("Sweeps processed, invoking ready handlers")

        for ready_handler in self.ready_handlers:
            await ready_handler()

        LOG.info("Done with ready handlers and sweeps")

    def _to_int_create_event(self, dazl_event):
        return IntegrationLedgerContractCreateEvent(
            initial=False,
            cid=dazl_event.cid,
            cdata=dazl_event.cdata)

    def ledger_init(self):
        handler_status = self._notice_handler('Ledger Init', None, False, True)

        def wrap_method(func):
            handler = without_return_value(
                as_handler_invocation(
                    self.client, handler_status, func))

            self.init_handlers.append(handler)

            return handler

        return wrap_method

    def ledger_ready(self):
        handler_status = self._notice_handler('Ledger Ready', None, False, True)

        def wrap_method(func):
            handler = without_return_value(
                as_handler_invocation(
                    self.client, handler_status, func))

            self.ready_handlers.append(handler)

            return handler

        return wrap_method

    def transaction_start(self):
        handler_status = self._notice_handler('Transaction Start', None, False, True)

        def to_int_event(dazl_event):
            return IntegrationLedgerTransactionEndEvent(
                command_id=dazl_event.command_id,
                workflow_id=dazl_event.workflow_id,
                contract_events=[self._to_int_create_event(e)
                                 for e in dazl_event.contract_events])

        def wrap_method(func):
            handler = with_marshalling(
                to_int_event,
                without_return_value(
                    as_handler_invocation(
                        self.client, handler_status, func)))

            self.client.add_ledger_transaction_start(handler)

            return handler

        return wrap_method

    def transaction_end(self):
        handler_status = \
            self._notice_handler('Transaction End', None, False, True)

        def to_int_event(dazl_event):
            return IntegrationLedgerTransactionEndEvent(
                command_id=dazl_event.command_id,
                workflow_id=dazl_event.workflow_id,
                contract_events=[self._to_int_create_event(e)
                                 for e in dazl_event.contract_events])

        def wrap_method(func):
            handler = with_marshalling(
                to_int_event,
                without_return_value(
                    as_handler_invocation(
                        self.client, handler_status, func)))

            self.client.add_ledger_transaction_end(handler)

            return handler

        return wrap_method

    def contract_created(
            self, template: Any, match: 'Optional[ContractMatch]' = None,
            sweep: bool = True, flow: bool = True, package_defaulting: bool = True):

        if package_defaulting:
            ftemplate = ensure_package_id(self.daml_model, template)
        else:
            ftemplate = template

        LOG.info('Registering contract_created: %r (match: %r, sweep/flow: %r/%r)',
                 ftemplate, match, sweep, flow)

        handler_status = \
            self._notice_handler(f'Contract Create', ftemplate, sweep, flow)

        def wrap_method(func):
            wfunc = without_return_value(
                as_handler_invocation(
                    self.client, handler_status, func))

            if sweep:
                self.sweeps.append((ftemplate, match, wfunc))

            handler = with_marshalling(self._to_int_create_event, wfunc)

            if flow:
                self.client.add_ledger_created(ftemplate, match=match, handler=handler)

            return handler

        return wrap_method

    def contract_archived(self, template: Any, match: 'Optional[ContractMatch]' = None,
                          package_defaulting: bool = True):

        if package_defaulting:
            ftemplate = ensure_package_id(self.daml_model, template)
        else:
            ftemplate = template

        LOG.info('Registering contract_archived: %r (match: %r)', ftemplate, match)

        handler_status = \
            self._notice_handler(f'Contract Archive', ftemplate, False, True)

        def to_int_event(dazl_event):
            return IntegrationLedgerContractArchiveEvent(
                cid=dazl_event.cid)

        def wrap_method(func):
            handler = with_marshalling(
                to_int_event,
                without_return_value(
                    as_handler_invocation(
                        self.client, handler_status, func)))

            self.client.add_ledger_archived(ftemplate, match=match, handler=handler)

            return handler

        return wrap_method

    def get_status(self) -> 'Sequence[LedgerHandlerStatus]':
        return self.handlers
