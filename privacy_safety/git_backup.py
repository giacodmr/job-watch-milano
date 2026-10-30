"""Authenticated age capsule of all advertised remote Git refs; restore is bare/offline."""
import io
import json
import os
from pathlib import Path
import re
import shutil
import tarfile

from .common import (REPOSITORY, OID, SHA256, SafetyError, canonical, digest, file_digest,
                     git, run, private_parent, temp_private, utc_now)

MAX_ARCHIVE = 2 * 1024**3
AGE_RECIPIENT = re.compile(r'^age1[0-9a-z]{58}$')

def census(remote):
    raw = run(['git', 'ls-remote', '--symref', remote], code='REMOTE_REF_READ_FAILED')
    refs, head, symbolic = {}, None, None
    for line in raw.decode().splitlines():
        value, name = line.split('\t', 1)
        if value.startswith('ref: '):
            if name == 'HEAD': symbolic = value[5:]
        elif name == 'HEAD': head = value
        elif not name.endswith('^{}'):
            if not name.startswith('refs/') or not OID.fullmatch(value):
                raise SafetyError('INVALID_REMOTE_REFS')
            refs[name] = value
    if not refs or not head or not OID.fullmatch(head):
        raise SafetyError('EMPTY_OR_INVALID_REMOTE')
    return {'refs': dict(sorted(refs.items())), 'head': head, 'symbolic_head': symbolic}

def refs_at(root):
    rows = git(root, 'for-each-ref', '--format=%(refname) %(objectname)').decode().splitlines()
    return dict(sorted(row.split(' ', 1) for row in rows))

def inventory(root):
    ids = sorted(set(git(root, 'rev-list', '--objects', '--all', 'HEAD', '--no-object-names').decode().splitlines()))
    if not ids or any(not OID.fullmatch(oid) for oid in ids):
        raise SafetyError('INVALID_OBJECT_INVENTORY')
    return {'count': len(ids), 'sha256': digest(('\n'.join(ids)+'\n').encode())}

def assert_self_contained(root):
    if git(root, 'rev-parse', '--is-shallow-repository').strip() != b'false':
        raise SafetyError('SHALLOW_BACKUP_FORBIDDEN')
    git_dir = Path(git(root, 'rev-parse', '--absolute-git-dir').decode().strip())
    if (git_dir/'objects/info/alternates').exists() or (git_dir/'shallow').exists():
        raise SafetyError('EXTERNAL_OBJECTS_FORBIDDEN')
    config = git(root, 'config', '--local', '--list').decode().lower()
    if 'extensions.partialclone=' in config or '.promisor=true' in config:
        raise SafetyError('EXTERNAL_OBJECTS_FORBIDDEN')
    # External LFS payloads and submodule repositories are outside a Git bundle.
    # Refuse to call such a backup complete instead of silently losing content.
    objects = git(root,'cat-file','--batch-all-objects','--batch-check=%(objectname) %(objecttype) %(objectsize)').decode().splitlines()
    selected = [line.split()[0] for line in objects if line.split()[1]=='tree' or (line.split()[1]=='blob' and int(line.split()[2])<=2048)]
    raw = git(root,'cat-file','--batch',input=('\n'.join(selected)+'\n').encode())
    offset = 0
    for _ in selected:
        end = raw.index(b'\n',offset); header = raw[offset:end].split(); size = int(header[2]); offset = end+1
        data = raw[offset:offset+size]; offset += size+1
        if (header[1]==b'tree' and (b'160000 ' in data or b' .gitmodules\x00' in data)) or (header[1]==b'blob' and data.startswith(b'version https://git-lfs.github.com/spec/v1')):
            raise SafetyError('EXTERNAL_PAYLOAD_BACKUP_UNSUPPORTED')
        if header[1]==b'blob' and b'filter=lfs' in data.replace(b' ',b''):
            raise SafetyError('EXTERNAL_PAYLOAD_BACKUP_UNSUPPORTED')
    git(root, 'fsck', '--full', '--strict', '--no-reflogs', code='GIT_OBJECT_INTEGRITY_FAILED')

def _crypto(binary):
    if not shutil.which(str(binary)):
        raise SafetyError('AGE_REQUIRED')
    run([binary, '--version'], code='AGE_UNAVAILABLE')

