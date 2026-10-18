from fractions import Fraction
from pathlib import Path

import pytest

import gutterline as gl

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "examples" / "house.gl"

GOOD = """\
rain 100
gutter round 125 price=18.50
downspout 76 capacity=2.0 price=12.00
plane front 12.0 6.5
"""


def _job(text=GOOD, rain=None):
    job, issues = gl.parse_job(text, rain=rain)
    assert not [i for i in issues if i.level == "error"], issues
    return job


def test_bad_number_is_reported_on_its_line():
    _, issues = gl.parse_job("rain abc\n" + GOOD.split("\n", 1)[1])
    errors = [i for i in issues if i.level == "error"]
    assert errors[0].line == 1
    assert "rain must be a number" in errors[0].message


def test_unknown_directive_points_at_its_line():
    _, issues = gl.parse_job(GOOD + "colour red\n")
    assert [(i.line, i.level) for i in issues] == [(5, "error")]
    assert "unknown directive 'colour'" in issues[0].message


def test_duplicate_singleton_names_the_first_line():
    _, issues = gl.parse_job("rain 100\nrain 80\n" + GOOD.split("\n", 1)[1])
    dup = [i for i in issues if "duplicate" in i.message]
    assert dup[0].line == 2
    assert "first set on line 1" in dup[0].message


def test_missing_required_lines_are_file_level_errors():
    _, issues = gl.parse_job("")
    assert {i.line for i in issues} == {0}
    text = " ".join(i.message for i in issues)
    for needle in ("rain", "gutter", "downspout", "plane"):
        assert needle in text


def test_flat_fall_is_a_warning_not_an_error():
    job, issues = gl.parse_job("fall 1:600\n" + GOOD)
    warnings = [i for i in issues if i.level == "warning"]
    assert warnings and warnings[0].line == 1
    assert job.fall_n == 600


def test_plane_area_and_flow_are_exact():
    # 12.0 m x 6.5 m = 78 m2; Q = 100 mm/h * 78 m2 / 3600 = 13/6 L/s exactly
    row = gl.analyse(_job())[0]
    assert row.area == 78
    assert row.flow == Fraction(13, 6)


def test_round_gutter_capacity_matches_hand_calculation():
    # D = 0.125 m: A = pi*D^2/8 = 0.0061359 m2, P = pi*D/2 + D = 0.32135 m,
    # R = 0.019095, S = 1/200, n = 0.012
    # Q = A * R^(2/3) * sqrt(S) / n = 0.0025829 m3/s = 2.583 L/s
    gutter = gl.Gutter("round", (Fraction(125),), Fraction(1))
    assert gutter.capacity_lps(Fraction(200), Fraction(12, 1000)) == pytest.approx(2.583, abs=0.005)


def test_box_gutter_capacity_matches_hand_calculation():
    # 100 x 75 mm box: A = 0.0075 m2, P = 0.25 m, R = 0.03 m
    # Q = 0.0075 * 0.03^(2/3) * sqrt(1/200) / 0.012 = 0.004267 m3/s = 4.267 L/s
    gutter = gl.Gutter("box", (Fraction(100), Fraction(75)), Fraction(1))
    assert gutter.capacity_lps(Fraction(200), Fraction(12, 1000)) == pytest.approx(4.267, abs=0.005)


def test_status_thresholds():
    assert gl.status_for(0.5, 0.8) == "OK"
    assert gl.status_for(0.9, 0.8) == "TIGHT"
    assert gl.status_for(1.01, 0.8) == "OVER"


def test_outlets_follow_flow_and_maximum_spacing():
    # Flow 30 m2 * 100 mm/h / 3600 = 0.833 L/s on 2.0 L/s downspouts -> 1 outlet by flow.
    # 30 m run with 12 m max spacing -> ceil(30 / 12) = 3 outlets by spacing. The larger wins.
    text = GOOD.replace("plane front 12.0 6.5", "plane long 30.0 1.0")
    row = gl.analyse(_job(text))[0]
    assert row.outlets == 3
    assert row.spacing == 10


def test_stock_pieces_joints_and_costs():
    # 12.0 m run, 3.0 m stock -> 4 pieces, 3 joints, 12 m bought at 18.50 = 222.00
    # Hangers every 0.6 m: ceil(12 / 0.6) + 1 = 21
    row = gl.analyse(_job())[0]
    assert (row.pieces, row.joints, row.hangers) == (4, 3, 21)
    assert gl.money(row.gutter_cost) == "222.00"
    assert gl.money(row.downspout_cost) == "24.00"


def test_money_rounds_half_up_to_cents():
    assert gl.money(Fraction(10, 3)) == "3.33"
    assert gl.money(Fraction(5, 1000)) == "0.01"


def test_pick_finds_smallest_round_size_that_fits():
    # Rain 50 mm/h: flow 1.083 L/s. 100 mm round capacity is 1.43 L/s -> 76% use, fits.
    job = _job(rain=Fraction(50))
    size, _ = gl.pick_round_size(job)
    assert size == 100
    # Rain 100 mm/h: 125 mm runs at 84% (over 80%), 150 mm capacity 4.20 L/s -> 52%.
    size, _ = gl.pick_round_size(_job(rain=Fraction(100)))
    assert size == 150


def test_rain_override_changes_flow():
    row = gl.analyse(_job(rain=Fraction(200)))[0]
    assert row.flow == Fraction(13, 3)


def test_check_exit_codes(tmp_path, capsys):
    clean = tmp_path / "clean.gl"
    clean.write_text(GOOD, encoding="utf-8")
    assert gl.main(["check", str(clean)]) == 0

    flood = tmp_path / "flood.gl"
    flood.write_text(GOOD, encoding="utf-8")
    assert gl.main(["check", str(flood), "--rain", "400"]) == 1
    assert "OVER" in capsys.readouterr().out

    broken = tmp_path / "broken.gl"
    broken.write_text("rain nope\n", encoding="utf-8")
    assert gl.main(["check", str(broken)]) == 2


def test_lint_prints_line_numbered_errors(tmp_path, capsys):
    bad = tmp_path / "bad.gl"
    bad.write_text("rain 100\nlimit 3\n", encoding="utf-8")
    assert gl.main(["lint", str(bad)]) == 2
    out = capsys.readouterr().out
    assert f"{bad}:2: error: limit must be at most 1" in out


def test_report_on_example_job_has_expected_numbers(capsys):
    assert gl.main(["report", str(EXAMPLE)]) == 0
    out = capsys.readouterr().out
    assert "front" in out and "TIGHT" in out
    # Cost: gutter 222.00 + 222.00 + 111.00 = 555.00, downspouts 24 + 12 + 12 = 48.00
    assert "total cost 603.00" in out


def test_example_pick_returns_150_at_100_mm_per_hour(capsys):
    assert gl.main(["pick", str(EXAMPLE)]) == 0
    assert "150 mm" in capsys.readouterr().out
