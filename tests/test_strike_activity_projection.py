"""Reject corrupt transient references rather than mislabeling another player."""
import pytest
from utils.strike_activity_projection import decode_observations


@pytest.mark.parametrize('record', [{'0': True}, {'0': -1}, {'1': 1}, {'99': 0}, []])
def test_corrupt_transient_observation_is_rejected(record):
    with pytest.raises(ValueError):
        decode_observations({'players': ['#PYY'], 'wars': ['war'], 'records': [record]})


def test_empty_snapshot_is_an_actual_empty_read():
    assert decode_observations({'players': [], 'wars': [], 'records': []}) == []
