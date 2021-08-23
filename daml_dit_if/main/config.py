import os
from dataclasses import dataclass, asdict
from typing import Optional

from daml_dit_api import \
    DABL_META_NAME

from .log import FAIL, LOG

@dataclass(frozen=True)
class Configuration:
    health_port: int
    ledger_url: str
    ledger_id: str
    dit_meta_path: str
    integration_spec_path: str
    type_id: 'Optional[str]'
    run_as_party: 'Optional[str]'
    log_level: int
    jwks_url: 'Optional[str]'
    queue_size: int


def optenv(var: str) -> 'Optional[str]':
    val = os.getenv(var)

    LOG.debug('Configuration environment lookup: %r => %r', var, val)

    return val


def env(var: str, default: 'Optional[str]' = None) -> str:
    val = optenv(var)

    if val:
        return val
    elif default is not None:
        LOG.debug('Using default %r for unspecified configuration environment variable: %r',
                  default, var)
        return default
    else:
        FAIL(f'Missing required environment variable: {var}')
        return ''  # unreached


def envint(var: str, default: 'Optional[int]' = None) -> int:
    val = env(var, None if default is None else str(default))

    try:
        return int(val)
    except ValueError:
        FAIL(f'Invalid integer {val} in environment variable: {var}')

def get_default_config() -> 'Configuration':
    config = Configuration(
        health_port=envint('DABL_HEALTH_PORT', 8089),
        ledger_url=env('DABL_LEDGER_URL', 'http://localhost:6865'),
        ledger_id=env('DABL_LEDGER_ID', 'cloudbox'),
        dit_meta_path=env('DAML_DIT_META_PATH', DABL_META_NAME),
        integration_spec_path=env('DABL_INTEGRATION_METADATA_PATH', 'int_args.yaml'),
        type_id=optenv('DABL_INTEGRATION_TYPE_ID'),
        run_as_party=optenv('DAML_LEDGER_PARTY'),
        log_level=envint('DABL_LOG_LEVEL', 0),
        jwks_url=optenv('DABL_JWKS_URL'),
        queue_size=envint('DABL_QUEUE_SIZE', 512))

    LOG.info('Configuration: %r', asdict(config))

    return config
