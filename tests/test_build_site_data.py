from __future__ import annotations

import copy
import unittest

from scripts import build_site_data as build_site_data


class BuildSiteDataTests(unittest.TestCase):
    def test_apply_station_pricing_overrides_corrects_52mx_tiers(self) -> None:
        overrides = build_site_data.load_station_pricing_overrides()
        stations = {
            "52mx": {
                "key": "52mx",
                "label": "52mx",
                "url": "https://52mx.net/console",
                "stationType": "non_subscription",
                "stationTypeLabel": "非包月型中转站",
                "stationTypeShortLabel": "非包月型",
                "platformGuess": "new-api",
                "verifiedTierCount": 2,
                "groupMultipliers": [{"groupName": "default", "groupMultiplier": 2.0}],
                "rechargeTiers": [
                    {
                        "rechargeName": "wallet topup 10 RMB",
                        "billingType": "permanent",
                        "billingTypeLabel": "永久额度",
                        "rmbAmount": 10.0,
                        "usdAmount": 1.0,
                        "rechargeLocation": "wallet API",
                        "expiresRule": "钱包接口未注明有效期",
                    },
                    {
                        "rechargeName": "wallet topup 50 RMB",
                        "billingType": "permanent",
                        "billingTypeLabel": "永久额度",
                        "rmbAmount": 50.0,
                        "usdAmount": 5.0,
                        "rechargeLocation": "wallet API",
                        "expiresRule": "钱包接口未注明有效期",
                    },
                ],
                "tierNotes": [],
                "announcements": [],
                "rankings": {},
                "quality": {},
            }
        }

        build_site_data.apply_station_pricing_overrides(stations, overrides)

        station = stations["52mx"]
        self.assertEqual(station["groupMultipliers"], [{"groupName": "default", "groupMultiplier": 1.0}])
        self.assertEqual([tier["usdAmount"] for tier in station["rechargeTiers"]], [100.0, 500.0])

    def test_authoritative_ranking_override_corrects_52mx_multiplier(self) -> None:
        overrides = build_site_data.load_station_pricing_overrides()
        stations = {
            "52mx": {
                "key": "52mx",
                "label": "52mx",
                "url": "https://52mx.net/console",
                "stationType": "non_subscription",
                "stationTypeLabel": "非包月型中转站",
                "stationTypeShortLabel": "非包月型",
                "platformGuess": "new-api",
                "verifiedTierCount": 2,
                "groupMultipliers": [{"groupName": "default", "groupMultiplier": 1.0}],
                "rechargeTiers": [
                    {
                        "rechargeName": "wallet topup 10 RMB",
                        "billingType": "permanent",
                        "billingTypeLabel": "永久额度",
                        "rmbAmount": 10.0,
                        "usdAmount": 100.0,
                        "rechargeLocation": "wallet API",
                        "expiresRule": "钱包接口未注明有效期",
                    }
                ],
                "tierNotes": [],
                "announcements": [],
                "rankings": {},
                "quality": {},
            },
            "other": {
                "key": "other",
                "label": "other",
                "url": "https://example.com",
                "stationType": "non_subscription",
                "stationTypeLabel": "非包月型中转站",
                "stationTypeShortLabel": "非包月型",
                "platformGuess": "new-api",
                "verifiedTierCount": 1,
                "groupMultipliers": [{"groupName": "default", "groupMultiplier": 1.0}],
                "rechargeTiers": [],
                "tierNotes": [],
                "announcements": [],
                "rankings": {},
                "quality": {},
            },
        }
        rankings = {
            "work_hours": [
                {
                    "rank": 2,
                    "rankingBasis": "formal_high_confidence",
                    "timeWindow": "work_hours",
                    "timeWindowLabel": "工作时段",
                    "station": "52mx",
                    "label": "52mx",
                    "stationUrl": "https://52mx.net",
                    "stationType": "non_subscription",
                    "stationTypeLabel": "非包月型中转站",
                    "stationTypeShortLabel": "非包月型",
                    "totalScore": 0.0,
                    "successScore": 25.0,
                    "latencyScore": 34.0,
                    "costScore": 0.0,
                    "correctRate": 0.25,
                    "avgSeconds": 205.0,
                    "medianSeconds": 238.0,
                    "p95Seconds": 293.0,
                    "effectiveMultiplier": 20.0,
                    "feeVerified": True,
                    "adoptedTier": "default | wallet topup 10 RMB",
                    "adoptedGroup": "default",
                    "adoptedRechargeName": "wallet topup 10 RMB",
                    "billingType": "permanent",
                    "billingTypeLabel": "永久额度",
                    "multiplierFullUseAssumption": "钱包接口未注明有效期",
                    "requests": 12,
                    "correct": 3,
                    "failures": 9,
                    "http2xx": 3,
                    "http200WithError": 0,
                    "firstAt": "",
                    "lastAt": "",
                },
                {
                    "rank": 1,
                    "rankingBasis": "formal_high_confidence",
                    "timeWindow": "work_hours",
                    "timeWindowLabel": "工作时段",
                    "station": "other",
                    "label": "other",
                    "stationUrl": "https://example.com",
                    "stationType": "non_subscription",
                    "stationTypeLabel": "非包月型中转站",
                    "stationTypeShortLabel": "非包月型",
                    "totalScore": 0.0,
                    "successScore": 50.0,
                    "latencyScore": 60.0,
                    "costScore": 0.0,
                    "correctRate": 0.5,
                    "avgSeconds": 50.0,
                    "medianSeconds": 50.0,
                    "p95Seconds": 60.0,
                    "effectiveMultiplier": 1.0,
                    "feeVerified": True,
                    "adoptedTier": "default | tier",
                    "adoptedGroup": "default",
                    "adoptedRechargeName": "tier",
                    "billingType": "permanent",
                    "billingTypeLabel": "永久额度",
                    "multiplierFullUseAssumption": "baseline",
                    "requests": 10,
                    "correct": 5,
                    "failures": 5,
                    "http2xx": 5,
                    "http200WithError": 0,
                    "firstAt": "",
                    "lastAt": "",
                },
            ],
            "off_hours": [],
            "all_hours": [],
        }

        build_site_data.apply_authoritative_ranking_overrides(stations, rankings, overrides)

        row = rankings["work_hours"][0]
        self.assertEqual(row["station"], "52mx")
        station_row = rankings["work_hours"][0]
        self.assertAlmostEqual(station_row["effectiveMultiplier"], 0.1)
        self.assertEqual(station_row["adoptedTier"], "default | wallet topup 10 RMB")
        self.assertEqual(station_row["rank"], 1)

    def test_recompute_ranking_window_recalculates_cost_total_and_rank(self) -> None:
        rows = [
            {
                "rank": 3,
                "station": "a",
                "successScore": 30.0,
                "latencyScore": 40.0,
                "effectiveMultiplier": 0.1,
                "totalScore": 0.0,
                "costScore": 0.0,
            },
            {
                "rank": 2,
                "station": "b",
                "successScore": 35.0,
                "latencyScore": 50.0,
                "effectiveMultiplier": 1.0,
                "totalScore": 0.0,
                "costScore": 0.0,
            },
            {
                "rank": 1,
                "station": "c",
                "successScore": 45.0,
                "latencyScore": 55.0,
                "effectiveMultiplier": 7.1,
                "totalScore": 0.0,
                "costScore": 0.0,
            },
        ]

        build_site_data.recompute_ranking_window(rows)

        by_station = {row["station"]: row for row in rows}
        self.assertAlmostEqual(by_station["a"]["costScore"], 100.0)
        self.assertAlmostEqual(by_station["c"]["costScore"], 0.0)
        self.assertGreater(by_station["b"]["totalScore"], by_station["a"]["totalScore"])
        self.assertEqual([row["station"] for row in rows], ["b", "a", "c"])
        self.assertEqual([row["rank"] for row in rows], [1, 2, 3])


if __name__ == "__main__":
    unittest.main()
