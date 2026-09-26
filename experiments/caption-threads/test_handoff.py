import unittest

from discovery import Library
from handoff import build_handoff
from workflow import discovery_brief
from test_discovery import row


class HandoffBehavior(unittest.TestCase):
    def test_only_explicitly_checked_matches_and_complete_owner_brief_are_exported(self):
        library = Library([row('yes','2021-02-03','A hiker on a trail.'),
                           row('no','2022-03-04','Hiking boots in a shop.'),
                           row('unknown','2023-04-05','A misty hillside.')])
        brief = 'Hiking across the years. ' + 'Keep the chronology. '*90 + 'Exclude shops and equipment-only pictures.'
        result = build_handoff(library,'test','Hiking',brief,'Supported hiking sources',
                               {0:'match',1:'reject',2:'unknown'})
        candidate = result.candidates[0]
        self.assertEqual(candidate.asset_ids, ('yes',))
        self.assertEqual(candidate.brief, brief)
        self.assertEqual(result.reviewed_assets,3)
        with self.assertRaises(ValueError):
            build_handoff(library,'bad','Bad',brief,'Bad',{99:'match'})

    def test_generated_details_cannot_narrow_a_geographic_thread(self):
        candidate={'operator':'returning_geography','anchor':'Italy','terms':[]}
        brief=discovery_brief(candidate)
        self.assertIn('Italy',brief)
        self.assertIn('different settings',brief)
        self.assertNotIn('mountain',brief)
