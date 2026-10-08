import hashlib
import io
import threading
import pytest
from core.app_update import (Version, select_release, package_for, download, check,
                             UpdateError, Cancelled, safe_url, REPOSITORY, MANIFEST)


def release(tag='v0.28.0-editor-preview', preview=True):
    payload = b'package fixture'
    name = 'RawBaker-Editor-0.28-Windows-x64.zip'
    asset = lambda n, size: dict(name=n, size=size, browser_download_url=f'https://github.com/{REPOSITORY}/releases/download/{tag}/{n}')
    r = dict(tag_name=tag, prerelease=preview, draft=False, assets=[asset(name, len(payload)), asset(MANIFEST, 100)])
    m = dict(schema=1, app_id='com.vulcanhub.rawbaker', tag=tag, version=tag[1:], commit='a'*40,
             channel='preview' if preview else 'stable', packages=[dict(os='windows', arch='x64', kind='portable-zip',
             name=name, size=len(payload), sha256=hashlib.sha256(payload).hexdigest())])
    return r, m, payload


@pytest.mark.parametrize('a,b', [('0.9','0.10'), ('1.0.0-beta.2','1.0.0-beta.10'), ('1.0.0-beta','1.0.0'), ('0.25-editor-preview','0.27.0-editor-preview')])
def test_semantic_versions(a,b):
    assert Version(a) < Version(b)


def test_channels_and_no_downgrade():
    r,_,_=release()
    assert select_release([r], '0.27.0-editor-preview', True) == r
    assert select_release([r], '0.27.0', False) is None
    assert select_release([r], '0.29.0', True) is None
    assert select_release([r], '0.28.0-editor-preview', True) is None
    r['prerelease']=False
    assert select_release([r], '0.27.0', False) is None


def test_exact_package_and_manifest():
    r,m,_=release()
    assert package_for(r,m,('windows','x64','portable-zip')).preview
    for target in [('darwin','arm64','portable-zip'),('windows','arm64','portable-zip'),('windows','x64','source')]:
        with pytest.raises(UpdateError,match='package'): package_for(r,m,target)
    m['commit']='main'
    with pytest.raises(UpdateError,match='metadata'): package_for(r,m,('windows','x64','portable-zip'))


@pytest.mark.parametrize('field,value', [('name','../evil.zip'),('sha256','xyz'),('size',-1)])
def test_rejects_malformed_package(field,value):
    r,m,_=release();m['packages'][0][field]=value
    with pytest.raises(UpdateError): package_for(r,m,('windows','x64','portable-zip'))


@pytest.mark.parametrize('url', ['http://github.com/file','https://evil.example/file','https://github.com@evil.example/x','file:///tmp/a','https://github.com:444/x'])
def test_rejects_unsafe_urls(url):
    with pytest.raises(UpdateError): safe_url(url)


def test_verified_download_cancel_and_retry(tmp_path):
    r,m,data=release();p=package_for(r,m,('windows','x64','portable-zip'));event=threading.Event()
    for payload in (b'bad',data+b'extra'):
        with pytest.raises(UpdateError,match='hash'): download(p,tmp_path,event,lambda *a:None,lambda u:io.BytesIO(payload))
    assert list(tmp_path.iterdir())==[]
    def cancel(*a): event.set()
    with pytest.raises(Cancelled): download(p,tmp_path,event,cancel,lambda u:io.BytesIO(data))
    assert list(tmp_path.iterdir())==[]
    event.clear()
    path=download(p,tmp_path,event,lambda *a:None,lambda u:io.BytesIO(data))
    assert path.read_bytes()==data


def test_feed_and_missing_metadata():
    r,m,_=release()
    assert check('0.27.0-editor-preview',True,('windows','x64','portable-zip'),lambda u:m if u.endswith(MANIFEST) else [r]).version=='0.28.0-editor-preview'
    r['assets']=[]
    with pytest.raises(UpdateError,match='package'):check('0.27.0-editor-preview',True,('windows','x64','portable-zip'),lambda u:[r])
    with pytest.raises(UpdateError,match='empty'):check('0.27',True,('windows','x64','portable-zip'),lambda u:[])


def test_duplicate_check_and_disabled_apply():
    # No installation path can terminate the app or modify working documents.
    from ui.app_update import UpdateController
    c=UpdateController();runs=[];c._run=lambda *a:runs.append(a)
    c.check();c.check()
    assert c.state=='checking' and len(runs)==1
    assert c.apply() is False
