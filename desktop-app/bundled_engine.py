"""Start and own Syntra's private, offline llama.cpp inference process."""
import atexit
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request


class BundledEngine:
    def __init__(self, root=None):
        self.root = Path(root) if root else (Path(sys.executable).parent if getattr(sys, 'frozen', False) else Path(__file__).parent)
        self.process = None
        self.log = None
        self.url = None

    def start(self, timeout=180, model_path=None, cancel=None):
        if not (self.root / 'models' / 'syntra-max-aperion.gguf').is_file():
            sibling = self.root / 'Syntra Offline'
            if (sibling / 'models' / 'syntra-max-aperion.gguf').is_file():
                self.root = sibling
        model = Path(model_path) if model_path else self.root / 'models' / 'syntra-max-aperion.gguf'
        if not model.is_file():
            raise RuntimeError('Install Syntra Max Aperion from the model setup screen first.')
        if model.stat().st_size < 1_000_000_000:
            raise RuntimeError('Syntra model file is incomplete. Extract the offline ZIP again.')

        data = Path(os.environ.get('LOCALAPPDATA', str(Path.home()))) / 'SyntraSlashes'
        data.mkdir(parents=True, exist_ok=True)
        self.log = (data / 'bundled-engine.log').open('ab')
        atexit.register(self.stop)
        errors = []
        for backend in ('vulkan', 'cpu'):
            executable = self.root / 'engine' / backend / 'llama-server.exe'
            if not executable.is_file():
                errors.append(f'{backend}: runtime missing')
                continue
            with socket.socket() as sock:
                sock.bind(('127.0.0.1', 0))
                port = sock.getsockname()[1]
            self.url = f'http://127.0.0.1:{port}'
            args = [str(executable), '--model', str(model), '--alias', 'syntra-max-aperion',
                    '--host', '127.0.0.1', '--port', str(port), '--ctx-size', '16384',
                    '--jinja', '--no-webui', '--parallel', '1']
            if backend == 'cpu':
                args += ['--gpu-layers', '0']
            environment = os.environ.copy()
            self.log.write(f'\nStarting Syntra {backend} backend\n'.encode())
            self.log.flush()
            self.process = subprocess.Popen(args, cwd=str(executable.parent), env=environment,
                                            stdin=subprocess.DEVNULL, stdout=self.log, stderr=self.log,
                                            creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                if cancel is not None and cancel.is_set():
                    self.stop()
                    raise RuntimeError('Model loading was cancelled.')
                if self.process.poll() is not None:
                    errors.append(f'{backend}: exited with code {self.process.returncode}')
                    break
                try:
                    with urllib.request.urlopen(self.url + '/health', timeout=2) as response:
                        if json.load(response).get('status') == 'ok':
                            os.environ['SYNTRA_MODEL_URL'] = self.url
                            return True
                except (OSError, ValueError, urllib.error.HTTPError):
                    pass
                time.sleep(0.5)
            else:
                errors.append(f'{backend}: model load timed out')
            self._stop_process()
        self.stop()
        raise RuntimeError('Syntra could not load its local model (' + '; '.join(errors) +
                           '). See bundled-engine.log in LocalAppData/SyntraSlashes.')

    def _stop_process(self):
        process, self.process = self.process, None
        if process is not None and process.poll() is None:
            if os.name == 'nt':
                subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                               creationflags=subprocess.CREATE_NO_WINDOW, timeout=15)
            else:
                process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()

    def stop(self):
        self._stop_process()
        if self.log:
            self.log.close()
            self.log = None
