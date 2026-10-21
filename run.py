"""하나의 명령으로 로컬 API와 화면 실행. Ctrl+C로 함께 종료.

환경변수(선택):
  UI_ADDRESS / UI_PORT        화면 주소·포트 (기본 127.0.0.1:8501 → 이 PC에서만 접속)
  API_PORT                    내부 API 포트 (기본 8000, 항상 127.0.0.1에서만 받음)
  ADMIN_USER / ADMIN_PASSWORD 계정이 없으면 이 값으로 자동 생성 (배포 환경처럼 입력할 수 없을 때)
"""
import getpass
import os
from pathlib import Path
import subprocess
import sys
import time
import urllib.request

ROOT = Path(__file__).resolve().parent
# 출력이 파일·파이프로 갈 때(Windows cp949 등) 인코딩 오류로 멈추지 않게 합니다.
sys.stdout.reconfigure(errors="replace")


def ensure_account():
    from server import add_user, db
    admin, password = os.getenv("ADMIN_USER", "").strip(), os.getenv("ADMIN_PASSWORD", "")
    with db() as conn:
        if admin and password:
            if not conn.execute("SELECT 1 FROM users WHERE username=?", (admin,)).fetchone():
                add_user(admin, password)
                print(f"계정 '{admin}'을(를) 만들었습니다.")
            return
        has_users = conn.execute("SELECT 1 FROM users LIMIT 1").fetchone()
    if has_users:
        return
    if not sys.stdin.isatty():
        raise SystemExit("계정이 없습니다. ADMIN_USER와 ADMIN_PASSWORD 환경변수를 설정하십시오.")
    print("첫 로그인 계정을 만듭니다.")
    username = input("아이디 [extra]: ").strip() or "extra"
    password = getpass.getpass("비밀번호: ")
    if not password:
        raise SystemExit("비밀번호를 입력해 주세요.")
    add_user(username, password)


def main():
    ensure_account()
    address, port = os.getenv("UI_ADDRESS", "127.0.0.1"), os.getenv("UI_PORT", "8501")
    api_port = os.getenv("API_PORT", "8000")
    api_url = f"http://127.0.0.1:{api_port}"
    backend = subprocess.Popen([sys.executable, "-m", "uvicorn", "server:app", "--host", "127.0.0.1", "--port", api_port], cwd=ROOT)
    ui = None
    try:
        ready = False
        for _ in range(50):
            if backend.poll() is not None:
                raise SystemExit(f"백엔드 실행 실패. {api_port} 포트의 기존 서버를 종료하고 다시 실행해 주세요.")
            try:
                urllib.request.urlopen(f"{api_url}/openapi.json", timeout=1).close()
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
        ui = subprocess.Popen([sys.executable, "-m", "streamlit", "run", "ui.py", "--server.address", address,
                               "--server.port", port, "--server.headless", "true"], cwd=ROOT,
                              env={**os.environ, "EXTRA_API_URL": api_url})
        print(f"접속: http://localhost:{port} (종료: Ctrl+C)")
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
