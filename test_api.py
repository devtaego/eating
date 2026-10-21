import base64
import importlib
from io import BytesIO
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch, MagicMock

from fastapi.testclient import TestClient
from PIL import Image

from nutrition import parse_response, NutritionError


class APITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.env = patch.dict(os.environ, {"EXTRA_DB": str(Path(cls.temp.name) / "test.sqlite3"), "OPENAI_API_KEY": ""})
        cls.env.start()
        import server
        cls.server = importlib.reload(server)
        cls.server.add_user("a", "password-a")
        cls.server.add_user("b", "password-b")
        cls.client = TestClient(cls.server.app)

    @classmethod
    def tearDownClass(cls):
        cls.client.close()
        cls.env.stop()
        cls.temp.cleanup()

    def auth(self, name="a"):
        token = self.client.post("/auth/login", json={"username": name, "password": f"password-{name}"}).json()["token"]
        return {"Authorization": f"Bearer {token}"}

    def test_favorites_isolated_persistent_idempotent(self):
        a, b = self.auth(), self.auth("b")
        for _ in range(2):
            self.assertEqual(self.client.put("/favorites/1", headers=a).status_code, 200)
        self.assertEqual(len(self.client.get("/favorites", headers=self.auth()).json()), 1)
        self.assertEqual(self.client.get("/favorites", headers=b).json(), [])
        self.assertEqual(self.client.put("/favorites/999", headers=a).status_code, 404)
        self.client.delete("/favorites/1", headers=b)
        self.assertEqual(len(self.client.get("/favorites", headers=a).json()), 1)
        self.client.delete("/favorites/1", headers=a)

    def test_fridge_reset_preserves_favorites_and_records(self):
        a, b = self.auth(), self.auth("b")
        self.client.put("/fridge", headers=a, json={"ingredients": ["계란", "밥"]})
        self.assertEqual(self.client.get("/fridge", headers=b).json()["ingredients"], [])
        self.client.put("/favorites/2", headers=a)
        self.client.post("/body-records", headers=a, json={"day": "2026-01-01", "height": 170, "weight": 60})
        self.client.put("/fridge", headers=a, json={"ingredients": []})
        self.assertEqual(self.client.get("/fridge", headers=a).json()["ingredients"], [])
        self.assertTrue(self.client.get("/favorites", headers=a).json())
        self.assertTrue(self.client.get("/body-records", headers=a).json())

    def test_photo_ai_request_and_validation(self):
        a = self.auth()
        image = BytesIO()
        Image.new("RGB", (10, 10)).save(image, format="PNG")
        fake = MagicMock()
        fake.responses.create.return_value.output_text = '{"ingredients":["계란","달걀"]}'
        with patch.dict(os.environ, {"OPENAI_API_KEY": "fake-test-key"}), patch.object(self.server, "OpenAI", return_value=fake):
            response = self.client.post("/ingredients/analyze", headers=a, files=[("files", ("test.png", image.getvalue(), "image/png"))])
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["ingredients"], ["달걀"])
        request = fake.responses.create.call_args.kwargs
        self.assertTrue(request["input"][0]["content"][1]["image_url"].startswith("data:image/jpeg;base64,"))
        self.assertFalse(request["store"])
        response = self.client.post("/ingredients/analyze", headers=a, files=[("files", ("test.png", b"bad", "image/png"))])
        self.assertEqual(response.status_code, 503)

    def test_nutrition_mapping_and_error(self):
        row = {"foodNm": "양파", "nutConSrtrQua": "100g", "enerc": "29", "prot": "1"}
        result = parse_response({"response": {"header": {"resultCode": "00"}, "body": {"items": [row]}}})
        self.assertEqual(result[0]["basis"], "100g")
        self.assertEqual(result[0]["energy_kcal"], "29")
        self.assertIsNone(result[0]["fat_g"])
        with self.assertRaises(NutritionError):
            parse_response({"response": {"header": {"resultCode": "30"}}})
        with patch.object(self.server, "search_nutrition", return_value=result):
            response = self.client.get("/nutrition", params={"q": "양파"}, headers=self.auth())
        self.assertEqual(response.json()["items"], result)

    def test_ai_recipes_cached_favoritable_and_fallback(self):
        a = self.auth()
        self.client.put("/fridge", headers=a, json={"ingredients": ["닭가슴살", "노란 파프리카"]})
        # 키가 없으면 샘플 레시피 + 안내 문구
        body = self.client.get("/recipes/recommend", headers=a).json()
        self.assertEqual(body["source"], "sample")
        self.assertTrue(body["notice"])
        fake = MagicMock()
        fake.responses.create.return_value.output_text = json.dumps({"recipes": [
            {"title": "닭가슴살 파프리카 볶음", "minutes": 15, "servings": 1,
             "ingredients": [{"name": "닭가슴살", "amount": "100g"}, {"name": "파프리카", "amount": "1/2개"},
                             {"name": "소금", "amount": "약간"}],
             "steps": ["닭가슴살을 속까지 익혀 주세요.", "파프리카를 넣어 볶아 주세요."]},
            {"title": "빈 레시피", "minutes": 5, "servings": 1, "ingredients": [], "steps": []}]}, ensure_ascii=False)
        with patch.dict(os.environ, {"OPENAI_API_KEY": "fake-test-key"}), patch.object(self.server, "OpenAI", return_value=fake):
            first = self.client.get("/recipes/recommend", headers=a).json()
            again = self.client.get("/recipes/recommend", headers=a).json()
        self.assertEqual(fake.responses.create.call_count, 1)  # 같은 재료는 캐시
        self.assertEqual(first["source"], "ai")
        self.assertEqual([r["title"] for r in first["recipes"]], ["닭가슴살 파프리카 볶음"])  # 빈 레시피 제외
        recipe = first["recipes"][0]
        self.assertEqual(recipe["missing"], [])  # 노란 파프리카 = 파프리카
        self.assertEqual(recipe["missing_seasonings"], ["소금"])
        self.assertEqual(again["recipes"][0]["id"], recipe["id"])
        self.assertEqual(self.client.put(f"/favorites/{recipe['id']}", headers=a).status_code, 200)
        self.assertIn(recipe["id"], [r["id"] for r in self.client.get("/favorites", headers=a).json()])
        # 다른 사용자는 남의 AI 레시피를 즐겨찾기할 수 없음
        self.assertEqual(self.client.put(f"/favorites/{recipe['id']}", headers=self.auth("b")).status_code, 404)
        self.client.delete(f"/favorites/{recipe['id']}", headers=a)

    def test_recipe_image_generated_once_and_served(self):
        a = self.auth()
        self.assertEqual(self.client.get("/recipes/1/image", headers=a).status_code, 404)  # 키 없음
        png = BytesIO()
        Image.new("RGB", (1536, 1024), (200, 120, 60)).save(png, format="PNG")
        fake = MagicMock()
        fake.images.generate.return_value.data = [MagicMock(b64_json=base64.b64encode(png.getvalue()).decode())]
        run_now = lambda fn, *args: fn(*args)  # 백그라운드 대신 즉시 실행
        with patch.dict(os.environ, {"OPENAI_API_KEY": "fake-test-key"}), \
                patch.object(self.server, "OpenAI", return_value=fake), \
                patch.object(self.server.IMAGE_POOL, "submit", side_effect=run_now):
            first = self.client.get("/recipes/2/image", headers=a)
            second = self.client.get("/recipes/2/image", headers=a)
        self.assertEqual(first.status_code, 202)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(second.headers["content-type"], "image/jpeg")
        with Image.open(BytesIO(second.content)) as image:
            self.assertLessEqual(image.width, 900)
        self.assertEqual(fake.images.generate.call_count, 1)
        self.assertEqual(self.client.get("/recipes/999/image", headers=a).status_code, 404)

    def test_login_locked_after_repeated_failures(self):
        self.server.add_user("lock", "password-lock")
        for _ in range(5):
            self.assertEqual(self.client.post("/auth/login", json={"username": "lock", "password": "bad"}).status_code, 401)
        # 잠긴 동안에는 올바른 비밀번호도 거부합니다.
        self.assertEqual(self.client.post("/auth/login", json={"username": "lock", "password": "password-lock"}).status_code, 429)
        self.server.LOGIN_FAILS.clear()
        self.assertEqual(self.client.post("/auth/login", json={"username": "lock", "password": "password-lock"}).status_code, 200)

    def test_daily_ai_limits(self):
        self.server.add_user("quota", "password-quota")
        a = self.auth("quota")
        image = BytesIO()
        Image.new("RGB", (10, 10)).save(image, format="PNG")
        fake = MagicMock()
        fake.responses.create.return_value.output_text = '{"ingredients":["달걀"]}'
        env = {"OPENAI_API_KEY": "fake-test-key", "AI_ANALYZE_DAILY_LIMIT": "1", "AI_RECIPES_DAILY_LIMIT": "1",
               "AI_IMAGES_DAILY_LIMIT": "0"}
        with patch.dict(os.environ, env), patch.object(self.server, "OpenAI", return_value=fake):
            upload = lambda: self.client.post("/ingredients/analyze", headers=a,
                                              files=[("files", ("t.png", image.getvalue(), "image/png"))])
            self.assertEqual(upload().status_code, 200)
            self.assertEqual(upload().status_code, 429)
            self.client.put("/fridge", headers=a, json={"ingredients": ["달걀"]})
            fake.responses.create.return_value.output_text = json.dumps({"recipes": [
                {"title": "달걀찜", "minutes": 10, "servings": 1, "ingredients": [{"name": "달걀", "amount": "2개"}],
                 "steps": ["달걀을 풀어 찌세요."]}]}, ensure_ascii=False)
            self.assertEqual(self.client.get("/recipes/recommend", headers=a).json()["source"], "ai")
            self.client.put("/fridge", headers=a, json={"ingredients": ["달걀", "대파"]})
            limited = self.client.get("/recipes/recommend", headers=a).json()
            self.assertEqual(limited["source"], "sample")
            self.assertIn("한도", limited["notice"])
            usage = self.client.get("/usage", headers=a).json()
        self.assertEqual(usage["analyze"], {"used": 1, "limit": 1})
        self.assertEqual(usage["recipes"], {"used": 1, "limit": 1})
        self.assertEqual(usage["images"]["limit"], 0)  # 0 = 제한 없음

    def test_logout_and_invalid_login(self):
        a = self.auth()
        self.client.post("/auth/logout", headers=a)
        self.assertEqual(self.client.get("/favorites", headers=a).status_code, 401)
        self.assertEqual(self.client.post("/auth/login", json={"username": "a", "password": "bad"}).status_code, 401)

    def test_ui_flow(self):
        import requests
        from streamlit.testing.v1 import AppTest

        def dispatch(method, url, **kwargs):
            kwargs.pop("timeout", None)
            response = self.client.request(method, url.split("8000", 1)[1], **kwargs)
            converted = requests.Response()
            converted.status_code = response.status_code
            converted._content = response.content
            return converted

        with patch("requests.request", side_effect=dispatch):
            at = AppTest.from_file(str(Path(__file__).with_name("ui.py")), default_timeout=20).run()
            at.text_input[0].set_value("b")
            at.text_input[1].set_value("password-b")
            at.button[0].click().run()
            self.assertFalse(at.exception)
            next(x for x in at.button if x.label == "저장 후 시작").click().run()
            at.text_area[0].set_value("달걀, 밥, 대파, 식용유, 소금")
            next(x for x in at.button if x.label == "추천 받기").click().run()
            self.assertFalse(at.exception)
            next(x for x in at.button if x.label == "즐겨찾기 추가").click().run()
            self.assertFalse(at.exception)
            next(x for x in at.button if x.label == "레시피 보기").click().run()
            self.assertFalse(at.exception)
            # 레시피 상세는 팝업(st.dialog)입니다. AppTest는 팝업 안 폼 제출(부분 재실행)을 지원하지 않으므로
            # 팝업이 열리고 영양정보 검색 폼이 보이는지까지만 확인합니다. 조회 API는 별도 테스트에서 검증합니다.
            self.assertTrue(any(x.label == "영양정보 검색" for x in at.button))
            self.assertTrue(any("조리 순서" in m.value for m in at.markdown))
            next(x for x in at.button if x.label == "재료 초기화").click().run()
            self.assertFalse(at.exception)
            self.assertEqual(at.text_area[0].value, "")
            self.assertTrue(any(x.label == "즐겨찾기 해제" for x in at.button))


if __name__ == "__main__":
    unittest.main()
