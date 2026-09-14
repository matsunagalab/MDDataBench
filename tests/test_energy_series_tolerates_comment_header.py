"""The scorer reads a StateDataReporter log even with an agent's own comment line on top.

037_ligand_1g74 sif_only r3 (campaign v2): the first line was a
space-separated ``# Step Time(ps) ...`` comment, DictReader made it the header,
every field landed under ``None`` and the scorer crashed (``scorer_error``).
"""

import numpy as np

from mddatabench import dynamics


HEADER = '#"Step","Time (ps)","Potential Energy (kJ/mole)","Temperature (K)"\n'
ROWS = "1000,2.0,-2000.5,300.1\n2000,4.0,-2001.5,299.9\n"


def test_comment_line_before_the_header_is_skipped(tmp_path):
    path = tmp_path / "energy.dat"
    path.write_text("# Step Time(ps) PotentialEnergy(kJ/mol) Temperature(K)\n" + HEADER + ROWS)
    series = dynamics.energy_series(path)
    assert np.allclose(series["Potential Energy (kJ/mole)"], [-2000.5, -2001.5])
    assert np.allclose(series["Step"], [1000, 2000])


def test_a_plain_reporter_log_reads_as_before(tmp_path):
    path = tmp_path / "energy.csv"
    path.write_text(HEADER + ROWS)
    assert np.allclose(dynamics.energy_series(path)["Temperature (K)"], [300.1, 299.9])


def test_extra_fields_without_a_header_do_not_crash(tmp_path):
    path = tmp_path / "energy.csv"
    path.write_text(HEADER + "1000,2.0,-2000.5,300.1,extra\n")
    assert np.allclose(dynamics.energy_series(path)["Step"], [1000])


def test_only_comments_is_empty(tmp_path):
    path = tmp_path / "energy.dat"
    path.write_text("# nothing here\n# still nothing\n")
    assert dynamics.energy_series(path) == {}
