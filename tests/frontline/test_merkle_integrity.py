import pytest
from src.ledger.merkle import merkle_root


def test_merkle_root_distinguishes_3leaf_from_4leaf():
    """In version 2, odd-node promotion with domain separation distinguishes 3 leaves from 4 leaves."""
    leaves_3 = ["leaf_a", "leaf_b", "leaf_c"]
    leaves_4 = ["leaf_a", "leaf_b", "leaf_c", "leaf_c"]

    root_3 = merkle_root(leaves_3, merkle_version=2)
    root_4 = merkle_root(leaves_4, merkle_version=2)

    assert root_3 != root_4, "3-leaf tree and 4-leaf tree (with duplicate 3rd leaf) must not collide in v2"


def test_merkle_root_distinguishes_different_multisets():
    """Two 4-leaf trees with different multisets must produce different roots."""
    tree_a = ["alpha", "beta", "gamma", "delta"]
    tree_b = ["alpha", "beta", "gamma", "epsilon"]

    root_a = merkle_root(tree_a, merkle_version=2)
    root_b = merkle_root(tree_b, merkle_version=2)

    assert root_a != root_b


def test_merkle_root_stable_for_same_multiset():
    """Two trees with identical leaves in the same order must produce identical roots."""
    tree1 = ["one", "two", "three", "four"]
    tree2 = ["one", "two", "three", "four"]

    assert merkle_root(tree1, merkle_version=2) == merkle_root(tree2, merkle_version=2)


def test_merkle_root_identical_for_same_leaves_different_order_if_documented():
    """Documented: Merkle tree in Frontline is strictly order-sensitive.
    
    Leaves represent a chronological sequence of actions/events in the transparency log.
    Permuting leaves represents a timeline reordering attack and must produce different roots.
    """
    tree1 = ["first", "second", "third", "fourth"]
    tree2 = ["fourth", "third", "second", "first"]

    root1 = merkle_root(tree1, merkle_version=2)
    root2 = merkle_root(tree2, merkle_version=2)

    assert root1 != root2, "Different leaf orders must produce different roots (order-sensitive)"


def test_legacy_merkle_roots_still_verify():
    """Legacy merkle_version=1 retains the original construction without domain separation."""
    leaves = ["leaf1", "leaf2", "leaf3"]
    # Legacy calculation: 3 leaves padded to 4 by duplicating leaf3
    import hashlib
    h12 = hashlib.sha256(("leaf1" + "leaf2").encode("utf-8")).hexdigest()
    h33 = hashlib.sha256(("leaf3" + "leaf3").encode("utf-8")).hexdigest()
    expected_v1 = hashlib.sha256((h12 + h33).encode("utf-8")).hexdigest()

    v1_root = merkle_root(leaves, merkle_version=1)
    assert v1_root == expected_v1


def test_version_2_roots_use_domain_separation():
    """Version 2 root must differ from Version 1 root for the same leaves due to domain separation."""
    leaves = ["leaf1", "leaf2", "leaf3", "leaf4"]
    v1_root = merkle_root(leaves, merkle_version=1)
    v2_root = merkle_root(leaves, merkle_version=2)

    assert v1_root != v2_root, "v2 root must use domain separation prefixes and differ from v1"
