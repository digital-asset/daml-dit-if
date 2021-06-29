daml-dit-if
====

Daml Hub [integrations](https://hub.daml.com/docs/quickstart/#integrations)
are loadable Python modules that mediate the relationship between a Daml Hub
ledger and various external systems. Because of their special role within
Daml Hub, integrations have the ability to issue and receive external
network requests in addition to the usual ledger interactions supported
by [bots](https://hub.daml.com/docs/quickstart/#python-bots)
and [triggers](https://hub.daml.com/docs/quickstart/#daml-triggers).
This gives integrations the ability to issue network requests based on
ledger activity as well as issue ledger commands based on network
activity. To allow monitoring and control by Daml Hub, integrations must
also follow a set of interface conventions. This repository
contains a framework that builds on Digital Asset's
[DAZL Ledger Client](https://github.com/digital-asset/dazl-client)
to simplify development of common types of integrations.

This framework makes it possible to develop custom integration
types, but due to their access to the network, integrations have
privileged status within Daml Hub and require elevated permissions to
install. Please contact [Digital Asset](https://discuss.daml.com/) for
more information on deploying custom integration types into Daml Hub.

For examples of fully constructed integrations built with the
framework, there are several open source examples available in GitHub
repositories. These also correspond to some of the default integrations
available to all Daml Hub users via the _Browse Integrations_ tab in the
[console](https://hub.daml.com/docs/quickstart)'s ledger view.

* [Core Pack](https://github.com/digital-asset/daml-dit-integration-core)
* [Coindesk](https://github.com/digital-asset/daml-dit-integration-coindesk)
* [Slack](https://github.com/digital-asset/daml-dit-integration-slack)
* [Exberry](https://github.com/digital-asset/daml-dit-integration-exberry)


## Integration Packaging and Deployment

Integrations are packaged in [DIT files](https://github.com/digital-asset/daml-dit-api),
built using the [`ddit` build tool](https://github.com/digital-asset/daml-dit-ddit),
and can be deployed into Daml Hub using the same upload mechanism as other
artifacts (Daml Models, bots, etc.). Daml Hub also has an 'arcade' facility
that uses a public [GitHub repository](https://github.com/digital-asset/daml-dit-arcade-index)
to maintain a list of integrations and sample apps that can be deployed through
a single click on the [console user interface](https://hub.daml.com/docs/quickstart).

Logically speaking, Daml Hub integrations package their Python
implementation code alongside metadata describing available
integration types and any other resources required to make the
integration operate. Integrations usually require Daml models to
represent their data model, and often require external Python
dependencies specified through a `requirements.txt` file. Both of
these are examples of additional resources that might be bundled into
a DIT file.  Note that while `daml-dit-if` and `dazl` are both Python
dependencies required by integrations, they are exceptions to this
rule.  Daml Hub provides both of these by default, so they should not
be listed in `requirements.txt` and should not be included in the DIT
file.

## Integration Design Guidelines

Building integrations for Daml Hub, we've found the following to be good
guidance for designing reliable and usable integrations:

* Rather than require a number of distinct integration types or integration instances, favor designs that reduce the number of types and instances. This can simplify both configuration and deployment.
* When possible, consider using contracts on ledger to allow configuration of multiple activities of the same integration rather than multiple instances of the same integration with different sets of configuration parameters.
* Store private API tokens and keys on-ledger in contracts. This restricts visibility of secrets to the integration itself.
* Try to ensure that as much retry/handshaking logic is managed directly in integration code, rather than in Daml. This makes it easier to ensure that the Daml logic is more purely focused on the business processes being modeled rather than the details of the integration protocol.
* Prefer level sensitive logic to edge sensitive logic. Rather than triggering an external interaction based on the occurrence of an event, trigger based on the presence of a contract and archive the contract when the interaction is complete. This can improve reliability and error recovery in the event of failed integrations, and help keep technical integration details out of the business logic in Daml.

## The Integration Framework API

The integration framework API has two parts:

* Metadata describing the available integration types.
* A Python API for registering event handlers.

The metadata for an integration is stored in an additional
`integration_types` section within `dabl-meta.yaml`. This section
lists and describes the integration types defined within the DIT file.
This metadata section includes the name of the entry point function
for the integration type, some descriptive text, and a list of the
configuration arguments accepted by the integration:

The [ledger event log integration](https://github.com/digital-asset/daml-dit-integration-core/blob/master/src/core_int/integration_ledger_event_log.py) is defined like this:

```yaml
catalog:

    ... elided ...

integration_types:

    ... elided ...

    - id: com.projectdabl.integrations.core.ledger_event_log
      name: Ledger Event Log
      description: >
          Writes a log message for all ledger events.
      entrypoint: core_int.integration_ledger_event_log:integration_ledger_event_log_main
      env_class: core_int.integration_ledger_event_log:IntegrationLedgerEventLogEnv
      fields:
          - id: historyBound
            name: Transaction History Bound
            description: >
                Bound on the length of the history maintained by the integration
                for the purpose of the log fetch endpoint. -1 can be used to remove
                the bound entirely.
            field_type: text
            default_value: "1024"
```


* `id` - The symbolic identifier used to select the integration type within the DIT.
* `name` - A user friendly name for the integration.
* `description` - A description of what the integration does.
* `entrypoint` - The package qualified name of the entrypoint function.
* `env_class` - The package qualified name of the class used to contain the integration's _environment_.
* `fields` - A list of [configuration fields](https://github.com/digital-asset/daml-dit-if#integration-configuration-arguments) that users will be able to enter through the console when configuring an integration. These will be passed into the integration instance at runtime via an instance of `env_class`.

The `entrypoint` and `env_class` fields identify by name the two
Python structures that represent the runtime definition of an
integration type's implemenation.

The first, `entrypoint`, is required for all integration types and
names a function the framework calls when starting a new instance of
an integration. During the entrypoint function, integrations are able
to register handlers for various sort of events (ledger, web, and
otherwise), start coroutines, and access integration configuration
arguments specified through the Daml Hub console UI. The syntax for
`entrypoint` is `$PYTHON_PACKAGE_NAME:$FUNCTION_NAME`, and the function
itself must have the following signature.

```python
from daml_dit_if.api import IntegrationEvents

def integration_ledger_event_log_main(
        env: 'IntegrationLedgerEventLogEnv',
        events: 'IntegrationEvents'):

```

The `events` argument is an instance of [`IntegrationEvents`](https://github.com/digital-asset/daml-dit-if/blob/master/daml_dit_if/api/__init__.py#L272)
containing a number of [function decorators](https://www.python.org/dev/peps/pep-0318/)
that can be used to register [event handlers](https://github.com/digital-asset/daml-dit-if#integration-event-handlers).
This represents the bulk of the integration call API, and contains
means to register handlers for various DAZL ledger events, HTTPS
endpoints, timers, and internal message queues. Based on the event
handlers that the integration registers, the integration framwork
configures itself appropriately to make those events known to the
integration while it is running.

The `env` argument is the environment in which the integration is
running. This contains named fields with all of the integration
configuration parameters, as well as access to various other features
of the integration framework. These include in-memory queuing and
metadata for the Daml model associated with the integration. Because
the configuration parameters for an integration can vary from
one integration type to the next, the type of `env` can be specialized
to the given integration type. For the example above, the specific
environment type `IntegrationLedgerEventLogEnv`, is defined as
follows.

```python
from daml_dit_if.api import IntegrationEnvironment


@dataclass
class IntegrationLedgerEventLogEnv(IntegrationEnvironment):
    historyBound: int

```

The environment class for an integration type is named in
`dabl-meta.yaml` with the field `env_class`. This class must derive
from [`IntegrationEnvironment`](https://github.com/digital-asset/daml-dit-if/blob/master/daml_dit_if/api/__init__.py#L280),
and if a specific subclass is not specified, the integration will
receive an instance of `IntegrationEnvironment` as its environment
when it starts up.  The syntax for `env_class` is the same as the
syntax for `entrypoint` : `$PYTHON_PACKAGE_NAME:$FUNCTION_NAME`.

## Logging

Daml Hub integrations use the default Python logging package, and the
framework provides support for controlling log level at runtime. To
integrate properly with this logic, it is important that integrations
use the standard mechanism for accessing the integration logger. This
logger is switched from `INFO` level to `DEBUG` level at a
`DABL_LOG_LEVEL` setting of 10 or above.

```python
from daml_dit_if.api import getIntegrationLogger

LOG = getIntegrationLogger()
```

## Integration coroutines

For integrations that need to maintain ongoing processing independent
of event handlers, a coroutine can be returned from the
entrypoint. The framework will arrange for this coroutine to be
scheduled for execution alongside the other coroutines managed by the
framework itself. For an example of this, see the [Exberry integration](https://github.com/digital-asset/daml-dit-integration-exberry/blob/c34e0962631da181a0bcd7ed92ef2aa4fbc8eb46/src/exberry_int/integration_exberry.py#L347).

## Integration Event Handlers

Integrations are purely event driven and may only take action in
response to an event notification from the framework. Integrations
register their interest in given events by decorating custom functions
with decorators provided to the integration when it is starting
up. These decorators are found in the `IntegrationEvents` instance
passed to the entrypoint function. As an example, the 
[Slack integration](https://github.com/digital-asset/daml-dit-integration-slack)
listens for outbound messages as follows.

```python
def integration_slack_main(
        env: 'IntegrationEnvironment',
        events: 'IntegrationEvents'):

... elided ...

    @events.ledger.contract_created(
        'SlackIntegration.OutboundMessage:OutboundMessage')
    async def on_contract_created(event):
         ... elided ...
```

Once the integration has started, `on_contract_created` will be called
for each DAZL event corresponding to an `OutboundMessage` contract
being created on the ledger.

In addition to ledger events, the framework provides a range of other
types of integration event handlers:


```python
@dataclass
class IntegrationEvents:
    queue: 'IntegrationQueueEvents'
    time: 'IntegrationTimeEvents'
    ledger: 'IntegrationLedgerEvents'
    webhook: 'IntegrationWebhookRoutes'
```

* **Ledger** - [DAZL](https://github.com/digital-asset/dazl-client) ledger events. (Contract Archived, Contract Created, Transaction Boundaries, etc.)
* **Webhook** - Inbound HTTPS requests from the outside world. (GET or POST)
* **Time** - Periodic timer events. (Useful to poll an external system, etc.)
* **Queue** - In-memory message queue events. (Useful when none of the other types apply.)

### Ledger Events

The framework provides ledger event handlers for ledger initializtion
events, transaction boundaries, and contract create and archived
events.  These events are all subject to the Daml ledger visiblity
model. An integration runs as a specific ledger party with a specific
set of rights to the ledger. The integration will only see contract
events visible to that party.

All ledger event handlers can return a list of DAZL ledger commands to
be issued by the framework when the event handler returns.

```python
from dazl import exercise

... elided ...

    @events.ledger.contract_created(
        'SlackIntegration.OutboundMessage:OutboundMessage')
    async def on_contract_created(event):
         ... elided ...

         return [exercise(event.cid, 'Archive')]
```

The contract created decorator takes a few of arguments that
control how it presents events to the framework.

```python
@abc.abstractmethod
def contract_created(self, template: Any, match: 'Optional[ContractMatch]' = None,
                     sweep: bool = True, flow: bool = True):
```

`template` is the DAZL template query string for event handler.  The
event handler will be called only for contracts that match this
query. It can be `*` to subscribe to all templates, or it can be a
qualified template name:

```python
    @events.ledger.contract_created(
        'SlackIntegration.OutboundMessage:OutboundMessage')
    async def on_contract_created(eve
```

If the template name does not specify a full package ID, the framework
will assume that the template name refers to a template in the
integration's package and automatically qualify that name with the
package ID. This eliminates ambiguity if there are multiple templates
with the same symbolic name and eliminates a DAZL error that occurs
when subscribing to contract template that the ledger has not yet seen
instantiated.

`sweep` and `flow` control how the event handler sees historical and
newly created contracts on the ledger. If `sweep` is `True`, the
framework will sweep the ledger for contracts that already exist when
the integration is starting up and call the event handler for each
such contract when starting up. When `flow` is `True`, the integration
will receive events corresponding to new contracts that are created
while it is running. Note that the framework provides no corresponding
control over contract archived events. If an archived event handler is
registered for a contract template, it will receive all visible
archive events for the template, regardless of whether or not the
framework called a created event handler corresponding to the
template.

### Webhook Events

Each integration instance maintains an `aiohttp` web endpoint that's
used to accept inbound HTTPS requests from external systems. Integrations
can register to receive both `GET` and `POST` requests from external
systems using the `webhook` event decorators.

```python
    @events.webhook.post(label='Slack Event Webhook Endpoint')
    async def on_webhook_post(request):
        body = await request.json()
```

Each integration is assigned a base Daml Hub URL based on the name of
its enclosing ledger and its integration ID. All webhook URL's for a
given integration are relative to that assigned base URL, and are
presented to the user via the integration status display.

Due to their nature, webhook handlers have to have the ability to
return both a set of ledger commands and an HTTP response. This is
accomodated with the `IntegrationWebhookResponse` class that contains
both a `commands` field and a `response` field.


```python
from daml_dit_if.api import IntegrationWebhookResponse

    @events.webhook.get(url_suffix='/json', label='JSON Table', auth=AuthorizationLevel.PUBLIC)
    async def on_get_table_json(request):
        row_data = get_formatted_table_data()

        return IntegrationWebhookResponse(
            response=json_response({'rows': row_data}))
```

To populate the `response` of an `IntegrationWebhookResponse`, there
are also several utility functions for generating standard `aiohttp`
responses:

```python
from daml_dit_if.api import \
    json_response, \
    empty_success_response, \
    blob_success_response, \
    unauthorized_response, \
    forbidden_response, \
    not_found_response, \
    bad_request, \
    internal_server_error
```

#### Webhook Event Configuration

The full definition for an integration decorator allows several
parameters to control the event handler.

```python
    @abc.abstractmethod
    def get(self, url_suffix: 'Optional[str]' = None, label: 'Optional[str]' = None,
             auth: 'Optional[AuthorizationLevel]' = AuthorizationLevel.PUBLIC):
```

`label` is a user friendly description of the event handler URL. It is
used to label the status presented to the event handler as it is
displayed in the console.

`url_suffix` is the URL suffix for this event handler relative to the
integration's base URL. It can be used to distinguish multiple
endpoints within the same integration if necessary, or left out
entirely. `aiohttp` pattern matching works in these suffixes as well.

`auth` is the authorization mode of the webhook endpoint. By default,
all webhook endpoints are publically visible, but the framework has
two options for stricter access controls.

* `ANY_PARTY` - Requests must be presented with a valid Daml Hub JWT corresponding to the integration's ledger.
* `INTEGRATION_PARTY` - Requests must be presented with a valid Daml Hub JWT corresponding to the integration's ledger and party.

A JWT is considered to be valid for a given party, only if that party
is listed in both the `readAs` and `actAs` claims.

`ANY_PARTY` is intended to be used in scenarios where the integration
might wish to enforce its own access controls based on an
authenticated user identity. To support this, the framework has two
functions for extracting the user's identify from an inbound
request. Note that these functions do not return results on `PUBLIC`
endpoints, due to the fact that there is no authentication checking
done for these endpoints and no notion of request identity.

```python
from daml_dit_if.api import
    get_request_parties, \
    get_single_request_party

    ... elided. ..

    @events.webhook.get(label='CSV Table', auth=AuthorizationLevel.INTEGRATION_PARTY)
    async def on_get_table_csv(request):
        row_data = get_formatted_table_data()

        LOG.info('>>> %r/%r', get_request_parties(request), get_single_request_party(request))
```

### Timer Events

To support time-based activities (polling, etc.), the integration
framework provides support for periodic timer events. These are events
that the framework schedules to be invoked at a repeating schedule at
a fixed interval. The interval is specified in seconds and the
decorator contains an optional label argument used to populate the
descriptive text on the integration status display.  As with other
event handlers, the handler for timer events can return a list of
ledger commands to be issued by the framework.

```python
    @events.time.periodic_interval(env.interval, label='Periodic Timer')
    async def interval_timer_elapsed():
        LOG.debug('Timer elapsed: %r', active_cids)
        return [exercise(cid, env.templateChoice, {})
                for cid
                in active_cids]
```

The integration framework makes a best effort attempt to call the
timer event handler at the requested periodicity, but no guarantees
are made about exact timing. The requested periodicity should be
considered a minimum. The event handler for a given timer will not be
called re-entrantly.

### Queue Events

The integration framework also provides in-memory queues and will call
queue event handlers for message placed on those queues. The intent of
this capability is to provide a way for integrations to respond to
types of events that the other event handlers do not cover.  An
example of this is the [Symphony integration](https://github.com/digital-asset/daml-dit-integration-symphony),
which uses queue events to accept and process incoming messages
received from the Symphony client library. Because there is no
framework event handler specific to Symphony, the client library
connection is opened as part of initialization and is written to place
incoming messages from the socket onto an internal messaging
queue. The queue handler can then take appropriate action on the
ledger for inbound events. This is also the preferred integration
strategy for websockets - open the connection when the integration
is initialized and have the connection post events to a framework queue
for integration processing.

This is how the Sympnony integration registers the handler:

```python
def integration_symphony_receive_dm_main(
        env: 'IntegrationSymphonyReceiveDMEnv',
        events: 'IntegrationEvents'):

    ... elided ...

    @events.queue.message()
    async def handle_message(message):
        return [create(message['type'], message['payload'])]
```

Inbound messages are placed into the queue using `env.queue.put(...)`:

```python
    async def on_im_message(self, im_message):

        ... elided ...

        await self.env.queue.put(msg_data)
```

Both the event handler decorator and the `put` call accept an optional
`queue_name` that allows messages to be divided into multiple channels
for separate handling.

```python
class IntegrationQueueSink:

    @abc.abstractmethod
    async def put(self, message: 'Any', queue_name: 'str' = 'default'):


class IntegrationQueueEvents:

    @abc.abstractmethod
    def message(self, queue_name: 'str' = 'default'):
```

There is neither a persistence guarantee nor any retry logic in the
internal queuing mechanism. If a message is placed on an internal
queue and the integration fails or is stopped before the event handler
is invoked, the message will not be processed.

## Integration Configuration Arguments

Integrations can be paramterized using multiple mechanisms, each with
pros and cons. By default, every integration (and Daml Hub automation
in general) is configured with a ledger party and a label. The
integration is connected to the ledger as that party, and the label is
essentially a comment that can be used to describe the purpose of the
automation.

Integrations may also receive configuration information via ledger
contracts. The [CoinDesk Integration](https://github.com/digital-asset/daml-dit-integration-coindesk/blob/master/src/core_int/integration_coindesk_price.py#L99)
uses contracts to describe the number of BTC exchange rates to
maintain on the ledger. The integration accepts this configuration
via the ledger directly. This is also the preferred way to communicate
API keys, tokens etc. to an integration. The Daml ledger privacy model
prevents any private data communicated via contract from exposure to
unauthorized parties.

For other sorts of configurations, there is also a mechanism by which
integrations can define configuration fields. These are presented to
the user in the integration configurator and communicated to the
integration via an argument file (`int_args.yaml`) that's parsed by
the framework and passed to the entrypoint function via the `env`
argument. These configuration parameters can contain descriptions and
be of data types that are specifically useful integrations. In additon
to numbers and strings, there is also support for configuration fields
that are enumerations, party identifiers, contract template ID's,
contract choice names, etc. They are configured in the `fields` block
of the integration type definition of `dabl_meta.yaml`.

Here is an example field list definition from the Ledger Event Log
integration.

```yaml
      fields:
          - id: historyBound
            name: Transaction History Bound
            description: >
                Bound on the length of the history maintained by the integration
                for the purpose of the log fetch endpoint. -1 can be used to remove
                the bound entirely.
            field_type: text
            default_value: "1024"
```

* `id` - The machine readable ID of the field. This corresponds to the field name in the `env_class` class instance used to store the environment.
* `name` - The user friendly name of the configuration field.
* `description` - Long form text describing the purpose of the configuration field.
* `field_type` - The type definition of the configuration field.
* `default_value` - An optional default value for the field.
* `required` - An optional boolean that can be explicitly set to `false` is the field  is optional

| Type Name           | Description |
|---------------------|-------------|
| _default_ or `text`          | Plain single line text.            |
| `number`            | A number, decimals allowed.            |
| `integer`           | An integer. Presented as a field with arrow up/down.            |
| `party`             | The name of a ledger party. Presented as a dropdown.          |
| `contract_template` | The name of a contract template on the ledger. Presented as a dropdown            |
| `contract_choice`   | The name of a choice on a contract template specified by another `contract_template` field. Specified with a JSON reference to the template field: `contract_choice:{"templateNameField": "targetTemplate"}`  |
| `enum`              | An enumeration. Specified with a JSON list of choices: `enum:["Create And Execute", "Trigger Contract"]`            |
| `clob`              | Long form text, presented as multiple lines.            |
