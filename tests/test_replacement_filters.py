"""Human-scale FWA weights preserve exact full-weight values."""
import math

import pytest

from utils.replacement_filters import compact_weight, parse_weight


@pytest.mark.parametrize(('source', 'expected'), [
    (149, 149000), ('149', 149000), ('149k', 149000), ('149K', 149000),
    (149000, 149000), ('149000', 149000), ('149.5k', 149500),
    (500, 500000), ('500000', 500000),
])
def test_weight_input_normalization(source, expected):
    assert parse_weight(source) == expected


@pytest.mark.parametrize('source', [None, True, False, 0, '-149', '0k', '501k',
                                   500001, 'abc', '149kk', 'NaN', math.inf,
                                   math.nan, '149.0001k', '1.2.3k'])
def test_weight_input_rejects_invalid_or_out_of_range(source):
    with pytest.raises(ValueError):
        parse_weight(source)


@pytest.mark.parametrize(('source', 'expected'), [
    (149000, '149k'), (149500, '149.5k'), (149123, '149.123k'),
    (0, '0k'), (None, '?'),
])
def test_compact_weight_label(source, expected):
    assert compact_weight(source) == expected
