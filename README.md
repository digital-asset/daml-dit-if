daml-dit-if
====

An application framework for integrations written to be hosted in
DABL. Integrations are run within DABL itself and serve to mediate the
relationship between a DABL ledger and external systems. Integrations
can issue and receive network connections, interoperate with a ledger
as a specific configured party, and maintain small amounts of locally
cached data. Due to their privileged status within a DABL cluster,
integrations require specific permissions to install. Please contact
[Digital Asset](https://discuss.daml.com/) for more information.

# Integration Packaging

Integrations are packaged in
[DIT files](https://github.com/digital-asset/daml-dit-api) and built
using the [`ddit` build tool](https://github.com/digital-asset/daml-dit-ddit).
Unlike most DIT files, integrations are  a special case of DIT file
augmented with the ability to run as an executable within a DABL cluster.
This is done by packaging Python
[DAZL bot](https://github.com/digital-asset/dazl-client) code into an
[executable ZIP](https://docs.python.org/3/library/zipapp.html)
using [PEX](https://github.com/pantsbuild/pex). This file is then
augumented with the metadata (`dabl-meta.yaml`) and other resources
needed to make it a fully formed DIT file.

# Developing Integrations

Logically speaking, DABL integrations are DAZL bots packaged with
information needed to fit them into the DABL runtime and user
interface. The major functional contrast between a DABL integration
and a Python Bot is that the integration has the external network
access needed to connect to an outside system and the Python Bot does
not. Due to the security implications of running within DABL with
external network access, integrations can only be deployed with the
approval of DA staff.

It is a requirement that DABL integrations are built with the
framework library defined within this repository. This integration
framework presents a Python API closely related to the DAZL bot api
and ensures that integrations follow the conventions required to run
within DABL. The framework parses ledger connection arguments,
translates configuration metadata into a domain object specific to the
integration, and exposes the appropriate health check endpoints
required to populate the DABL integration user interface.

## The Integration Framework API

The integration framework API has two parts - a Python entry point
that all integrations must provide and an additional section within
`dabl-meta.yaml` that describes the properties of a given
integration. The metadata section includes the name of the entry point
function for the integration, some descriptive text, and a list of
all of the configuration arguments that the integration accepts:

The ledger event log integration is defined like this:

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
      runtime: python-direct
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
* `env_class` - The package qualifies name of the environment class.
* `runtime` - Always `python-direct`.
* `fields` - A list of configuration fields. These are passed into the integration at runtime via correspondingly named fields of an instance of the `env_class`.

The Python definition of the entrypoint is this:


```python
@dataclass
class IntegrationLedgerEventLogEnv(IntegrationEnvironment):
    historyBound: int


def integration_ledger_event_log_main(
        env: 'IntegrationEnvironment',
        events: 'IntegrationEvents'):

```

At integration startup, the framework transfers control to
`integration_ledger_event_log_main` to allow the integration to
initialize itself. The first argument, `env`, is a instance of
`env_class` that contains the runtime values of the various `fields`
that the user has specified for the integration through the DABL
configuration UI. The second argument is an instance of
`IntegrationEvents`, that represents the bulk of the integration API.
`IntegrationEvents` contains a number of decorators that allow the
entrypoint function to register handlers for various types of
interesting events. These include various DAZL ledger events, HTTPS
resources, timers, and internal message queues.

For compelete examples of how the framework is used and integrations
are constructed , please see the following repositories:

* [Core Pack](https://github.com/digital-asset/daml-dit-integration-core)
* [Coindesk](https://github.com/digital-asset/daml-dit-integration-coindesk)
* [Slack](https://github.com/digital-asset/daml-dit-integration-slack)
* [Exberry](https://github.com/digital-asset/daml-dit-integration-exberry)

## A note on logging

DABL integrations use the default Python logging package, and the
framework provides specific support for controlling log level at
runtime. To integrate properly with this logic, it is important that
integrations use the `integration` logger. This logger is switched
from `INFO` level to `DEBUG` level at a `DABL_LOG_LEVEL` setting of 10
or above.

```python
import logging

LOG = logging.getLogger('integration')
```

# Locally Running an integration DIT.

Because they can be directly executed by a Python interpreter,
integration DIT files can be run directly on a development machine
like any other standalone executable. By convention, integrations
accept a number of environment variables that specify key paramaters.
Integrations built with the framework use defaults for these variables
that connect to a default locally configured sandbox instance.

Available variables include the following:

| Variable | Default | Purpose |
|----------|---------|---------|
| `DABL_HEALTH_PORT` | 8089 | Port for Health/Status HTTP endpoint |
| `DABL_INTEGRATION_METADATA_PATH` | 'int_args.yaml' | Path to local metadata file |
| `DABL_INTEGRATION_TYPE_ID` | | Type ID for the specific integration within the DIT to run |
| `DABL_LEDGER_PARTY` | | Party identifier for network connection |
| `DABL_LEDGER_URL` | `http://localhost:6865` | Address of local ledger gRPC API |
| `DABL_LOG_LEVEL` | 0 | Log verbosity level - 0 up to 50. |

Several of these are specifically of note for local development scenarios:

* `DABL_INTEGRATION_INTEGRATION_ID` - This is the ID of the
  integration that would normally come from DABL itself. This needs to
  be provided, but the specific value doesn't matter.
* `DABL_INTEGRATION_TYPE_ID` - DIT files can contain definitions for
  multiple types of integrations. Each integration type is described
  in a `IntegrationTypeInfo` block in the `dabl-meta.yaml` file and
  identified with an `id`. This ID needs to be specified with
  `DABL_INTEGRATION_TYPE_ID`, to launch the appropriate integration
  type within the DIT.
* `DABL_INTEGRATION_METADATA_PATH` - Integration configuration
  parameters specified to the integration from the console are
  communicated to the integration at runtime via a metadata file. By
  convention, this metadata file is named `int_args.yaml` and must be
  located in the working directory where the integration is being run.
* `DABL_HEALTH_PORT` - Each integration exposes health and status over
  a `healthz` HTTP resource. <http://localhost:8089/healthz> is the
  default, and the port can be adjusted, if necessary. (This will be
  the case in scenarios where multiple integrations are being run
  locally.) Inbound webhook resources defined with webhook handlers
  will also be exposed on this HTTP endpoint.

## Integration Configuration Arguments

Integrations accept their runtime configuration parameters through the
metadata block of a configuration YAML file. This file is distinct
from `dabl_meta.yaml`, usually named `int_args.yaml` and by default
should be located in the working directory of the integration. A file
and path can be explicitly specified using the
`DABL_INTEGRATION_METADATA_PATH` environment variable.

The format of the file is a single string/string map located under the
`metadata` key. The keys of the metadata map are the are defined by
the `field`s specified for the integration in the DIT file's
`dabl-meta.yaml` and the values are the the configuration paramaters
for the integration.

Note that historically, integrations have accepted their run as party
as a metadata attribute. This is visible below under the `runAs`
key. However, to better align with the overall DABL automation
architecture, this is now deprecated and integrations must take their
party via the runtime environment variable `DAML_LEDGER_PARTY`.

```yaml
"metadata":
  "interval": "1"
  "runAs": "ledger-party-f18044e5-6157-47bd-8ba6-7641b54b87ff"
  "targetTemplate": "9b0a268f4d5c93831e6b3b6d675a5416a8e94015c9bde7263b6ab450e10ae11b:Utility.Sequence:Sequence"
  "templateChoice": "Sequence_Next"
```
