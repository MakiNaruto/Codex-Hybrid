"""Preserve urllib environment and native system proxy discovery."""
import urllib.request


def discover_proxies():
    return urllib.request.getproxies()
