"""Local development hostname canonicalization for WebAuthn.

WebAuthn passkeys are configured for the RP ID ``localhost``. Browsers treat
127.0.0.1 and localhost as different origins, and an IP address is not a
portable WebAuthn RP ID. In DEBUG mode, redirect requests made to the IPv4
loopback address to the equivalent localhost URL before Django processes the
request. Production traffic is never redirected by this middleware.
"""
from urllib.parse import urlsplit

from django.conf import settings
from django.http import HttpResponseRedirect


class LocalhostCanonicalHostMiddleware:
    """Redirect local 127.0.0.1 requests to localhost in DEBUG mode only."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if settings.DEBUG:
            try:
                host = request.get_host()
                parsed_host = urlsplit("//{}".format(host))
            except (ValueError, UnicodeError):
                parsed_host = None

            if parsed_host and parsed_host.hostname:
                if parsed_host.hostname.lower().rstrip(".") == "127.0.0.1":
                    port = parsed_host.port
                    port_suffix = ":{}".format(port) if port else ""
                    target = "{}://localhost{}{}".format(
                        request.scheme,
                        port_suffix,
                        request.get_full_path(),
                    )
                    return HttpResponseRedirect(target)

        return self.get_response(request)
