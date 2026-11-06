"""Windows manual system proxy and registry bypass rules."""
import base64
import urllib.parse
import urllib.request


def discover_proxies():
    # Read the current user switch for every request, independently of the environment.
    return urllib.request.getproxies_registry()


class WindowsSystemProxyHandler(urllib.request.ProxyHandler):
    """Use Windows bypass rules too, without consulting inherited NO_PROXY."""

    def proxy_open(self, request, proxy, protocol):
        if request.host and urllib.request.proxy_bypass_registry(request.host):
            return None
        parsed = urllib.parse.urlsplit(proxy if '://' in proxy else 'http://' + proxy)
        if parsed.username and parsed.password:
            credentials = '{}:{}'.format(urllib.parse.unquote(parsed.username),
                                         urllib.parse.unquote(parsed.password))
            encoded = base64.b64encode(credentials.encode()).decode('ascii')
            request.add_header('Proxy-Authorization', 'Basic ' + encoded)
        hostport = urllib.parse.unquote(parsed.netloc.rsplit('@', 1)[-1])
        original_protocol = request.type
        request.set_proxy(hostport, parsed.scheme)
        if original_protocol != parsed.scheme and original_protocol != 'https':
            return self.parent.open(request, timeout=request.timeout)
        return None
