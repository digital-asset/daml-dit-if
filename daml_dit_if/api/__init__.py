import abc
import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Optional, Sequence

from aiohttp.helpers import sentinel
from aiohttp.web import Response
from daml_dit_api import DamlModelInfo
from dazl import Command, ContractData, ContractId
from dazl.query import ContractMatch

from ..main.auth_accessors import get_request_parties, get_single_request_party
from .common import (
    bad_request,
    blob_success_response,
    empty_success_response,
    ensure_package_id,
    forbidden_response,
    internal_server_error,
    json_response,
    not_found_response,
    unauthorized_response,
)


def _empty_commands() -> 'Sequence[Command]':
    return list()


@dataclass(frozen=True)
class IntegrationResponse:
    """
    Response to an integration event. All such responses contain
    a sequence of zero or more ledger commands to issue.
    """
    commands: 'Optional[Sequence[Command]]' = field(default_factory=_empty_commands)
    command_timeout: 'int' = 5


class IntegrationQueueSink:

    @abc.abstractmethod
    async def put(self, message: 'Any', queue_name: 'str' = 'default'):
        """
        Put a message onto the internal message queue with the given
        name. Throws an exception if there is no queue of that name.
        """
        pass


class IntegrationQueueEvents:

    @abc.abstractmethod
    def message(self, queue_name: 'str' = 'default'):
        """
        Register a function as a handler for internal queue message events.
        The function will be invoked for each message placed on the message
        queue of the given name. The message queue of that name is implicitly
        created by the presence of an event handler. Attempting to register
        two or more event handlers for the same queue is an error. There is no
        retry logic in the event of  handler failure.
        """
        pass


class IntegrationTimeEvents:

    @abc.abstractmethod
    def periodic_interval(self, seconds, label: 'Optional[str]' = None):
        """
        Register a function as a handler for periodic timer events. The
        function will be scheduled to run at the specified
        interval. Note that while multiple interval timers can be used
        by a single integration, only one will ever run at once, with
        jobs skipped in the event of overruns.
        """
        pass


@dataclass(frozen=True)
class IntegrationLedgerContractEvent:
    """
    Base class for ledger integration events related to actions taken
    on contracts.
    """
    cid: ContractId


@dataclass(frozen=True)
class IntegrationLedgerContractCreateEvent(IntegrationLedgerContractEvent):
    """
    Event raised to notify an integration of a contract on ledger.  When
    an integration is started up, this event is raised for each contract
    of interest already on the ledger. While an integration is running,
    this event is raised within transaction boundaries to describe contracts
    created within that transaction. The extent of the contract's validity
    in the integration's event stream spans this event and the corresponding
    :class:`IntegrationLedgerContractArchiveEvent` for the CID.
    """
    initial: bool
    cdata: ContractData


@dataclass(frozen=True)
class IntegrationLedgerContractArchiveEvent(IntegrationLedgerContractEvent):
    """
    Event raised to notify an integration of a contract archive on ledger. This
    represents the end of the validity of the contact with this CID, and this
    event will never be raised before the integration receives a
    :class:`IntegrationLedgerContractCreateEvent` for the contract.
    """


@dataclass(frozen=True)
class IntegrationLedgerTransactionEvent:
    """
    Base class for transaction boundary events.
    """
    command_id: str
    workflow_id: str
    contract_events: 'Sequence[IntegrationLedgerContractEvent]'


@dataclass(frozen=True)
class IntegrationLedgerTransactionStartEvent(IntegrationLedgerTransactionEvent):
    """
    Event raised to signal the beginning of a ledger transaction. Outside of
    integration startup, all contract events occur between this and
    a matching transaction end event.
    """


@dataclass(frozen=True)
class IntegrationLedgerTransactionEndEvent(IntegrationLedgerTransactionEvent):
    """
    Event raised to signal the end of a ledger transaction. Outside of
    integration startup, all contract events occur between this and
    a matching transaction start event occurring earlier in the event stream.
    """


