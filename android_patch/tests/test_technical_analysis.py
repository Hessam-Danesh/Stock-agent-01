import importlib.util
from pathlib import Path
import unittest

MODULE = Path(__file__).resolve().parents[1] / "technical_analysis.py"
spec = importlib.util.spec_from_file_location("technical_analysis", MODULE)
tech = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tech)


class TechnicalAnalysisTests(unittest.TestCase):
    def test_insufficient_data(self):
        rows = [(i, 100 + i, 100 + i, 100 + i, 0) for i in range(10)]
        result = tech.calculate_indicators(rows)
        self.assertEqual(result["data_quality"], "INSUFFICIENT")
        self.assertEqual(result["technical_trend"], "INSUFFICIENT_DATA")

    def test_flat_prices_rsi_neutral(self):
        rows = [(i, 100, 100, 100, 0) for i in range(100)]
        result = tech.calculate_indicators(rows)
        self.assertEqual(result["rsi14"], 50.0)
        self.assertEqual(result["data_quality"], "FULL")

    def test_uptrend_indicators_ready(self):
        rows = [(i, 100 + i, 100 + i, 100 + i, 1000 + i) for i in range(100)]
        result = tech.calculate_indicators(rows)
        self.assertEqual(result["data_quality"], "FULL")
        self.assertIsNotNone(result["ema20"])
        self.assertIsNotNone(result["ema50"])
        self.assertIsNotNone(result["rsi14"])
        self.assertIsNotNone(result["support20"])
        self.assertIsNotNone(result["resistance20"])
        self.assertIsNotNone(result["adx14"])
        self.assertIsNotNone(result["atr14"])
        self.assertIsNotNone(result["bb_upper"])
        self.assertIsNotNone(result["stoch_k"])

    def test_output_schema(self):
        rows = [(i, 100 + i * 0.1, 99 + i * 0.1, 101 + i * 0.1, 2000) for i in range(70)]
        result = tech.calculate_indicators(rows)
        expected = {"trade_date", "price_close", "rsi14", "ema20", "ema50", "macd", "macd_signal", "macd_hist", "latest_volume", "avg_volume20", "volume_ratio", "support20", "resistance20", "support60", "resistance60", "price_count", "traded_count", "data_quality", "technical_trend"}
        self.assertTrue(expected <= set(result))

if __name__ == "__main__":
    unittest.main()
