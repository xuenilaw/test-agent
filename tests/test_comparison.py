"""Report arithmetic and cohort alignment."""
import json
import tempfile
import unittest
from pathlib import Path
from test_agent.verification.comparison import cost,compare,markdown


class ComparisonTests(unittest.TestCase):
    def test_different_jpeg_bytes_cannot_be_claimed_same_input(self):
        with tempfile.TemporaryDirectory() as temp:
            paths=[]
            for name,sha in [('a','hash-a'),('b','hash-b')]:
                path=Path(temp)/name;path.mkdir();paths.append(path)
                record=dict(image='x',attempt=1,expected='PASS',ideal='PASSED',requirement=dict(origin='Hamburg',destination='Berlin'),
                    status='PASSED',latency_ms=1,usage={},image_variant='jpeg',sha256=sha)
                (path/'results.json').write_text(json.dumps(dict(records=[record],min_confidence=.90)))
            with self.assertRaisesRegex(ValueError,'JPEG bytes differ'):
                compare(dict(A=[paths[0]],B=[paths[1]]))

    def test_cost_and_cohort_alignment(self):
        self.assertEqual(cost(dict(model='claude-haiku-5-5',usage=dict(input_tokens=100,output_tokens=20))),(.00002,'estimated'))
        self.assertEqual(cost(dict(usage=dict(cost=.00001))),(.00001,'reported'))
        self.assertEqual(cost(dict(model='unknown',usage={})),(None,'unknown'))
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            record=dict(image='x',attempt=1,expected='PASS',ideal='PASSED',requirement=dict(origin='Hamburg',destination='Berlin'),
                status='PASSED',latency_ms=20,model='clef',usage=dict(cost=.00001),code=None)
            paths=[]
            for name in ['a','b']:
                p=root/name;p.mkdir();paths.append(p)
                (p/'results.json').write_text(json.dumps(dict(records=[record],min_confidence=.90)))
            result=compare(dict(A=[paths[0]],B=[paths[1]]))
            self.assertEqual(result['A']['totals']['false_pass'],0)
            self.assertIn('0.00001000',markdown(result))
            record['ideal']='FAILED'
            (paths[1]/'results.json').write_text(json.dumps(dict(records=[record],min_confidence=.90)))
            with self.assertRaises(ValueError):
                compare(dict(A=[paths[0]],B=[paths[1]]))
