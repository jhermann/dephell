# built-in
import asyncio
import re
from collections import defaultdict
from copy import deepcopy

# external
import attr
from cached_property import cached_property
from packaging.utils import canonicalize_name

# app
from ..exceptions import MergeError
from ..links import parse_link
from ..repositories import get_repo, GitRepo
from .constraint import Constraint
from .group import Group
from .git_specifier import GitSpecifier


loop = asyncio.get_event_loop()

# regex for names generated by pipenv
rex_hash = re.compile(r'[a-f0-9]{7}')


@attr.s()
class Dependency:
    raw_name = attr.ib()
    constraint = attr.ib(repr=False)
    repo = attr.ib(repr=False)
    link = attr.ib(default=None, repr=False)

    # flags
    applied = attr.ib(default=False, repr=False)

    # optional info
    description = attr.ib(default='', repr=False)       # summary
    authors = attr.ib(factory=tuple, repr=False)        # author, author_email, maintainer, maintainer_email
    links = attr.ib(factory=dict, repr=False)           # project_url, project_urls, package_url
    classifiers = attr.ib(factory=tuple, repr=False)    # classifiers

    # info from requirements file
    extras = attr.ib(factory=set, repr=False)
    # https://github.com/pypa/packaging/blob/master/packaging/markers.py
    marker = attr.ib(default=None, repr=False)

    # constructors

    @classmethod
    def from_requirement(cls, source, req, url=None):
        # https://github.com/pypa/packaging/blob/master/packaging/requirements.py
        link = parse_link(url or req.url)
        # make constraint
        constraint = Constraint(source, req.specifier)
        if isinstance(link, GitRepo):
            constraint._specs[source.name] = GitSpecifier()
        return cls(
            raw_name=req.name,
            constraint=constraint,
            repo=get_repo(link),
            link=link,
            extras=req.extras,
            marker=req.marker,
        )

    @classmethod
    def from_params(cls, *, raw_name, constraint, url=None, source=None, repo=None, **kwargs):
        # make link
        link = parse_link(url)
        if link and link.name and rex_hash.fullmatch(raw_name):
            raw_name = link.name
        # make constraint
        if source:
            constraint = Constraint(source, constraint)
        if isinstance(link, GitRepo):
            constraint._specs[source.name] = GitSpecifier()
        # make repo
        if repo is None:
            repo = get_repo(link)
        return cls(
            link=link,
            repo=repo,
            raw_name=raw_name,
            constraint=constraint,
            **kwargs,
        )

    # properties

    @cached_property
    def name(self) -> str:
        return canonicalize_name(self.raw_name)

    @cached_property
    def all_releases(self) -> tuple:
        return self.repo.get_releases(self)

    async def _fetch_releases_deps(self):
        tasks = []
        releases = []
        for release in self.all_releases:
            if 'dependencies' not in release.__dict__:
                task = asyncio.ensure_future(self.repo.get_dependencies(
                    release.name,
                    release.version,
                ))
                tasks.append(task)
                releases.append(release)
        responses = await asyncio.gather(*tasks)
        for release, response in zip(releases, responses):
            release.dependencies = response

    @cached_property
    def groups(self) -> tuple:
        # fetch releases
        future = asyncio.ensure_future(self._fetch_releases_deps())
        loop.run_until_complete(future)

        # group releases by their dependencies
        groups = defaultdict(set)
        for release in self.all_releases:
            key = '|'.join(sorted(map(str, release.dependencies)))
            groups[key].add(release)

        # sort groups by latest release
        groups = sorted(groups.values(), key=max, reverse=True)

        # convert every group to Group object
        groups = tuple(
            Group(releases=releases, number=number)
            for number, releases in enumerate(groups)
        )

        self._actualize_groups(groups=groups)
        return groups

    @cached_property
    def group(self):
        """By first access choose and save best group
        """
        for group in self.groups:
            if not group.empty:
                return group

    @property
    def dependencies(self) -> tuple:
        constructor = self.__class__.from_requirement
        return tuple(constructor(self, req) for req in self.group.dependencies)

    @property
    def locked(self):
        return 'group' in self.__dict__

    @property
    def compat(self):
        # if group has already choosed
        if self.locked:
            return not self.group.empty
        # if group hasn't choosed
        for group in self.groups:
            if not group.empty:
                return True
        return False

    @property
    def used(self) -> bool:
        """True if some deps in graph depends on this dep.
        """
        return not self.constraint.empty

    # methods

    def unlock(self):
        del self.__dict__['group']
        # if 'dependencies' in self.__dict__:
        #     del self.__dict__['dependencies']

    def merge(self, dep):
        # some checks when we merge two git based dep
        if isinstance(self.link, GitRepo) and isinstance(dep.link, GitRepo):
            if self.link.rev and dep.link.rev and self.link.rev != dep.link.rev:
                raise MergeError('links point to different revisions')
            if self.link.server != dep.link.server:
                raise MergeError('links point to different servers')
            ...

        # if ...
        # .. 1. we don't use repo in self,
        # .. 2. it's a git repo,
        # .. 3. dep has non-git repo,
        # .. 4. self has no rev,
        # then prefer non-git repo, because it's more accurate and fast.
        if isinstance(self.link, GitRepo) and not isinstance(dep.link, GitRepo):
            if not self.link.rev:
                if 'groups' not in self.__dict__:
                    self.repo = dep.repo

        if not isinstance(self.link, GitRepo) and isinstance(dep.link, GitRepo):
            self.link = dep.link
            self.repo = dep.repo

        self.constraint.merge(dep.constraint)
        self._actualize_groups(force=True)

    def unapply(self, name: str):
        self.constraint.unapply(name)
        self._actualize_groups(force=True)
        if self.locked:
            self.unlock()

    def copy(self):
        obj = deepcopy(self)
        obj.constraint = self.constraint.copy()
        if obj.locked:
            obj.unlock()
        return obj

    def _actualize_groups(self, *, force: bool=False, groups=None) -> bool:
        if not groups:
            if not force and 'groups' not in self.__dict__:
                return False
            groups = self.groups

        filtrate = self.constraint.filter
        for group in groups:
            group.releases = filtrate(group.all_releases)
        return True
