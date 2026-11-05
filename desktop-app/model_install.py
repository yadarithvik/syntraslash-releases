"""Resumable, checksum-pinned model installation without an Ollama dependency."""
import hashlib
from contextlib import contextmanager
import json
import os
from pathlib import Path
import re
import shutil
import threading
import urllib.request

MODEL_NAME = 'syntra-max-aperion.gguf'
MODEL_BYTES = 8988110688
MODEL_SHA256 = '2049f5674b1e92b4464e5729975c9689fcfbf0b0e4443ccf10b5339f370f9a54'
MODEL_URL = 'https://registry.ollama.ai/v2/library/qwen2.5/blobs/sha256:' + MODEL_SHA256


class InstallPaused(Exception):
    pass


class ModelInstaller:
    def __init__(self, directory=None, *, url=MODEL_URL, size=MODEL_BYTES,
                 digest=MODEL_SHA256, opener=urllib.request.urlopen):
        self.directory = Path(directory) if directory else Path(os.environ.get(
            'LOCALAPPDATA', str(Path.home()))) / 'SyntraSlashes' / 'models'
        self.path = self.directory / MODEL_NAME
        self.partial = self.directory / (MODEL_NAME + '.part')
        self.url, self.size, self.digest, self.opener = url, size, digest, opener
        self.cancel = threading.Event()

    def _check_cancel(self):
        if self.cancel.is_set():
            raise InstallPaused('Download paused. Your progress has been saved.')

    @contextmanager
    def _install_lock(self):
        self.directory.mkdir(parents=True, exist_ok=True)
        with (self.directory / '.install.lock').open('a+b') as lock:
            lock.seek(0, 2)
            if lock.tell() == 0:
                lock.write(b'0')
                lock.flush()
            lock.seek(0)
            try:
                if os.name == 'nt':
                    import msvcrt
                    msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as error:
                raise RuntimeError('Another Syntra window is installing the model. Wait for it to finish or close that window.') from error
            try:
                yield
            finally:
                lock.seek(0)
                if os.name == 'nt':
                    msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(lock.fileno(), fcntl.LOCK_UN)

    def verify(self, path, progress=lambda *_: None):
        path = Path(path)
        if not path.is_file() or path.stat().st_size != self.size:
            raise ValueError('The model is incomplete or is not the Syntra Max Aperion model.')
        digest = hashlib.sha256()
        done = 0
        with path.open('rb') as source:
            if source.read(4) != b'GGUF':
                raise ValueError('This is not a GGUF model file.')
            source.seek(0)
            while block := source.read(8 * 1024 * 1024):
                self._check_cancel()
                digest.update(block)
                done += len(block)
                progress('verifying', done, self.size)
        if digest.hexdigest() != self.digest:
            raise ValueError('Model checksum failed. Please download the model again.')
        return path

    def installed(self):
        if not self.path.is_file() or self.path.stat().st_size != self.size:
            return None
        try:
            marker = json.loads(self.path.with_suffix('.verified.json').read_text())
            stat = self.path.stat()
            if marker == {'sha256': self.digest, 'bytes': stat.st_size,
                          'mtime_ns': stat.st_mtime_ns}:
                return self.path
        except (OSError, ValueError):
            pass
        return None

    def _mark_verified(self):
        stat = self.path.stat()
        marker = self.path.with_suffix('.verified.json')
        temporary = marker.with_suffix('.tmp')
        temporary.write_text(json.dumps({'sha256': self.digest, 'bytes': stat.st_size,
                                         'mtime_ns': stat.st_mtime_ns}), encoding='utf-8')
        temporary.replace(marker)

    def download(self, progress=lambda *_: None):
        with self._install_lock():
            if self.installed():
                return self.path
            return self._download(progress)

    def _download(self, progress):
        self.directory.mkdir(parents=True, exist_ok=True)
        offset = self.partial.stat().st_size if self.partial.exists() else 0
        if offset > self.size:
            self.partial.unlink()
            offset = 0
        if shutil.disk_usage(self.directory).free < self.size - offset + 256 * 1024 * 1024:
            raise OSError('Not enough disk space. Free at least 10 GB and try again.')
        self._check_cancel()
        if offset < self.size:
            headers = {'User-Agent': 'Syntra-Slash/1.0', 'Accept-Encoding': 'identity'}
            if offset:
                headers['Range'] = f'bytes={offset}-'
            request = urllib.request.Request(self.url, headers=headers)
            progress('connecting', offset, self.size)
            with self.opener(request, timeout=30) as response:
                if response.status == 206:
                    match = re.fullmatch(r'bytes (\d+)-(\d+)/(\d+)',
                                         response.headers.get('Content-Range', ''))
                    if (not match or int(match[1]) != offset or
                            int(match[2]) != self.size - 1 or int(match[3]) != self.size):
                        raise ValueError('The server returned an invalid download range. Please retry.')
                elif response.status == 200:
                    offset = 0  # Server ignored Range: safely restart, never append duplicates.
                else:
                    raise OSError(f'Download server returned HTTP {response.status}. Please retry.')
                length = response.headers.get('Content-Length')
                if length is not None and int(length) != self.size - offset:
                    raise ValueError('The server returned an unexpected model size.')
                if shutil.disk_usage(self.directory).free < self.size - offset + 256 * 1024 * 1024:
                    raise OSError('Not enough disk space to restart the download. Free 10 GB.')
                with self.partial.open('ab' if offset else 'wb') as target:
                    progress('downloading', offset, self.size)
                    while True:
                        self._check_cancel()
                        block = response.read(1024 * 1024)
                        if not block:
                            break
                        if offset + len(block) > self.size:
                            raise ValueError('Download exceeded the expected model size.')
                        target.write(block)
                        offset += len(block)
                        progress('downloading', offset, self.size)
            if offset != self.size:
                raise OSError('Download interrupted. Choose Resume to continue from the saved progress.')
        try:
            self.verify(self.partial, progress)
        except ValueError:
            self.partial.unlink(missing_ok=True)  # Do not keep a corrupt, completed download.
            raise
        self._check_cancel()
        self.partial.replace(self.path)
        self._mark_verified()
        return self.path

    def import_model(self, source, progress=lambda *_: None):
        with self._install_lock():
            return self._import_model(source, progress)

    def _import_model(self, source, progress):
        source = self.verify(source, progress)
        self.directory.mkdir(parents=True, exist_ok=True)
        if source.resolve() == self.path.resolve():
            self._mark_verified()
            return self.path
        if shutil.disk_usage(self.directory).free < self.size + 256 * 1024 * 1024:
            raise OSError('Not enough space to import this model. Free at least 10 GB.')
        # Keep any resumable network download intact if importing is interrupted.
        temporary = self.path.with_suffix('.importing')
        try:
            done = 0
            with source.open('rb') as src, temporary.open('wb') as dst:
                while block := src.read(8 * 1024 * 1024):
                    self._check_cancel()
                    dst.write(block)
                    done += len(block)
                    progress('importing', done, self.size)
            self.verify(temporary, progress)
            temporary.replace(self.path)
            self._mark_verified()
            self.partial.unlink(missing_ok=True)
        finally:
            temporary.unlink(missing_ok=True)
        return self.path