def create_backup(remote, output, recipient, *, age='age', repository=REPOSITORY):
    _crypto(age)
    if not AGE_RECIPIENT.fullmatch(recipient):
        raise SafetyError('NATIVE_AGE_RECIPIENT_REQUIRED')
    output = private_parent(output)
    before = census(remote)
    with temp_private() as tmp:
        root = Path(tmp); mirror = root/'mirror.git'
        run(['git', '-c', 'core.hooksPath=/dev/null', '-c', 'init.templateDir=',
             'clone', '--mirror', '--no-local', remote, mirror], code='MIRROR_CLONE_FAILED')
        assert_self_contained(mirror)
        if refs_at(mirror) != before['refs'] or git(mirror, 'rev-parse', 'HEAD').decode().strip() != before['head']:
            raise SafetyError('REMOTE_CHANGED_RETRY')
        bundle = root/'repository.bundle'
        git(mirror, 'bundle', 'create', bundle, '--all', 'HEAD', code='BUNDLE_CREATE_FAILED')
        os.chmod(bundle, 0o600)
        manifest = {'version':1, 'repository':repository, 'captured_at':utc_now(),
                    'scope':'all-advertised-refs-and-HEAD', **before, 'objects':inventory(mirror),
                    'bundle_sha256':file_digest(bundle), 'bundle_bytes':bundle.stat().st_size}
        if bundle.stat().st_size > MAX_ARCHIVE:
            raise SafetyError('BACKUP_SIZE_LIMIT')
        archive = root/'capsule.tar'
        with tarfile.open(archive, 'w') as tar:
            data = canonical(manifest)
            entry = tarfile.TarInfo('manifest.json'); entry.size = len(data); entry.mode = 0o600
            tar.addfile(entry,io.BytesIO(data))
            entry = tarfile.TarInfo('repository.bundle'); entry.size = bundle.stat().st_size; entry.mode = 0o600
            with bundle.open('rb') as handle: tar.addfile(entry,handle)
        os.chmod(archive, 0o600)
        if archive.stat().st_size > MAX_ARCHIVE:
            raise SafetyError('BACKUP_SIZE_LIMIT')
        if census(remote) != before:
            raise SafetyError('REMOTE_CHANGED_RETRY')
        fd = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_NOFOLLOW', 0), 0o600)
        try:
            with os.fdopen(fd, 'wb') as handle:
                run([age, '--encrypt', '--recipient', recipient, archive], stdout=handle, code='BACKUP_ENCRYPTION_FAILED')
                handle.flush(); os.fsync(handle.fileno())
                if handle.tell() > MAX_ARCHIVE: raise SafetyError('BACKUP_SIZE_LIMIT')
        except BaseException:
            output.unlink(missing_ok=True)
            raise
    return {'status':'ENCRYPTED', 'capsule_sha256':file_digest(output), 'refs':len(before['refs']),
            'objects':manifest['objects']['count'], 'bytes':output.stat().st_size,
            'restore_verified':False}

