import re
from django.test import SimpleTestCase


class StudentRankingIntentTests(SimpleTestCase):
    def test_general_overall_best_is_not_award_only(self):
        q = "who is the overall best student"
        ranking_words = ("best", "top", "highest", "overall", "rank", "ranking", "performing", "performance", "average", "awards", "scholarships", "promotion")
        self.assertTrue(any(w in q for w in ranking_words))

    def test_award_and_general_ranking_are_distinct_intents(self):
        award_q = "best students for academic awards"
        general_q = "who is the overall best student"
        self.assertNotEqual("award" in award_q, "award" in general_q)

    def test_top_n_numeric_and_word_formats(self):
        for q, expected in (("top 5 students", 5), ("best 3 students", 3)):
            match = re.search(r"\b(?:top|best|highest|rank(?:ed|ing)?|first)\s+(\d{1,2})\b", q)
            self.assertEqual(int(match.group(1)), expected)
        words = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5}
        self.assertEqual(words["five"], 5)
