"""Streamlit Community Cloud 진입점.

Cloud는 Streamlit 프로세스 하나만 실행하므로, FastAPI 서버를 같은 프로세스의 백그라운드 스레드
(127.0.0.1, 외부 비공개)로 한 번만 띄운 뒤 기존 화면(ui.py)을 그대로 실행합니다.
로컬에서는 지금처럼 run.py를 쓰면 됩니다.
"""
import os
from pathlib import Path
import threading
import time
import urllib.request

import streamlit as st

ROOT = Path(__file__).resolve().parent
API_PORT = int(os.getenv("API_PORT", "8000"))
API_URL = f"http://127.0.0.1:{API_PORT}"


def load_secrets():
    """Cloud의 Secrets(TOML)를 환경변수로 옮깁니다. 이미 있는 환경변수가 우선입니다."""
    try:
        items = dict(st.secrets)
    except Exception:  # secrets.toml이 없는 로컬 실행
        return
    for name, value in items.items():
        if isinstance(value, (str, int, float, bool)) and name not in os.environ:
            os.environ[name] = str(value)


@st.cache_resource(show_spinner=False)
def start_api():
    load_secrets()
    import uvicorn
    import server

    admin, password = os.getenv("ADMIN_USER", "").strip(), os.getenv("ADMIN_PASSWORD", "")
    if admin and password:
        server.sync_admin(admin, password)  # Secrets에서 비밀번호를 바꾸면 앱 재시작 시 반영됩니다.

    api = uvicorn.Server(uvicorn.Config(server.app, host="127.0.0.1", port=API_PORT, log_level="warning"))
    threading.Thread(target=api.run, name="extra-api", daemon=True).start()
    for _ in range(100):
        try:
            urllib.request.urlopen(f"{API_URL}/openapi.json", timeout=1).close()
            return True
        except OSError:
            time.sleep(0.1)
    return False


if not start_api():
    st.error("내부 API 서버를 시작하지 못했습니다. 앱을 다시 시작하십시오.")
    st.stop()

os.environ["EXTRA_API_URL"] = API_URL
ui = ROOT / "ui.py"
exec(compile(ui.read_text(encoding="utf-8"), str(ui), "exec"), {"__name__": "__main__", "__file__": str(ui)})
