"""Public release discovery and verified downloads. Never installs or executes files."""
from dataclasses import dataclass
from functools import total_ordering
import hashlib
import json
from pathlib import Path
import re
import tempfile
import threading
from urllib.parse import urlsplit, quote
from urllib.request import Request, build_opener, HTTPRedirectHandler

REPOSITORY = 'VULCAN-HUB/RawBaker'
API = f'https://api.github.com/repos/{REPOSITORY}/releases'
MANIFEST = 'rawbaker-update-v1.json'


class UpdateError(Exception):
    pass


class Cancelled(UpdateError):
    pass


@total_ordering
class Version:
    def __init__(self, text):
        # Existing Editor tags used two numeric components.
        m = re.fullmatch(r'v?(0|[1-9]\d*)\.(0|[1-9]\d*)(?:\.(0|[1-9]\d*))?(?:-([0-9A-Za-z.-]+))?(?:\+[0-9A-Za-z.-]+)?', text)
        if not m:
            raise UpdateError('metadata')
        self.base = tuple(int(x or 0) for x in m.group(1, 2, 3))
        pre = m.group(4)
        parts = pre.split('.') if pre else []
        if any(not p or (p.isdigit() and len(p) > 1 and p[0] == '0') for p in parts):
            raise UpdateError('metadata')
        self.pre = tuple((0, int(p)) if p.isdigit() else (1, p) for p in parts)

    def key(self):
        return self.base, not bool(self.pre), self.pre

    def __eq__(self, other):
        return isinstance(other, Version) and self.key() == other.key()

    def __lt__(self, other):
        return self.key() < other.key()


def safe_url(url):
    p = urlsplit(url)
    if (p.scheme != 'https' or p.username or p.password or p.port not in (None, 443)
            or p.hostname not in ('api.github.com', 'github.com', 'release-assets.githubusercontent.com', 'objects.githubusercontent.com')):
        raise UpdateError('origin')
    return url


class HTTPSRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return super().redirect_request(req, fp, code, msg, headers, safe_url(newurl))


def open_url(url):
    return build_opener(HTTPSRedirect()).open(Request(safe_url(url), headers={
        'User-Agent': 'RawBaker-update', 'Accept': 'application/vnd.github+json'
    }), timeout=20)


def read_json(url, opener=open_url):
    with opener(url) as response:
        raw = response.read(2_000_001)
    if len(raw) > 2_000_000:
        raise UpdateError('metadata')
    try:
        return json.loads(raw)
    except (ValueError, UnicodeError) as exc:
        raise UpdateError('metadata') from exc


def asset_url(release, name):
    matches = [a for a in release.get('assets', []) if a.get('name') == name]
    if len(matches) != 1:
        raise UpdateError('package')
    asset = matches[0]
    expected = f'https://github.com/{REPOSITORY}/releases/download/{quote(release["tag_name"], safe="")}/{quote(name, safe="")}'
    if asset.get('browser_download_url') != expected:
        raise UpdateError('origin')
    return expected


@dataclass(frozen=True)
class Package:
    version: str
    name: str
    url: str
    sha256: str
    size: int
    commit: str
    preview: bool


def select_release(releases, current, beta):
    if not isinstance(releases, list):
        raise UpdateError('metadata')
    candidates = []
    for release in releases:
        if not isinstance(release, dict):
            raise UpdateError('metadata')
        if release.get('draft'):
            continue
        try:
            version = Version(release['tag_name'])
        except (KeyError, TypeError, UpdateError):
            continue  # Unrelated historical tags do not become updates.
        if not beta and (release.get('prerelease') or version.pre):
            continue
        if version > Version(current):
            candidates.append((version, release))
    return max(candidates, key=lambda item: item[0])[1] if candidates else None


def package_for(release, manifest, target):
    try:
        if (manifest['schema'] != 1 or manifest['app_id'] != 'com.vulcanhub.rawbaker'
                or manifest['tag'] != release['tag_name']
                or Version(manifest['version']) != Version(release['tag_name'])
                or not re.fullmatch('[0-9a-f]{40}', manifest['commit'])):
            raise UpdateError('metadata')
        preview = bool(release.get('prerelease') or Version(manifest['version']).pre)
        if manifest['channel'] != ('preview' if preview else 'stable'):
            raise UpdateError('metadata')
        matches = [p for p in manifest['packages'] if (p['os'], p['arch'], p['kind']) == target]
        if len(matches) != 1:
            raise UpdateError('package')
        p = matches[0]
        if (not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]*\.zip', p['name'])
                or not re.fullmatch('[0-9a-f]{64}', p['sha256'])
                or type(p['size']) is not int or not 0 < p['size'] <= 2_000_000_000):
            raise UpdateError('metadata')
        url = asset_url(release, p['name'])
        remote = next(a for a in release['assets'] if a['name'] == p['name'])
        if remote['size'] != p['size']:
            raise UpdateError('metadata')
        return Package(manifest['version'], p['name'], url, p['sha256'], p['size'], manifest['commit'], preview)
    except (KeyError, TypeError, ValueError) as exc:
        raise UpdateError('metadata') from exc


def check(current, beta, target, loader=read_json):
    # Paginate instead of incorrectly treating the first page as the entire feed.
    releases = []
    for page in range(1, 11):
        batch = loader(f'{API}?per_page=100&page={page}')
        if not isinstance(batch, list):
            raise UpdateError('metadata')
        releases.extend(batch)
        if len(batch) < 100:
            break
    else:
        raise UpdateError('feed_limit')
    if not releases:
        raise UpdateError('empty')
    release = select_release(releases, current, beta)
    if release is None:
        return None
    manifest = loader(asset_url(release, MANIFEST))
    return package_for(release, manifest, target)


def download(package, cache, cancel, progress, opener=open_url):
    cache = Path(cache)
    cache.mkdir(parents=True, exist_ok=True)
    # One private directory per attempt; never replace user files or old downloads.
    folder = Path(tempfile.mkdtemp(prefix='download-', dir=cache))
    partial = folder / (package.name + '.part')
    final = folder / package.name
    total = 0
    digest = hashlib.sha256()
    try:
        if cancel.is_set():
            raise Cancelled('cancelled')
        with opener(package.url) as response, partial.open('xb') as out:
            while True:
                if cancel.is_set():
                    raise Cancelled('cancelled')
                chunk = response.read(256 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > package.size:
                    raise UpdateError('hash')
                out.write(chunk)
                digest.update(chunk)
                progress(total, package.size)
        if cancel.is_set():
            raise Cancelled('cancelled')
        if total != package.size or digest.hexdigest() != package.sha256:
            raise UpdateError('hash')
        partial.replace(final)
        return final
    except BaseException:
        partial.unlink(missing_ok=True)
        if not any(folder.iterdir()):
            folder.rmdir()
        raise
