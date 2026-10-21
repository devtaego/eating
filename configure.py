"""로컬 .env에 AI 키를 입력. 입력/저장한 키는 화면에 출력하지 않습니다."""
import getpass
from pathlib import Path
from dotenv import set_key

if __name__ == "__main__":
    path = Path(__file__).resolve().parent / ".env"
    print("사진 분석용 OpenAI API 키를 설정합니다. Enter만 누르면 기존 설정을 유지합니다.")
    key = getpass.getpass("OpenAI API key: ").strip()
    if key:
        set_key(str(path), "OPENAI_API_KEY", key)
        print("AI 키 저장 완료. 실행 중인 서버를 재시작해 주세요.")
    else:
        print("기존 설정을 유지합니다.")
