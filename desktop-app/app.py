"""Open Syntra immediately, install its model on demand, then start the workspace."""
from pathlib import Path
import sys
import threading
from http.server import ThreadingHTTPServer

import webview
from bundled_engine import BundledEngine
from model_install import InstallPaused, ModelInstaller, MODEL_BYTES, MODEL_NAME


class SetupAPI:
    def __init__(self, root=None):
        self._root = Path(root) if root else (Path(sys.executable).parent if getattr(sys, 'frozen', False) else Path(__file__).parent)
        self._installer = ModelInstaller()
        self._bundled = BundledEngine(self._root)
        self._lock = threading.RLock()
        self._worker = None
        self._window = None
        self._httpd = None
        self._closing = threading.Event()
        self._model = None
        self._state = {'phase': 'checking', 'done': 0, 'total': MODEL_BYTES,
                       'message': 'Checking your model library…', 'busy': False,
                       'ready': False, 'path': str(self._installer.directory)}

    def get_state(self):
        with self._lock:
            return dict(self._state)

    def _update(self, **changes):
        with self._lock:
            self._state.update(changes)

    def _progress(self, phase, done, total):
        self._update(phase=phase, done=done, total=total, message='')

    def _run(self, task):
        with self._lock:
            if self._closing.is_set() or (self._worker and self._worker.is_alive()):
                return False
            self._installer.cancel.clear()
            self._state.update(busy=True, message='')
            def work():
                try:
                    task()
                except InstallPaused as error:
                    self._update(phase='paused', message=str(error))
                except Exception as error:
                    self._update(phase='error', message=str(error))
                finally:
                    self._update(busy=False)
            self._worker = threading.Thread(target=work, daemon=True)
            self._worker.start()
            return True

    def _initialize(self):
        def check():
            self._model = self._installer.installed()
            if not self._model:
                candidates = [self._installer.path, self._root / 'models' / MODEL_NAME,
                              self._root / 'Syntra Offline' / 'models' / MODEL_NAME]
                for candidate in candidates:
                    if candidate.is_file():
                        try:
                            self._model = self._installer.verify(candidate, self._progress)
                            if candidate == self._installer.path:
                                self._installer._mark_verified()
                            break
                        except ValueError:
                            continue
            if self._model:
                self._update(ready=True)
                self._launch()
            else:
                saved = self._installer.partial.stat().st_size if self._installer.partial.exists() else 0
                self._update(phase='paused' if saved else 'missing', done=saved,
                             message='Your saved download is ready to resume.' if saved else '')
        self._run(check)

    def install_model(self):
        def install():
            self._model = self._installer.download(self._progress)
            self._update(phase='ready', ready=True, done=MODEL_BYTES,
                         message='Model installed and verified. You can now open Syntra.')
        return self._run(install)

    def pause_download(self):
        self._installer.cancel.set()
        return True

    def import_model(self):
        def choose():
            selection = self._window.create_file_dialog(webview.FileDialog.OPEN,
                allow_multiple=False, file_types=('GGUF model (*.gguf)',))
            if not selection:
                self._update(phase='missing', message='')
                return
            self._model = self._installer.import_model(selection[0], self._progress)
            self._update(phase='ready', ready=True, done=MODEL_BYTES,
                         message='Existing model imported and verified. Ready to use.')
        return self._run(choose)

    def open_syntra(self):
        if not self._model:
            return False
        return self._run(self._launch)

    def _launch(self):
        if self._closing.is_set():
            return
        self._update(phase='loading', message='Starting local AI. The first load may take a few minutes.')
        self._bundled.start(model_path=self._model, cancel=self._closing)
        if self._closing.is_set():
            self._bundled.stop()
            return
        import engine
        import model_bridge
        model_bridge.MODEL_SERVER_URL = self._bundled.url
        if self._httpd is None:
            self._httpd = ThreadingHTTPServer(('127.0.0.1', 0), engine.SyntraServerHandler)
            self._httpd.daemon_threads = True
            threading.Thread(target=self._httpd.serve_forever, daemon=True).start()
        self._update(phase='running', message='Syntra is ready.')
        if not self._closing.is_set():
            self._window.load_url(f'http://127.0.0.1:{self._httpd.server_port}')

    def _close(self):
        self._closing.set()
        self._installer.cancel.set()
        if 'session_manager' in sys.modules:
            sys.modules['session_manager'].stop_all_tasks()
        if self._httpd:
            self._httpd.shutdown()
            self._httpd.server_close()
        self._bundled.stop()


def main():
    api = SetupAPI()
    resources = Path(getattr(sys, '_MEIPASS', Path(__file__).parent))
    api._window = webview.create_window('Syntra Slash', str(resources / 'model-setup.html'),
        js_api=api, width=1360, height=840, min_size=(760, 640),
        resizable=True, background_color='#111113')
    api._window.events.closing += api._close
    try:
        webview.start(api._initialize, gui='edgechromium')
    finally:
        api._close()


if __name__ == '__main__':
    main()
