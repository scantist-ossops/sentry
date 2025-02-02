__all__ = ["override_options"]

from contextlib import contextmanager
from unittest.mock import patch

from django.test.utils import override_settings

from sentry.utils.types import Any


@contextmanager
def override_options(options):
    """
    A context manager for overriding specific configuration
    Options.
    """
    from django.conf import settings

    from sentry.options import default_manager
    from sentry.options.manager import OptionsManager

    wrapped = default_manager.store.get
    original_lookup = OptionsManager.lookup_key

    def new_get(key, **kwargs):
        try:
            return options[key.name]
        except KeyError:
            return wrapped(key, **kwargs)

    def new_lookup(self: OptionsManager, key):
        if key in options:
            return self.make_key(key, lambda: "", Any, 1 << 0, 0, 0, None)
        else:
            return original_lookup(self, key)

    # Patch options into SENTRY_OPTIONS as well
    new_options = settings.SENTRY_OPTIONS.copy()
    new_options.update(options)
    with override_settings(SENTRY_OPTIONS=new_options):
        with patch.object(default_manager.store, "get", side_effect=new_get), patch(
            "sentry.options.OptionsManager.lookup_key", new=new_lookup
        ):
            yield
