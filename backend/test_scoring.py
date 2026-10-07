import unittest
import sys
from pathlib import Path

# Add backend directory to sys.path
sys.path.insert(0, str(Path(__file__).parent))

from scoring import score_listing, _consistency, haversine_km, PRICES


class TestScoring(unittest.TestCase):
    def setUp(self):
        self.sample_listing = {
            "type": "rent",
            "locality": "Madhapur",
            "address": "Flat 402, Sri Residency, Madhapur, Hyderabad",
            "bhk": 2,
            "sqft": 1200,
            "price": 36000.0,
            "description": "Well maintained 2BHK near Inorbit Mall with 2 balconies and covered parking. Visits welcome on weekends.",
            "lat": 17.4483,
            "lng": 78.3915
        }
        self.lister_trusted = {"registered": True, "verified": 5, "reports": 0}

    def test_haversine_distance(self):
        # Same point distance is 0
        self.assertAlmostEqual(haversine_km(17.4483, 78.3915, 17.4483, 78.3915), 0.0, places=2)
        # Distance between Madhapur center and Gachibowli center is ~4.6 km
        dist = haversine_km(17.4483, 78.3915, 17.4401, 78.3489)
        self.assertGreater(dist, 4.0)
        self.assertLess(dist, 5.0)

    def test_location_consistency_under_5km(self):
        # Pin in Madhapur (exact centre)
        d = dict(self.sample_listing)
        d["lat"] = PRICES["Madhapur"]["lat"]
        d["lng"] = PRICES["Madhapur"]["lng"]

        pen, reasons, good = _consistency(d, n_photos=3)
        self.assertEqual(pen, 0)
        self.assertTrue(any("Pin location matches Madhapur" in g for g in good))

        # Check full score
        res = score_listing(d, n_photos=3, duplicates=[], lister_info=self.lister_trusted)
        self.assertEqual(res["score"], 100)
        self.assertEqual(res["verdict"], "Verified")

    def test_location_consistency_over_5km_lowers_score(self):
        # Listing says Madhapur, but coordinates are in LB Nagar (~20.6 km away)
        d_close = dict(self.sample_listing)
        d_far = dict(self.sample_listing)
        d_far["lat"] = PRICES["LB Nagar"]["lat"]
        d_far["lng"] = PRICES["LB Nagar"]["lng"]

        pen, reasons, good = _consistency(d_far, n_photos=3)
        self.assertGreater(pen, 50)
        self.assertTrue(any("exceeds 5 km threshold" in r[1] for r in reasons))

        # Full score must be lower for far pin than close pin
        res_close = score_listing(d_close, n_photos=3, duplicates=[], lister_info=self.lister_trusted)
        res_far = score_listing(d_far, n_photos=3, duplicates=[], lister_info=self.lister_trusted)

        self.assertLess(res_far["score"], res_close["score"])
        # Far listing must contain a clear reason mentioning the distance threshold
        far_reason_texts = [r["text"] for r in res_far["reasons"]]
        self.assertTrue(any("exceeds 5 km threshold" in t for t in far_reason_texts))

    def test_missing_coordinates_graceful(self):
        # Listings without lat/lng should not crash or trigger distance penalty
        d = dict(self.sample_listing)
        del d["lat"]
        del d["lng"]
        pen, reasons, good = _consistency(d, n_photos=3)
        self.assertEqual(pen, 0)

    def test_scam_pattern_detection(self):
        d = dict(self.sample_listing)
        d["description"] = "Owner abroad, please pay advance token money via bitcoin or western union."
        res = score_listing(d, n_photos=3, duplicates=[], lister_info=self.lister_trusted)
        self.assertLess(res["score"], 80)
        self.assertTrue(any("Scam-style wording" in r["text"] for r in res["reasons"]))

    def test_duplicate_photo_hard_limit(self):
        dups = [{"listing_id": 99, "wallet": "0x1234567890abcdef", "distance": 2}]
        res = score_listing(self.sample_listing, n_photos=3, duplicates=dups, lister_info=self.lister_trusted)
        # Reused photos can never exceed 60
        self.assertLessEqual(res["score"], 60)
        self.assertNotEqual(res["verdict"], "Verified")


if __name__ == "__main__":
    unittest.main()
