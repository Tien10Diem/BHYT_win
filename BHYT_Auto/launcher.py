"""Launcher chạy ứng dụng Tra cứu BHYT trên Windows & Linux."""
from pathlib import Path
import os
import platform
import shutil
import socket
import subprocess
import sys
import threading
import time
import urllib.request
import webbrowser

ROOT = Path(__file__).resolve().parent

def find_chrome():
    env_path = os.environ.get('BHYT_CHROME_PATH')
    if env_path and Path(env_path).is_file():
        return env_path
    
    if sys.platform == 'win32':
        candidates = [
            r'C:\Program Files\Google\Chrome\Application\chrome.exe',
            r'C:\Program Files (x86)\Google\Chrome\Application\chrome.exe',
            os.path.expandvars(r'%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe'),
            shutil.which('chrome.exe'),
            shutil.which('chrome'),
        ]
        for c in candidates:
            if c and Path(c).is_file():
                return str(Path(c).resolve())
    elif sys.platform == 'linux':
        linux_candidates = ['google-chrome', 'google-chrome-stable', 'chromium-browser', 'chromium']
        for c in linux_candidates:
            found = shutil.which(c)
            if found:
                return found
    return None

def main():
    chrome = find_chrome()
    if not chrome:
        raise RuntimeError('Không tìm thấy Google Chrome. Hãy cài đặt Chrome hoặc gán biến môi trường BHYT_CHROME_PATH.')
    
    data = Path(os.environ.get('BHYT_DATA_DIR', str(ROOT / 'data'))).resolve()
    data.mkdir(parents=True, exist_ok=True)
    (data / 'results').mkdir(exist_ok=True)
    cache = data / 'driver-cache'
    cache.mkdir(exist_ok=True)

    env = os.environ.copy()
    env.update({
        'BHYT_DATA_DIR': str(data),
        'BHYT_CHROME_PATH': chrome,
        'SE_CACHE_PATH': str(cache),
        'PYTHONDONTWRITEBYTECODE': '1'
    })
    
    if sys.platform != 'win32':
        env['PYTHONNOUSERSITE'] = '1'
        env.pop('PYTHONHOME', None)
        env.pop('PYTHONPATH', None)

    port = None
    for candidate in range(8510, 8551):
        with socket.socket() as probe:
            try:
                probe.bind(('127.0.0.1', candidate))
                port = candidate
                break
            except OSError:
                continue
    if port is None:
        raise RuntimeError('Không tìm được cổng localhost trống trong dải 8510–8550.')

    url = f'http://127.0.0.1:{port}'
    child = subprocess.Popen(
        [sys.executable, '-m', 'streamlit', 'run', str(ROOT / 'app' / 'app.py'),
         '--server.address', '127.0.0.1', '--server.port', str(port),
         '--server.headless', 'true', '--browser.gatherUsageStats', 'false'],
        env=env,
        cwd=str(ROOT / 'app')
    )

    def open_when_ready():
        for _ in range(60):
            if child.poll() is not None:
                return
            try:
                with urllib.request.urlopen(url + '/_stcore/health', timeout=1) as response:
                    if response.status == 200:
                        webbrowser.open(url, new=2)
                        return
            except OSError:
                time.sleep(0.5)

    threading.Thread(target=open_when_ready, daemon=True).start()
    print('=' * 60)
    print('  ỨNG DỤNG TRA CỨU BHYT (PHIÊN BẢN WINDOWS)')
    print('=' * 60)
    print('Địa chỉ Web:  ' + url)
    print('Thư mục lưu:  ' + str(data / 'results'))
    print('Trình duyệt:  ' + chrome)
    print('-' * 60)
    print('Giữ cửa sổ dòng lệnh này mở trong suốt quá trình tra cứu.')
    print('Bấm "Đóng Chrome" trên giao diện Web, sau đó bấm Ctrl+C tại đây để tắt.')
    print('=' * 60)

    try:
        return child.wait()
    except KeyboardInterrupt:
        print('\nĐang dừng ứng dụng...')
        child.terminate()
        try:
            child.wait(timeout=5)
        except subprocess.TimeoutExpired:
            child.kill()
            child.wait()
        return 0

if __name__ == '__main__':
    try:
        sys.exit(main())
    except Exception as exc:
        print('Không thể khởi động ứng dụng: ' + str(exc), file=sys.stderr)
        input('\nNhấn Enter để thoát...')
        sys.exit(1)
