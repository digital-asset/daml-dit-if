from typing import Optional

from aiohttp.web import Request

from .jwt import JWTClaims

from .log import LOG

from .config import Configuration


DABL_JWT_LEDGER_CLAIMS = "DABL_JWT_LEDGER_CLAIMS"


def get_configured_integration_ledger_claims(
        config: 'Configuration', claims: "JWTClaims") -> "Optional[JWTClaims]":

    """
    Given an IF configuration and a dict of claims from a DAML Ledger
    JWT, return the ledger claims from that token, if and only if they
    correspond to the configured ledger ID. Tokens with claims against
    other ledger ID's have no power here.
    """

    ledger_claims = claims.get('https://daml.com/ledger-api')

    LOG.debug('ledger_claims: %r', ledger_claims)

    if ledger_claims is None:
        return None

    claimed_ledger_id = ledger_claims.get('ledgerId', 'missing-ledger-id-claim')

    if claimed_ledger_id != config.ledger_id:
        LOG.debug(f'Ledger ID mismatch in claims: {claimed_ledger_id} != {config.ledger_id}')
        return None

    return ledger_claims


def is_integration_party_ledger_claim(config: "Configuration", ledger_claims: "JWTClaims") -> bool:
    """
    Given an IF configuration and a dict of DAML ledger claims from
    a token, determine if the configured integration party is included
    in the ledger claims. For a token to claim the integration party, the
    token must claim the party in both the 'readAs' and 'actAs' sections.
    """
    read_as_parties = ledger_claims.get('readAs', [])
    act_as_parties = ledger_claims.get('actAs', [])

    party = config.run_as_party

    if party is None:
        return False

    return party in read_as_parties and party in act_as_parties


def get_request_claims(request: 'Request'):
    """
    Return the DAML ledger claims for the request's JWT token. If there
    are no such claims, or the token has not been extracted (as in a
    public endpoint), this returns None.
    """
    return request.get(DABL_JWT_LEDGER_CLAIMS, None)


def get_request_parties(request: 'Request'):
    """
    Get the DAML ledger parties identified in the current request's JWT
    token. The parties returned by this function are the parties that
    appear in _both_ the 'readAs' and 'actAs' ledger claims.  If there is
    no such party, or if no token has been extracted from the request (as
    in a public endpoint), this returns the empty list.
    """
    ledger_claims = get_request_claims(request)

    if ledger_claims is None:
        return []

    read_as_parties = ledger_claims.get('readAs', [])
    act_as_parties = ledger_claims.get('actAs', [])

    return list(set(read_as_parties).intersection(set(act_as_parties)))


def get_single_request_party(request: 'Request'):
    """
    Returns the single DAML ledger party identified in the current request's
    JWT. For a party to be returned by this function, it must appear in _both_
    the  'readAs' and 'actAs' ledger claims. If there is no such party, or if no
    JWT has been extracted from the request (as in a public endpoint), this
    returns None. If there are multiple such parties identified in the JWT,
    it is an error, and an exception is raised.
    """
    parties = get_request_parties(request) or []

    if parties:
        if len(parties) == 1:
            return parties[0]
        else:
            raise Exception(f'Only one ledger party expected in token: {parties}')

    return None
