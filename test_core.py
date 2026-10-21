import unittest
from recommend import normalize, recommend, suggest


def recipe(i, names):
    return {"id": i, "title": str(i), "minutes": 10,
            "ingredients": [{"name": n} for n in names]}


class RecommendationTests(unittest.TestCase):
    def test_alias_and_deduplication(self):
        self.assertEqual(normalize(["계란", " 달걀 ", ""]), ["달걀"])

    def test_complete_recipe_ranks_first(self):
        recipes = [recipe(1, ["달걀", "두부"]), recipe(2, ["달걀"])]
        self.assertEqual(recommend(recipes, ["계란"])[0]["id"], 2)

    def test_gain_excludes_existing_and_two_missing(self):
        recipes = [recipe(1, ["달걀"]), recipe(2, ["달걀", "두부"]),
                   recipe(3, ["두부"]), recipe(4, ["두부", "김치"])]
        result = suggest(recipes, ["달걀"])
        self.assertEqual(result["ingredient"], "두부")
        self.assertEqual(result["count"], 2)

    def test_no_unrelated_recommendations(self):
        self.assertEqual(recommend([recipe(1, ["두부"])], ["달걀"]), [])

    def test_variety_names_match_family(self):
        # 사진 인식 결과처럼 색·품종이 붙어도 같은 재료로 비교합니다.
        result = recommend([recipe(1, ["파프리카", "버섯", "토마토"])],
                           ["노란 파프리카", "양송이버섯", "방울토마토"])
        self.assertEqual(result[0]["missing"], [])

    def test_seasonings_do_not_block_or_count_as_match(self):
        recipes = [recipe(1, ["닭가슴살", "소금", "식용유"]), recipe(2, ["두부", "소금"])]
        result = recommend(recipes, ["닭가슴살"])
        self.assertEqual([r["id"] for r in result], [1])  # 소금만 겹치는 2번은 제외
        self.assertEqual(result[0]["missing"], [])
        self.assertEqual(result[0]["missing_seasonings"], ["소금", "식용유"])

    def test_suggest_ignores_missing_seasonings(self):
        recipes = [recipe(1, ["닭가슴살", "상추", "소금"])]
        self.assertEqual(suggest(recipes, ["닭가슴살"])["ingredient"], "상추")

    def test_photo_ingredients_get_full_recommendations(self):
        import json
        from pathlib import Path
        recipes = json.loads((Path(__file__).parent / "recipes.json").read_text(encoding="utf-8"))
        photo = ["노란 파프리카", "닭가슴살", "방울토마토", "브로콜리", "빨간 파프리카", "상추", "양송이버섯", "연어"]
        result = recommend(recipes, photo)
        self.assertEqual(len(result), 5)
        self.assertTrue(all(r["missing"] == [] for r in result))


if __name__ == "__main__":
    unittest.main()
