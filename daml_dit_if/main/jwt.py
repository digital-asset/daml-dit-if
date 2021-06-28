from asyncio import shield, sleep
from datetime import timedelta
import json
from typing import TYPE_CHECKING, Any, Collection, Mapping, Optional, Union

from aiohttp import ClientSession

if TYPE_CHECKING:
    from jwcrypto.jwk import JWK

from .log import LOG


DEFAULT_POLL_INTERVAL = timedelta(seconds=10)
IAT_SKEW = timedelta(seconds=15)
MAX_TOKEN_EXPIRY = timedelta(days=1)


JWTClaims = Mapping[str, Any]


class JWTValidator:
    def __init__(self, jwks_urls: "Optional[Union[str, Collection[str]]]" = None):
        from jwcrypto.jwk import JWKSet

        self.jwks_urls = jwks_urls
        self.keys = JWKSet()
        self.session = None  # type: Optional[ClientSession]

    async def poll(self, poll_interval: timedelta = DEFAULT_POLL_INTERVAL):
        """
        Periodically check for new keys. This coroutine will NEVER terminate naturally, so it should
        not be awaited.
        """
        while True:
            await sleep(poll_interval.total_seconds())

            LOG.debug("JWKS poller polling for new keys...")
            await shield(self._load_new_keys())
            LOG.debug("...JWKS poll complete.")

    async def decode_claims(self, token: str) -> "JWTClaims":
        from jwcrypto.jwt import JWT

        LOG.debug("Verifying token: %r", token)
        jwt = JWT(jwt=token)
        key = jwt.token.jose_header["kid"]
        await self.get_key(key)

        jwt = JWT(jwt=token, key=self.keys)
        return json.loads(jwt.claims)

    async def get_key(self, kid: str) -> "Optional[JWK]":
        """
        Retrieve a key for a given ``kid``. If the key could not be found, the keystore is
        refreshed, and if a key is discovered through that process, it is returned. May return
        ``None`` if even after refreshing keys from the remote JWKS source, a key for the given
        ``kid`` could not be found.
        """
        key = self.keys.get_key(kid)
        if key is None:
            await shield(self._load_new_keys())
            key = self.keys.get_key(kid)

        return key

    def export_all_keys(self) -> "str":
        """
        Return a JSON string that formats all public keys currently in the store as JWKS.
        """
        return self.keys.export(private_keys=False)

    async def _load_new_keys(self):
        from jwcrypto.jwk import JWK

        for url in self.jwks_urls:
            try:
                if self.session is None:
                    self.session = ClientSession()

                async with self.session.get(url, allow_redirects=False) as response:
                    jwks_json = await response.json()

                # ``JWKSet.import_keyset`` suffers from a few critical flaws that make it
                # unusable for us:
                #   1) ``import_keyset`` internally adds keys to a set, which is semantically
                #      correct. However, because JWK has no __eq__ or __hash__ implementation,
                #      EVERY key is repeatedly appended to the set rather than duplicates
                #      getting filtered out.
                #   2) The previous point necessitates that we pre-process the data to filter out
                #      keys that we do not wish to add, thereby requiring us to parse the JSON
                #      and read the payload. ``import_keyset`` expects its argument as a serialized
                #      JSON string, which it promptly parses back into a data structure.
                #
                # We process JWKS endpoints ourselves and selectively add keys directly to the
                # implementation. We are NOT reimplementing ``import_keyset``'s functionality of
                # carrying additional non-``keys`` fields into the ``JWKSet`` object. We are
                # generating JWKS data ourselves, and always generate data that contains only the
                # single top-level property of ``keys`` so this has no impact on us.
                jwks_keys = jwks_json.get("keys")
                if jwks_keys is None:
                    LOG.warning(
                        'The JWKS endpoint did not return a "keys" property, so no new '
                        "keys were added. This will be retried"
                    )
                    continue

                existing_kids = {k.key_id for k in self.keys}
                for jwk_dict in jwks_keys:
                    kid = jwk_dict.get("kid")
                    if kid is None:
                        LOG.warning(
                            'The JWKS endpoint contained a key without a "kid" field. '
                            "It will be dropped."
                        )
                    elif kid in existing_kids:
                        LOG.debug(
                            "We already know about kid %s, so the new value will be "
                            "ignored.",
                            kid,
                        )
                    else:
                        jwk = None
                        try:
                            jwk = JWK(**jwk_dict)
                        except Exception:  # noqa
                            LOG.exception(
                                f"The JWK identified by {kid} could not be parsed."
                            )

                        if jwk is not None:
                            try:
                                self.keys.add(jwk)
                            except Exception:  # noqa
                                LOG.exception(
                                    f"The JWK identified by {kid} could not be added."
                                )

            except Exception as ex:  # noqa
                # Do NOT log these with full stack traces because they're actually fairly common,
                # particularly at startup when user-service has yet to start. Merely logging the
                # text of the exception without a scary stack trace is sufficient.
                LOG.warning("Error when checking url %r for new keys: %s", url, ex)

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session is not None:
            await self.session.close()
