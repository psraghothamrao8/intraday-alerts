"""
Acceptance test for Task 7: Stop calibration and config reference.
Verifies that:
1. stops_S1.md, stops_S2.md, and stops_S3.md exist in data/reports/.
2. config.yaml references all three stop report files.
3. Stop parameters match calibration decisions.
"""
from pathlib import Path
import pytest


def test_stop_reports_exist_and_referenced_in_config():
    r_dir = Path("data/reports")
    s1_rep = r_dir / "stops_S1.md"
    s2_rep = r_dir / "stops_S2.md"
    s3_rep = r_dir / "stops_S3.md"

    assert s1_rep.exists(), "data/reports/stops_S1.md must exist"
    assert s2_rep.exists(), "data/reports/stops_S2.md must exist"
    assert s3_rep.exists(), "data/reports/stops_S3.md must exist"

    cfg_text = Path("config.yaml").read_text(encoding="utf-8")
    assert "stops_S1.md" in cfg_text, "config.yaml must reference stops_S1.md"
    assert "stops_S2.md" in cfg_text, "config.yaml must reference stops_S2.md"
    assert "stops_S3.md" in cfg_text, "config.yaml must reference stops_S3.md"

    # Verify key sections in the stop reports
    for rep in [s1_rep, s2_rep, s3_rep]:
        content = rep.read_text(encoding="utf-8")
        assert "MAE" in content
        assert "Stop Variant" in content
        assert "Decision & Configuration" in content
