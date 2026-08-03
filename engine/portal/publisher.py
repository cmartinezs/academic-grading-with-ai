"""C4 publisher registry.

Maps ``publisherType`` (or the hosting profile mode) to a publisher adapter.
Unknown publisher types fail closed.
"""

from __future__ import annotations

from .errors import PublisherUnavailableError
from .hosting.base import AbstractPublisher, PreflightError
from .hosting.local_static import LocalStaticPublisher
from .hosting.fake_authenticated import FakeAuthenticatedPublisher

_REGISTRY = {
    "local-static": LocalStaticPublisher(),
    "fake-authenticated": FakeAuthenticatedPublisher(),
}


def get_publisher(publisher_type: str) -> AbstractPublisher:
    try:
        return _REGISTRY[publisher_type]
    except KeyError:
        raise PublisherUnavailableError(f"Unsupported publisher type: {publisher_type!r}")


def publisher_for_mode(portal_mode: str) -> AbstractPublisher:
    if portal_mode == "static-encrypted":
        return get_publisher("local-static")
    if portal_mode == "authenticated":
        return get_publisher("fake-authenticated")
    raise PublisherUnavailableError(f"Unsupported portal mode: {portal_mode!r}")
