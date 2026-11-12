import unittest
from decimal import Decimal

from ai_engine.services.intervention_outcomes import compare_terminal_scores


class InterventionResultComparisonTests(unittest.TestCase):
    def test_improvement_is_reported_in_percentage_points(self):
        result = compare_terminal_scores(Decimal('42.50'), Decimal('58.00'))
        self.assertEqual(result['change'], Decimal('15.50'))
        self.assertEqual(result['trend'], 'IMPROVED')

    def test_decline_is_reported(self):
        result = compare_terminal_scores(72, 61)
        self.assertEqual(result['change'], Decimal('-11'))
        self.assertEqual(result['trend'], 'DECLINED')

    def test_unchanged_score_is_not_called_improvement(self):
        result = compare_terminal_scores('50.00', '50.00')
        self.assertEqual(result['change'], Decimal('0.00'))
        self.assertEqual(result['trend'], 'UNCHANGED')

    def test_missing_result_remains_pending(self):
        result = compare_terminal_scores(40, None)
        self.assertIsNone(result['change'])
        self.assertEqual(result['trend'], 'PENDING')


if __name__ == '__main__':
    unittest.main()
