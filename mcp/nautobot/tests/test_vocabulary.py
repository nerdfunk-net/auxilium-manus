import pytest

from nautobot_mcp.vocabulary import UnknownNameError, Vocabulary

ROLES = ("Network", "Server", "lab")


def test_exact_match_returns_canonical_name():
    assert Vocabulary("role", ROLES).resolve("Network") == "Network"


def test_match_is_case_and_whitespace_insensitive():
    vocab = Vocabulary("role", ROLES)
    assert vocab.resolve("  network ") == "Network"
    assert vocab.resolve("LAB") == "lab"


def test_unknown_name_suggests_closest_and_lists_available():
    with pytest.raises(UnknownNameError) as exc:
        Vocabulary("role", ROLES).resolve("Netwerk")
    message = str(exc.value)
    assert "No role 'Netwerk'" in message
    assert "Closest: 'Network'" in message
    assert "Available: Network, Server, lab" in message


def test_unknown_name_without_close_match_still_lists_available():
    with pytest.raises(UnknownNameError) as exc:
        Vocabulary("role", ROLES).resolve("router")
    assert "Closest" not in str(exc.value)
    assert "Available: Network, Server, lab" in str(exc.value)


def test_long_vocabularies_are_truncated_in_the_message():
    names = tuple(f"name-{i:03d}" for i in range(100))
    with pytest.raises(UnknownNameError) as exc:
        Vocabulary("tag", names).resolve("zzz")
    assert "and 80 more" in str(exc.value)


def test_resolve_many_fails_on_the_first_unknown_value():
    vocab = Vocabulary("role", ROLES)
    assert vocab.resolve_many(["network", "SERVER"]) == ("Network", "Server")
    with pytest.raises(UnknownNameError):
        vocab.resolve_many(["network", "nope"])


def test_uuid_values_pass_through_unchanged_when_allowed():
    uuid = "3358dc2b-860c-411c-8a7f-16cb1ff17495"
    assert Vocabulary("location", ("A",), allow_uuid=True).resolve(uuid) == uuid
    with pytest.raises(UnknownNameError):
        Vocabulary("role", ROLES).resolve(uuid)


def test_names_are_immutable_and_deduplicated():
    vocab = Vocabulary("role", ["Network", "Network", "Server"])
    assert vocab.names == ("Network", "Server")


def test_empty_vocabulary_says_none_exist_instead_of_an_empty_list():
    with pytest.raises(UnknownNameError) as exc:
        Vocabulary("dcim.location tag", ()).resolve("lab")
    assert str(exc.value) == "No dcim.location tag 'lab'. None exist in this Nautobot."
