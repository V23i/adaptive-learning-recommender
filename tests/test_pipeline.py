"""End-to-end tests on a tiny scale: reproducibility, validation, anomaly detection, SQL load, evaluation."""
import os, shutil, sqlite3, sys, tempfile, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import generate as G, validate as V, evaluate as E

TINY = dict(learners=150, skills=30, content=90, attempts=3000, courses=4)


class Pipeline(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        cls.a = G.build("starter", out=os.path.join(cls.tmp, "a"), overrides=TINY)
        cls.b = G.build("starter", out=os.path.join(cls.tmp, "b"), overrides=TINY)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp)

    def test_same_seed_is_reproducible(self):
        self.assertEqual(self.a["row_counts"], self.b["row_counts"])
        self.assertEqual(self.a["sha256"], self.b["sha256"])

    def test_different_seed_differs(self):
        m = G.build("starter", seed=1, out=os.path.join(self.tmp, "c"), formats=("csv",), overrides=TINY)
        self.assertNotEqual(m["sha256"]["attempt.csv"], self.a["sha256"]["attempt.csv"])

    def test_exact_volume(self):
        self.assertEqual(self.a["row_counts"]["attempt"], TINY["attempts"])
        self.assertEqual(self.a["row_counts"]["learner"], TINY["learners"])

    def test_validation_passes_and_all_injected_issues_found(self):
        s = V.run(os.path.join(self.tmp, "a"), quiet=True)
        self.assertEqual(s["unexplained_findings"], {})
        self.assertTrue(s["passed"])
        for typ, v in s["injected_issue_detection"].items():
            self.assertGreater(v["labelled"], 0, typ)
            self.assertEqual((v["false_pos"], v["false_neg"]), (0, 0), typ)

    def test_clean_run_has_no_findings(self):
        m = G.build("starter", out=os.path.join(self.tmp, "d"), formats=("csv",), anomalies=False, overrides=TINY)
        s = V.run(os.path.join(self.tmp, "d"), quiet=True)
        self.assertEqual(s["findings"], {})
        self.assertEqual(m["row_counts"]["ground_truth"], 0)

    def test_sql_seed_loads(self):
        con = sqlite3.connect(":memory:")
        d = os.path.join(self.tmp, "a")
        con.executescript(open(os.path.join(d, "schema.sql")).read())
        con.executescript(open(os.path.join(d, "seed.sql")).read())
        n = con.execute("select count(*) from attempt").fetchone()[0]
        self.assertEqual(n, TINY["attempts"])

    def test_temporal_split_evaluation_runs(self):
        out = E.run(os.path.join(self.tmp, "a"), quiet=True)
        self.assertEqual(out["clean"]["prerequisite_compliance"], 1.0)
        self.assertEqual(out["clean"]["reason_code_coverage"], 1.0)


if __name__ == "__main__":
    unittest.main()
