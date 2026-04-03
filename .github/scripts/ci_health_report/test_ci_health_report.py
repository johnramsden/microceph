import unittest
from unittest.mock import MagicMock, patch
from collections import defaultdict
from datetime import datetime, timezone
import urllib.request
import urllib.error

import ci_health_report
from ci_health_report import (
    SPARKS,
    bucket_count,
    make_sparkline,
    trend_indicator,
    build_report,
    main,
    _urlopen,
)


class _Tests(unittest.TestCase):

    @patch("time.sleep")
    @patch("urllib.request.urlopen")
    def test_rate_limit_retries_with_wait(self, mock_urlopen, mock_sleep):
        """_urlopen sleeps Retry-After + 5s on 429 then retries successfully."""
        import http.client
        msg = http.client.HTTPMessage()
        msg["Retry-After"] = "10"
        resp = MagicMock()
        resp.read.return_value = b'{"ok": true}'
        resp.__enter__ = lambda s: s
        resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.side_effect = [
            urllib.error.HTTPError("https://api.github.com/test", 429, "Too Many Requests", msg, None),
            resp,
        ]
        result = _urlopen(urllib.request.Request("https://api.github.com/test"))
        mock_sleep.assert_called_once_with(15)  # Retry-After(10) + 5
        self.assertEqual(result, b'{"ok": true}')

    def test_bucket_count(self):
        """bucket_count returns daily, weekly, or monthly bucket counts."""
        self.assertEqual(bucket_count(7),  7)   # daily
        self.assertEqual(bucket_count(14), 14)  # daily (boundary)
        self.assertEqual(bucket_count(30), 4)   # weekly
        self.assertEqual(bucket_count(90), 12)  # weekly (boundary)
        self.assertEqual(bucket_count(91), 3)   # monthly

    def test_make_sparkline_all_zero(self):
        """make_sparkline returns all low bars when every bucket has zero failures."""
        buckets = [{"runs": 10, "failures": 0}] * 4
        self.assertEqual(make_sparkline(buckets), "▁▁▁▁")

    def test_make_sparkline_ascending(self):
        """make_sparkline lowest bar at start, highest at end for rising failure rate."""
        buckets = [
            {"runs": 10, "failures": 0},
            {"runs": 10, "failures": 5},
            {"runs": 10, "failures": 10},
        ]
        spark = make_sparkline(buckets)
        self.assertEqual(len(spark), 3)
        self.assertLess(SPARKS.index(spark[0]), SPARKS.index(spark[1]))
        self.assertLess(SPARKS.index(spark[1]), SPARKS.index(spark[2]))

    def test_trend_indicator_increasing(self):
        """trend_indicator returns ↑ when recent half has higher failure rate."""
        buckets = [
            {"runs": 10, "failures": 1},
            {"runs": 10, "failures": 1},
            {"runs": 10, "failures": 5},
            {"runs": 10, "failures": 5},
        ]
        result = trend_indicator(buckets)
        self.assertTrue(result.startswith("↑"))

    def test_trend_indicator_decreasing(self):
        """trend_indicator returns ↓ when recent half has lower failure rate."""
        buckets = [
            {"runs": 10, "failures": 5},
            {"runs": 10, "failures": 5},
            {"runs": 10, "failures": 1},
            {"runs": 10, "failures": 1},
        ]
        result = trend_indicator(buckets)
        self.assertTrue(result.startswith("↓"))

    def test_build_report_structure_and_totals(self):
        """build_report produces a markdown table with Trend column and correct summary totals."""
        buckets = [{"runs": 5, "failures": 1}, {"runs": 5, "failures": 2}]
        stats = defaultdict(lambda: {"runs": 0, "failures": 0, "buckets": []})
        stats[("Tests", "build")]["runs"] = 10
        stats[("Tests", "build")]["failures"] = 3
        stats[("Tests", "build")]["buckets"] = buckets
        now = datetime(2026, 1, 1, 9, 0, 0, tzinfo=timezone.utc)
        report = build_report(stats, 30, 5, now)
        self.assertIn("| Workflow | Job | Runs | Failures | Rate | Trend |", report)
        self.assertIn("| Tests | build | 10 | 3 | 30.0%", report)
        self.assertIn("**Total job runs:** 10", report)
        self.assertIn("**Total failures:** 3", report)
        self.assertIn("**Overall failure rate:** 30.0%", report)

    @patch("ci_health_report.post_comment")
    @patch("ci_health_report.get_jobs")
    @patch("ci_health_report.get_runs")
    def test_skipped_and_cancelled_not_counted(self, mock_runs, mock_jobs, mock_comment):
        """skipped and cancelled conclusions are excluded from run and failure counts."""
        mock_runs.return_value = [{"id": 1, "name": "Tests", "created_at": "2026-01-15T00:00:00Z"}]
        mock_jobs.return_value = [
            {"name": "build", "conclusion": "success"},
            {"name": "build", "conclusion": "failure"},
            {"name": "build", "conclusion": "skipped"},
            {"name": "build", "conclusion": "cancelled"},
        ]
        with patch.dict("os.environ", {"GH_TOKEN": "tok", "GH_REPO": "o/r", "REPORT_ISSUE": "1", "LOOKBACK_DAYS": "30", "TOP_JOBS": "5"}):
            main()
        report = mock_comment.call_args[0][3]
        self.assertIn("| Tests | build | 2 | 1 |", report)


if __name__ == "__main__":
    unittest.main()
