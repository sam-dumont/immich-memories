import unittest

from discovery import Library


def row(key, date, caption, country="Belgium", city="Brussels"):
    return {"asset_id": key, "taken_at": date, "caption": caption,
            "country": country, "city": city, "media_kind": "photo", "people": []}


class DiscoveryBehavior(unittest.TestCase):
    def test_recurring_subject_survives_a_large_unrelated_burst(self):
        rows = [row(str(i), f"{2014+i}-05-02", "A ceramic vessel on a pottery wheel.")
                for i in range(10)]
        rows += [row(f"burst{i}", "2020-07-01", "A festive balloon.") for i in range(200)]
        library = Library(rows)
        candidates = library.recurrences(min_days=4, min_years=3)
        pottery = next(c for c in candidates if c["anchor"] == "pottery")
        self.assertEqual(pottery["days"], 10)
        self.assertEqual(len(pottery["years"]), 10)
        self.assertFalse(any(c["anchor"] == "balloon" for c in candidates))
        self.assertEqual({w["asset_id"] for w in library.witnesses(pottery["refs"], 10)},
                         {str(i) for i in range(10)})

    def test_geography_nominates_a_thread_without_activity_keywords(self):
        rows = [row(f"home{i}", f"{2016+i//4}-{1+i%4:02}-01", "A kitchen table.")
                for i in range(20)]
        rows += [row(f"away{i}", f"{2016+i}-06-01", "People near an old building.",
                     "Italy" if i % 2 else "France", "Elsewhere") for i in range(5)]
        library = Library(rows)
        candidates = library.geographic_candidates()
        changing = next(c for c in candidates if c["operator"] == "geographic_variation")
        self.assertEqual(set(changing["refs"]), set(range(20, 25)))
        self.assertEqual(changing["base_country"], "Belgium")
        self.assertNotIn("owner visited", changing["claim"])
        self.assertEqual(len(changing["years"]), 5)

    def test_rare_connector_retains_its_own_caption_evidence(self):
        rows = [row(str(i), f"{2014+i}-05-02", "A clay vessel beside a kiln.") for i in range(5)]
        rows += [row(str(10+i), f"{2014+i}-08-02", "A pot with glaze.") for i in range(5)]
        rows += [row("bridge", "2022-01-03", "Feldspar is used in clay bodies and glaze.")]
        library = Library(rows)
        links = library.connections({"clay": library.posts["clay"], "glaze": library.posts["glaze"]})
        link = next(c for c in links if c["connector"] == "feldspar")
        self.assertEqual(link["witness_refs"], [10])
        self.assertEqual(set(link["anchors"]), {"clay", "glaze"})
        self.assertEqual(link["status"], "hypothesis")
