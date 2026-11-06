"""Per-request proxy discovery with explicit platform policies."""
import sys
import urllib.request

from infrastructure.proxy import macos, windows
from infrastructure.proxy.windows import WindowsSystemProxyHandler


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def discover_proxies():
    if sys.platform == "win32":
        return windows.discover_proxies()
    return macos.discover_proxies()


class FreshProxyOpener:
    """Discover proxies for every request, without sharing mutable handlers.

    urllib's default ProxyHandler snapshots macOS system proxies at creation.
    A desktop service can outlive VPN/proxy changes and sleep/wake cycles.
    Rebuilding locally also keeps concurrent requests independent. Do not
    replay failed POSTs: the upstream may already have accepted a generation.
    """

    def __init__(self, upstream_proxy=None):
        self.upstream_proxy = upstream_proxy

    def open(self, request, timeout=120):
        windows = sys.platform == 'win32'
        proxies = ({'http': self.upstream_proxy, 'https': self.upstream_proxy}
                   if self.upstream_proxy and not windows else discover_proxies())
        # Record only presence, never proxy URLs, credentials or bypass lists.
        request.connected_proxy_configured = bool(proxies.get(request.type))
        handler = WindowsSystemProxyHandler if windows else urllib.request.ProxyHandler
        opener = urllib.request.build_opener(handler(proxies), NoRedirect())
        return opener.open(request, timeout=timeout)
