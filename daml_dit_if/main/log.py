import logging
import sys
import time
import typing

# The integration framework has its own internal concept of logging
# level that is mapped onto the levels of several distinct channels
# in the underlying Python logging framework. This value is intended
# to be on a scale of 0 to 50 (inclusive), and the specific mapping
# is defined in set_log_level.

_level = 0


LOG = logging.getLogger('daml-dit-if')


def FAIL(message: str) -> typing.NoReturn:
    LOG.error(f'=== FATAL ERROR: {message} ===')

    sys.exit(9)


def setup_default_logging():
    logging.Formatter.converter = time.gmtime

    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s [%(levelname)s] (%(name)s) %(message)s',
        datefmt='%Y-%m-%dT%H:%M:%S%z')

    set_log_level(0)


def get_log_level():
    global _level

    return _level


def is_debug_enabled():
    return get_log_level() >= 20


def set_log_level(level):
    global _level

    if level < 0 or level > 50:
        FAIL(f'Requested log level, {level}, is out of the valid range [0,50].')

    if level > 0 or _level > 0:
        LOG.info(f'Updating log level to {level}')

    logging.getLogger('integration').setLevel(
        logging.DEBUG if level >= 10 else logging.INFO)

    logging.getLogger('daml-dit-if').setLevel(
        logging.DEBUG if level >= 20 else logging.INFO)

    logging.getLogger('dazl').setLevel(
        logging.DEBUG if level >= 40 else logging.INFO)

    logging.getLogger().setLevel(
        logging.DEBUG if level >= 40 else logging.INFO)

    _level = level


def get_log_level_options():
    return [
        { 'label': 'Runtime', 'value': 0  },
        { 'label': 'Low'    , 'value': 10 },
        { 'label': 'High'   , 'value': 20 },
        { 'label': 'All'    , 'value': 50 },
    ]

