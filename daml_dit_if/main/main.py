import asyncio
import base64
import logging
import pkg_resources
import sys
import yaml

from dataclasses import dataclass
from pathlib import Path
from asyncio import ensure_future, gather, get_event_loop
from typing import Optional, Dict
from dacite import from_dict

from aiohttp import ClientSession
from yarl import URL

from aiohttp.web import Application, AppRunner, TCPSite, RouteTableDef, \
    Request, Response

from dazl import Network

from daml_dit_api import \
    IntegrationRuntimeSpec, \
    IntegrationTypeInfo, \
    PackageMetadata

from .config import Configuration, get_default_config

from .log import FAIL, LOG, setup_default_logging, set_log_level

from .web import start_web_endpoint

from .integration_context import IntegrationContext
from .package_metadata_introspection import get_package_metadata


def load_integration_spec(config: 'Configuration') -> 'Optional[IntegrationRuntimeSpec]':
    spec_path = Path(config.integration_spec_path)

    if spec_path.exists():
        LOG.debug('Loading integration spec from: %r', spec_path)

        yaml_spec=yaml.safe_load(spec_path.read_bytes())

        LOG.info('Integration spec: %r', yaml_spec)

        return from_dict(
            data_class=IntegrationRuntimeSpec,
            data=yaml_spec)

    else:
        LOG.error(f'No spec file found at: {repr(spec_path)}')
        return None


def create_network(url: str) -> 'Network':
    network = Network()
    network.set_config(url=url)
    return network


async def run_dazl_network(network: 'Network'):
    """
    Run the dazl network, and make sure that fatal dazl errors terminate the application.
    """
    try:
        LOG.info('Starting dazl network...')

        await network.aio_run()
    except:  # noqa
        LOG.exception('The main dazl coroutine died with an exception')

    FAIL('Execution cannot continue without dazl coroutine.')


async def _aio_main(
        integration_type: 'IntegrationTypeInfo',
        config: 'Configuration',
        type_id: str,
        integration_spec: 'IntegrationRuntimeSpec',
        metadata: 'PackageMetadata'):

    network = create_network(config.ledger_url)
    dazl_coro = ensure_future(run_dazl_network(network))

    integration_context = \
        IntegrationContext(
            network, config, integration_type, type_id, integration_spec, metadata)

    await integration_context.safe_load()

    integration_coro = integration_context.get_coro()

    if integration_coro:
        LOG.info('Integration coroutine ready, starting web endpoint.')

        web_coro = start_web_endpoint(config, integration_context)

        integration_startup_coro = integration_context.safe_start()

        LOG.info('Starting main loop.')
        await gather(
            web_coro, dazl_coro, integration_coro, integration_startup_coro)

        return True

    return False


def _get_integration_types(metadata: 'PackageMetadata') -> 'Dict[str, IntegrationTypeInfo]':

    package_itypes = (metadata.integration_types
                      or metadata.integrations  # support for deprecated
                      or [])

    return {itype.id: itype for itype in package_itypes}


def main():
    setup_default_logging()

    LOG.info('Initializing dabl-integration...')

    # Parsing certain DAML-LF modules causes very deep stacks;
    # increase the standard limit to be able to handle those.
    sys.setrecursionlimit(10000)

    config = get_default_config()

    set_log_level(config.log_level)

    metadata = get_package_metadata(config)

    integration_types = _get_integration_types(metadata)
    integration_spec = load_integration_spec(config)

    type_id = config.type_id

    if integration_spec and not type_id:
        # Allow fallback to the spec file on disk, to support
        # execution on DABL clusters that do not inject type ID
        # via an environment variable.
        type_id = integration_spec.type_id

    if not type_id:
        # Guide the user to provide the type ID via the current
        # environment variable rather than with the deprecated config
        # file approach.
        raise Exception('DABL_INTEGRATION_TYPE_ID environment variable undefined')

    integration_type = integration_types.get(type_id)

    if not integration_type:
        FAIL(f'No integration of type {type_id}')

    if integration_spec:
        LOG.info('Running integration type: %r...', type_id)

        loop = get_event_loop()

        if not loop.run_until_complete(
                _aio_main(integration_type, config, type_id, integration_spec, metadata)):
            FAIL('Error initializing integration, shutting down.')

    else:
        FAIL('No metadata file. Terminating without running')
