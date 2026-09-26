import unittest

from discovery import Library
from query import retrieve_plan
from test_discovery import row


class RequestRetrievalBehavior(unittest.TestCase):
    def test_across_places_does_not_admit_unrelated_foreign_pictures(self):
        rows = [row(str(i),f'{2015+i}-01-01','A pottery workshop.') for i in range(5)]
        rows += [row(str(10+i),f'{2015+i}-02-01','A street sign.','France','Paris') for i in range(5)]
        rows += [row(str(20+i),f'{2015+i}-03-01','A table.') for i in range(5)]
        library=Library(rows)
        plan={'queries':[['pottery']],'countries':[], 'geographic_contrast':True,
              'retrieval_basis':'geographic_history','since':None,'until':None}
        self.assertEqual(retrieve_plan(library,plan),list(range(5)))