class IntegrationLedgerEvents:

    @abc.abstractmethod
    def ledger_init(self):
        """
        Decorator for registering a callback to be invoked when the
        ledger event stream has been connected and is initializing.
        Called before any :meth:`ledger_create` event, sweep or flow.
        """

    @abc.abstractmethod
    def ledger_ready(self):
        """
        Decorator for registering a callback to be invoked when the
        ledger event stream has been initialized. Called after
        any :meth:`ledger_create` event resulting from an initial sweep
        of contracs and before any flow events.
        """

    @abc.abstractmethod
    def transaction_start(self):
        """
        Decorator for registering a callback to be invoked when the
        integration receives a new transaction. Called before
        individual :meth:`ledger_create` and :meth:`ledger_archive`
        callbacks occurring within the transaction.
        """

    @abc.abstractmethod
    def transaction_end(self):
        """
        Decorator for registering a callback to be invoked when the
        integration receives a new transaction. Called after
        individual :meth:`ledger_create` and :meth:`ledger_archive`
        callbacks occurring within the transaction.
        """

    @abc.abstractmethod
    def contract_created(self, template: Any, match: 'Optional[ContractMatch]' = None,
                         sweep: bool = True, flow: bool = True):
        """
        Register a callback to be invoked when the integration encounters a newly created
        contract instance of a template.

        :param template:
            A template name to subscribe to, or '*' to subscribe on all templates.
        :param handler:
            The callback to invoke whenever a matching template is created.
        :param match:
            An (optional) parameter that filters the templates to be received by the callback.
        :param sweep:
            An (optional) parameter that controls whether or not the integration receives
            a sweep of all existing active contracts on startup.
        :param flow:
            An (optional) parameter that controls whether or not the integration receives
            contract messages after the initial sweep. (If both sweep and flow are false,
            the handler will never be called.)
        """

    @abc.abstractmethod
    def contract_archived(self, template: Any, match: 'Optional[ContractMatch]' = None):
        """
        Decorator for registering a callback to be invoked when the integration
        encounters a newly archived contract instance of a template.

        :param template:
            A template name to subscribe to, or '*' to subscribe on all templates.
        :param match:
            An (optional) parameter that filters the templates to be received by the callback.
        """


@dataclass(frozen=True)
class IntegrationWebhookResponse(IntegrationResponse):
    """
    Response to a webhook request. Contains both the
    ledger commands needed to fulfill the hook and the
    HTTP response.
    """

    response: 'Optional[Response]' = None

    json_response: Any = sentinel
    text_response: 'Optional[str]' = None
    blob_response: 'Optional[bytes]' = None

    http_content_type: 'Optional[str]' = None
    http_status: int = 200


class AuthorizationLevel(Enum):
    PUBLIC = "DABL_PUBLIC"
    ANY_PARTY = "DABL_ANY_PARTY"
    INTEGRATION_PARTY = "DABL_INTEGRATION_PARTY"


class IntegrationWebhookRoutes:

    @abc.abstractmethod
    def post(self, url_suffix: 'Optional[str]' = None, label: 'Optional[str]' = None,
             auth: 'Optional[AuthorizationLevel]' = AuthorizationLevel.PUBLIC):
        """
        Register a function as an HTTP POST handler for the integration's webhook.
        Integration HTTP handlers must return an instance of
        :class:`IntegrationWebhookResponse`.

        :param url_suffix:
            The suffix for the URL of the webhook resource. This is appended to
            an integration URL provided by DABL to form the full URL of the resource.

        :param label:
            A user-friendly description of the purpose of the webhook resource. This
            is displayed as on the DABL console to identify the purpose of the URL.
        """

    @abc.abstractmethod
    def get(self, url_suffix: 'Optional[str]' = None, label: 'Optional[str]' = None,
             auth: 'Optional[AuthorizationLevel]' = AuthorizationLevel.PUBLIC):
        """
        Register a function as an HTTP GET handler for the integration's webhook.
        Integration HTTP handlers must return an instance of
        :class:`IntegrationWebhookResponse`.

        :param url_suffix:
            The suffix for the URL of the webhook resource. This is appended to
            an integration URL provided by DABL to form the full URL of the resource.

        :param label:
            A user-friendly description of the purpose of the webhook resource. This
            is displayed as on the DABL console to identify the purpose of the URL.
        """


@dataclass
class IntegrationEvents:
    queue: 'IntegrationQueueEvents'
    time: 'IntegrationTimeEvents'
    ledger: 'IntegrationLedgerEvents'
    webhook: 'IntegrationWebhookRoutes'


@dataclass
class IntegrationEnvironment:
    queue: 'IntegrationQueueSink'
    party: str
    daml_model: 'Optional[DamlModelInfo]'

    def tid(self, template_id: str) -> str:
        return ensure_package_id(self.daml_model, template_id)

IntegrationEntryPoint = \
    Callable[[IntegrationEnvironment, IntegrationEvents], None]

def getIntegrationLogger():
    return logging.getLogger('integration')
