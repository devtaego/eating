"""하나의 명령으로 로컬 API와 화면 실행. Ctrl+C로 함께 종료."""
import getpass
from pathlib import Path
import subprocess
import sys
import time
import urllib.request

ROOT = Path(__file__).resolve().parent


def main():
    from server import add_user, db
    with db() as conn:
        has_users = conn.execute("SELECT 1 FROM users LIMIT 1").fetchone()
    if not has_users:
        print("첫 로그인 계정을 만듭니다.")
        username = input("아이디 [extra]: ").strip() or "extra"
        password = getpass.getpass("비밀번호: ")
        if not password:
            raise SystemExit("비밀번호를 입력해 주세요.")
        add_user(username, password)
    backend = subprocess.Popen([sys.executable, "-m", "uvicorn", "server:app", "--host", "127.0.0.1", "--port", "8000"], cwd=ROOT)
    ui = None
    try:
        ready = False
        for _ in range(50):
            if backend.poll() is not None:
                raise SystemExit("백엔드 실행 실패. 8000 포트의 기존 서버를 종료하고 다시 실행해 주세요.")
            try:
                urllib.request.urlopen("http://127.0.0.1:8000/openapi.json", timeout=1).close()
                # 시작 직후 기존 포트 점유 서버를 잘못 연결하지 않도록 프로세스 확인.
                time.sleep(0.2)
                if backend.poll() is None:
                    ready = True
                    break
            except OSError:
                pass
            time.sleep(0.2)
        if not ready:
            raise SystemExit("백엔드가 준비되지 않았어요. 터미널 오류를 확인해 주세요.")
        ui = subprocess.Popen([sys.executable, "-m", "streamlit", "run", "ui.py", "--server.port", "8501"], cwd=ROOT)
        print("접속: http://localhost:8501 — 종료하려면 Ctrl+C")
        while ui.poll() is None and backend.poll() is None:
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    finally:
        for proc in (ui, backend):
            if proc and proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()


if __name__ == "__main__":
    main()
