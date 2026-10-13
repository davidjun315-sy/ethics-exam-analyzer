"""Local one-command launch; open a browser only after the server is ready."""
import os
import subprocess
import sys
import threading
import time
import urllib.request
import webbrowser


def main():
    port = os.getenv('PORT', '8000')
    url = f'http://127.0.0.1:{port}'
    process = subprocess.Popen([sys.executable, '-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', port])
    def open_when_ready():
        for _ in range(100):
            if process.poll() is not None:
                return
            try:
                with urllib.request.urlopen(url + '/health', timeout=.5) as response:
                    if response.status == 200:
                        webbrowser.open(url)
                        return
            except OSError:
                time.sleep(.2)
    if os.getenv('OPEN_BROWSER', '1') == '1':
        threading.Thread(target=open_when_ready, daemon=True).start()
    try:
        return process.wait()
    except KeyboardInterrupt:
        process.terminate()
        process.wait()
        return 0


if __name__ == '__main__':
    raise SystemExit(main())
