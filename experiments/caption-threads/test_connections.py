import unittest

from connection_recheck import validate_sides


class ConnectionEvidenceBehavior(unittest.TestCase):
    def test_a_definition_cannot_replace_the_pictured_input(self):
        answer={'decision':'cross_context','title':'A material and its use','claim':'A relation',
                'input_refs':[2],'outcome_refs':[2],'relation_refs':[3],'unknowns':[]}
        dates={1:'2021-01-01',2:'2022-01-01',3:'2020-01-01'}
        with self.assertRaises(ValueError):
            validate_sides(answer,{1},{2},{1,2,3},dates)
