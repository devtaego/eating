# Hugging Face Spaces(Docker) 배포용. 로컬 개발과 같은 Python 3.14를 씁니다.
FROM python:3.14-slim

# Spaces는 UID 1000 사용자로 실행합니다.
RUN useradd -m -u 1000 user
USER user
ENV HOME=/home/user \
    PATH=/home/user/.local/bin:$PATH \
    PYTHONUNBUFFERED=1
WORKDIR /home/user/app

COPY --chown=user requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt

COPY --chown=user . .

# 화면은 외부(7860)에 열고, API는 컨테이너 내부(127.0.0.1:8000)에서만 받습니다.
# Spaces 페이지는 앱을 iframe으로 띄우므로 Streamlit XSRF 쿠키가 막혀 사진 업로드가 403이 될 수 있어 끕니다.
# (API는 쿠키가 아닌 Bearer 토큰으로 인증합니다.)
ENV UI_ADDRESS=0.0.0.0 \
    UI_PORT=7860 \
    STREAMLIT_SERVER_ENABLE_XSRF_PROTECTION=false \
    STREAMLIT_BROWSER_GATHER_USAGE_STATS=false

EXPOSE 7860
CMD ["python", "run.py"]
