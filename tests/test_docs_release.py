from scripts.docs_release import final_for_candidate


def test_first_one_point_zero_candidates_publish_at_root():
    assert final_for_candidate("v1.0.0-rc.1", ["v0.103.0", "v1.0.0-rc.1"]) is None


def test_later_candidates_preserve_the_latest_final():
    assert final_for_candidate("v1.11.0-rc.1", ["v1.2.0", "v1.10.0", "v1.11.0-rc.1"]) == "v1.10.0"


def test_final_releases_publish_at_root():
    assert final_for_candidate("v1.1.0", ["v1.0.0"]) is None
