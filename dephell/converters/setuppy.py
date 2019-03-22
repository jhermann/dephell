# built-in
from collections import defaultdict
from distutils.core import run_setup
from itertools import chain
from pathlib import Path
from typing import Optional

# project
from dephell_specifier import RangeSpecifier
from packaging.requirements import Requirement
from yapf.yapflib.style import CreateGoogleStyle
from yapf.yapflib.yapf_api import FormatCode

# app
from ..controllers import DependencyMaker, Readme
from ..models import Author, EntryPoint, RootDependency
from ..utils import chdir
from .base import BaseConverter


TEMPLATE = """
# -*- coding: utf-8 -*-

# DO NOT EDIT THIS FILE!
# This file has been autogenerated by dephell <3
# https://github.com/orsinium/dephell

try:
    from setuptools import setup
except ImportError:
    from distutils.core import setup

{readme}

setup(
    long_description=readme,
    {kwargs},
)
"""


class SetupPyConverter(BaseConverter):
    lock = False

    def can_parse(self, path: Path, content: Optional[str] = None) -> bool:
        if isinstance(path, str):
            path = Path(path)
        if path.name == 'setup.py':
            return True
        if not content:
            return False
        if 'setuptools' not in content and 'distutils' not in content:
            return False
        return ('setup(' in content)

    @classmethod
    def load(cls, path) -> RootDependency:
        path = Path(str(path))
        with chdir(path.parent):
            info = run_setup(path.name)

        root = RootDependency(
            raw_name=cls._get(info, 'name'),
            version=cls._get(info, 'version') or '0.0.0',

            description=cls._get(info, 'description'),
            license=cls._get(info, 'license'),

            keywords=cls._get_list(info, 'keywords'),
            classifiers=cls._get_list(info, 'classifiers'),
            platforms=cls._get_list(info, 'platforms'),

            python=RangeSpecifier(cls._get(info, 'python_requires')),
            readme=Readme.from_code(path=path),
        )

        # links
        for key, name in (('home', 'url'), ('download', 'download_url')):
            link = cls._get(info, name)
            if link:
                root.links[key] = link

        # authors
        for name in ('author', 'maintainer'):
            author = cls._get(info, name)
            if author:
                root.authors += (
                    Author(name=author, mail=cls._get(info, name + '_email')),
                )

        # entrypoints
        entrypoints = []
        for group, content in getattr(info, 'entry_points', {}).items():
            for entrypoint in content:
                entrypoints.append(EntryPoint.parse(text=entrypoint, group=group))
        root.entrypoints = tuple(entrypoints)

        # dependencies
        reqs = chain(
            cls._get_list(info, 'requires'),
            cls._get_list(info, 'install_requires'),
        )
        deps = []
        for req in reqs:
            req = Requirement(req)
            deps.extend(DependencyMaker.from_requirement(source=root, req=req))
        root.attach_dependencies(deps)

        # extras
        for extra, reqs in getattr(info, 'extras_require', {}).items():
            for req in reqs:
                req = Requirement(req)
                deps = DependencyMaker.from_requirement(source=root, req=req)
                for dep in deps:
                    dep.envs = {extra}
                root.attach_dependencies(deps)

        return root

    def dumps(self, reqs, project: RootDependency, content=None) -> str:
        """
        https://setuptools.readthedocs.io/en/latest/setuptools.html#metadata
        """
        content = []
        content.append(('name', project.raw_name))
        content.append(('version', project.version))
        if project.description:
            content.append(('description', project.description))
        if project.python:
            content.append(('python_requires', str(project.python)))

        # links
        fields = (
            ('home', 'url'),
            ('download', 'download_url'),
        )
        for key, name in fields:
            if key in project.links:
                content.append((name, project.links[key]))
        if project.links:
            content.append(('project_urls', project.links))

        # authors
        if project.authors:
            author = project.authors[0]
            content.append(('author', author.name))
            if author.mail:
                content.append(('author_email', author.mail))
        if len(project.authors) > 1:
            author = project.authors[1]
            content.append(('maintainer', author.name))
            if author.mail:
                content.append(('maintainer_email', author.mail))

        if project.license:
            content.append(('license', project.license))
        if project.keywords:
            content.append(('keywords', ' '.join(project.keywords)))
        if project.classifiers:
            content.append(('classifiers', project.classifiers))
        if project.platforms:
            content.append(('platforms', project.platforms))
        if project.entrypoints:
            entrypoints = defaultdict(list)
            for entrypoint in project.entrypoints:
                entrypoints[entrypoint.group].append(str(entrypoint))
            content.append(('entry_points', dict(entrypoints)))

        # packages, package_data
        content.append(('packages', sorted(str(p) for p in project.package.packages)))
        data = defaultdict(list)
        for rule in project.package.data:
            data[rule.module].append(rule.relative)
        data = {package: sorted(paths) for package, paths in data.items()}
        content.append(('package_data', data))

        reqs_list = [self._format_req(req=req) for req in reqs]
        content.append(('install_requires', reqs_list))

        extras = defaultdict(list)
        for req in reqs:
            formatted = self._format_req(req=req)
            for env in req.envs:
                extras[env].append(formatted)
        if extras:
            content.append(('extras_require', dict(extras)))

        if project.readme is not None:
            readme = project.readme.to_rst().as_code()
        else:
            readme = "readme = ''"

        content = ',\n    '.join('{}={!r}'.format(name, value) for name, value in content)
        content = TEMPLATE.format(kwargs=content, readme=readme)

        content, _changed = FormatCode(content, style_config=CreateGoogleStyle())
        return content

    # private methods

    @staticmethod
    def _get(msg, name: str) -> str:
        value = getattr(msg.metadata, name, None)
        if not value:
            value = getattr(msg, name, None)
        if not value:
            return ''
        if value == 'UNKNOWN':
            return ''
        return value.strip()

    @staticmethod
    def _get_list(msg, name: str) -> tuple:
        values = getattr(msg, name, None)
        if not values:
            return ()
        return tuple(value for value in values if value != 'UNKNOWN' and value.strip())

    @staticmethod
    def _format_req(req):
        line = req.name
        if req.extras:
            line += '[{extras}]'.format(extras=','.join(req.extras))
        if req.version:
            line += req.version
        if req.markers:
            line += '; ' + req.markers
        return line
