"""
Helpers to get data locations for the current platform.
"""

# built-in
import os
from functools import lru_cache
from pathlib import Path

# app
from ..constants import IS_WINDOWS
from ..imports import lazy_import


appdirs = lazy_import('appdirs')  # pylint: disable=invalid-name


@lru_cache(maxsize=2)
def get_data_dir(app: str = 'dephell') -> Path:
    """Return base directory for persistent dephell data like jails."""
    # unix and Windows from environment
    envvar = 'LOCALAPPDATA' if IS_WINDOWS else 'XDG_DATA_HOME'
    if envvar in os.environ:
        path = Path(os.environ[envvar])
        if path.exists():
            return path / app

    # unix default
    path = Path.home() / '.local' / 'share'
    if path.exists():
        return path / app

    # mac os x
    path = Path.home() / 'Library' / 'Application Support'
    if path.exists():
        return path / app

    return Path(appdirs.user_data_dir(app))


@lru_cache(maxsize=2)
def get_cache_dir(app: str = 'dephell') -> Path:
    """Return basedir for transient / cached data that is OK to be lost."""
    # unix and Windows from environment
    envvar = 'TEMP' if IS_WINDOWS else 'XDG_CACHE_HOME'
    if envvar in os.environ:
        path = Path(os.environ[envvar])
        if path.exists():
            return path / app

    # unix default
    path = Path.home() / '.cache'
    if path.exists():
        return path / app

    # mac os x
    path = Path.home() / 'Library' / 'Caches'
    if path.exists():
        return path / app

    return get_data_dir(app=app) / 'cache'
