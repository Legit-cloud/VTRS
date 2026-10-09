import pytest
from hypothesis import given
from hypothesis import strategies as st

from apps.audit.domain.merkle import GENESIS_ROOT, chain_root, merkle_root

leaves = st.lists(st.binary(max_size=64), min_size=1, max_size=40)


def test_empty_batch_has_no_root():
    with pytest.raises(ValueError):
        merkle_root([])


@given(leaves)
def test_root_is_deterministic(data):
    assert merkle_root(data) == merkle_root(list(data))


@given(leaves, st.data())
def test_changing_any_leaf_changes_the_root(data, draw):
    index = draw.draw(st.integers(min_value=0, max_value=len(data) - 1))
    altered = list(data)
    altered[index] = altered[index] + b"!"
    assert merkle_root(altered) != merkle_root(data)


@given(st.lists(st.binary(max_size=16), min_size=2, max_size=20, unique=True))
def test_reordering_changes_the_root(data):
    assert merkle_root(list(reversed(data))) != merkle_root(data)


def test_odd_leaf_is_not_duplicated():
    # With duplication, [a, b, c] and [a, b, c, c] would share a root.
    assert merkle_root([b"a", b"b", b"c"]) != merkle_root([b"a", b"b", b"c", b"c"])


def test_chain_depends_on_the_previous_root():
    root = merkle_root([b"x"])
    assert chain_root(GENESIS_ROOT, root) != chain_root("1" * 64, root)