def _unseal(capsule, identity, expected_sha256, root, age, repository):
    _crypto(age)
    capsule, identity = Path(capsule), Path(identity)
    for path in (capsule, identity):
        if path.is_symlink() or not path.is_file() or path.stat().st_mode & 0o077:
            raise SafetyError('PRIVATE_FILE_REQUIRED')
    if capsule.stat().st_size > MAX_ARCHIVE:
        raise SafetyError('BACKUP_SIZE_LIMIT')
    if not SHA256.fullmatch(expected_sha256) or file_digest(capsule) != expected_sha256:
        raise SafetyError('CAPSULE_HASH_MISMATCH')
    archive = root/'decrypted.tar'
    run([age, '--decrypt', '--identity', identity, '--output', archive, capsule], code='BACKUP_DECRYPTION_FAILED')
    os.chmod(archive, 0o600)
    if archive.stat().st_size > MAX_ARCHIVE:
        raise SafetyError('BACKUP_SIZE_LIMIT')
    with tarfile.open(archive, 'r:') as tar:
        entries = tar.getmembers()
        if len(entries) != 2 or {e.name for e in entries} != {'manifest.json','repository.bundle'} or any(not e.isfile() for e in entries):
            raise SafetyError('INVALID_CAPSULE_MEMBERS')
        manifest_entry = tar.getmember('manifest.json')
        if manifest_entry.size > 8*1024*1024:
            raise SafetyError('INVALID_MANIFEST')
        manifest = json.loads(tar.extractfile(manifest_entry).read())
        required = {'version','repository','captured_at','scope','refs','head','symbolic_head','objects','bundle_sha256','bundle_bytes'}
        if set(manifest) != required or manifest['version'] != 1 or manifest['repository'] != repository or manifest['scope'] != 'all-advertised-refs-and-HEAD':
            raise SafetyError('INVALID_MANIFEST')
        if not OID.fullmatch(manifest['head']) or not isinstance(manifest['refs'],dict) or not manifest['refs']:
            raise SafetyError('INVALID_MANIFEST')
        for ref, oid in manifest['refs'].items():
            if not ref.startswith('refs/') or not isinstance(oid,str) or not OID.fullmatch(oid):
                raise SafetyError('INVALID_MANIFEST')
        if manifest['symbolic_head'] is not None and manifest['refs'].get(manifest['symbolic_head']) != manifest['head']:
            raise SafetyError('INVALID_MANIFEST')
        entry = tar.getmember('repository.bundle')
        if entry.size != manifest['bundle_bytes'] or entry.size > MAX_ARCHIVE:
            raise SafetyError('BUNDLE_SIZE_MISMATCH')
        bundle = root/'repository.bundle'
        with bundle.open('xb') as handle:
            os.chmod(bundle, 0o600); shutil.copyfileobj(tar.extractfile(entry), handle)
    if file_digest(bundle) != manifest['bundle_sha256']:
        raise SafetyError('BUNDLE_HASH_MISMATCH')
    return bundle, manifest

def restore_backup(capsule, identity, expected_sha256, target=None, *, age='age', repository=REPOSITORY):
    # Always validate/decrypt/verify in a disposable bare repository first.
    final = private_parent(target) if target else None
    with temp_private() as tmp:
        root = Path(tmp)
        bundle, manifest = _unseal(capsule, identity, expected_sha256, root, age, repository)
        restored = root/'restore.git'
        run(['git', '-c', 'init.templateDir=', 'init', '--bare', restored], code='RESTORE_INIT_FAILED')
        git(restored, 'bundle', 'verify', bundle, code='BUNDLE_NOT_SELF_CONTAINED')
        git(restored, 'fetch', '--no-tags', bundle, '+refs/*:refs/*', code='RESTORE_FETCH_FAILED')
        git(restored, 'fetch', '--no-tags', bundle, 'HEAD', code='RESTORE_HEAD_FAILED')
        if manifest['symbolic_head']:
            git(restored, 'symbolic-ref', 'HEAD', manifest['symbolic_head'])
        else:
            (restored/'HEAD').write_text(manifest['head']+'\n')
        assert_self_contained(restored)
        if refs_at(restored) != manifest['refs'] or inventory(restored) != manifest['objects'] or git(restored, 'rev-parse', 'HEAD').decode().strip() != manifest['head']:
            raise SafetyError('RESTORE_PARITY_FAILED')
        # No origin URL, push configuration, checkout or hooks are restored.
        git(restored, 'config', 'core.hooksPath', '/dev/null')
        if final:
            # Claim the new target exclusively: never replace an existing directory.
            try:
                final.mkdir(mode=0o700)
            except FileExistsError:
                raise SafetyError('OUTPUT_ALREADY_EXISTS') from None
            try:
                shutil.copytree(restored,final,dirs_exist_ok=True)
                final.chmod(0o700)
                git(final, 'fsck', '--full', '--strict', '--no-reflogs', code='PERSISTED_RESTORE_INTEGRITY_FAILED')
                if refs_at(final) != manifest['refs'] or inventory(final) != manifest['objects']:
                    raise SafetyError('PERSISTED_RESTORE_PARITY_FAILED')
            except BaseException:
                shutil.rmtree(final)
                raise
        return {'status':'RESTORE_VERIFIED', 'refs':len(manifest['refs']), 'objects':manifest['objects']['count'],
                'head_sha':manifest['head'], 'persisted':bool(final), 'remote_configured':False}
