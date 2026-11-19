"""Let a bare ``pytest`` run the suite.

The repo root is the plugin itself, so it has an ``__init__.py`` with relative
imports: Hermes loads it as a package. pytest would see that file, treat the
root as a package and import ``__init__.py`` on its own, which fails. The
tests load the plugin the way Hermes does (see tests/test_plugin.py), so here
the root is collected as a plain directory instead.

pytest asks the *parent* directory's conftests how to collect a directory, so
this file cannot do that for its own directory directly; it registers a small
plugin, which applies everywhere, from pytest_configure.
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parent


class _PluginRootIsNotATestPackage:
    def pytest_collect_directory(self, path, parent):
        if path == ROOT:
            import pytest

            return pytest.Dir.from_parent(parent, path=path)
        return None

    # Run before pytest's own hook, which would return a Package.
    pytest_collect_directory.tryfirst = True


def pytest_configure(config):
    config.pluginmanager.register(_PluginRootIsNotATestPackage(), "hathor-root-dir")
