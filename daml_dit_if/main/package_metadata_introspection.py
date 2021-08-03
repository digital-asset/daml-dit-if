import sys
import yaml
from dacite import from_dict, Config

from typing import Optional, Dict

from .log import LOG
from zipfile import ZipFile

from daml_dit_api import \
    DABL_META_NAME, \
    DamlModelInfo, \
    PackageMetadata, \
    IntegrationTypeInfo

from .config import Configuration

def _get_local_dabl_meta(config: 'Configuration') -> 'Optional[str]':
    dit_meta_path = config.dit_meta_path

    LOG.debug('Attmpting to load DABL metadata from local file: %r',
              dit_meta_path)

    try:
        with open(dit_meta_path, "r") as f:
            return f.read()
    except:  # noqa
        LOG.error(f'Failed to load local DABL metadata {dit_meta_path}')
        return None


def _get_pex_dabl_meta() -> 'Optional[str]':
    pex_filename = sys.argv[0]

    LOG.debug('Attmpting to load DABL metadata from PEX file: %r', pex_filename)

    try:
        with ZipFile(pex_filename) as zf:
            with zf.open(DABL_META_NAME) as meta_file:
                return meta_file.read().decode('UTF-8')
    except:  # noqa
        LOG.error(f'Failed to read {DABL_META_NAME} from PEX file {pex_filename}'
                  f' (This is an expected error in local development scenarios.)')
        return None


def get_package_metadata(config: 'Configuration') -> 'PackageMetadata':
    dabl_meta = _get_pex_dabl_meta() or _get_local_dabl_meta(config)

    if dabl_meta:
        return from_dict(
            data_class=PackageMetadata,
            data=yaml.safe_load(dabl_meta))

    raise Exception(f'Could not find {DABL_META_NAME}, either in running DIT '
                    f'file or locally as {config.dit_meta_path}.')
