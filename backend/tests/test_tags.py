"""agent/tags.py v1 (04-backend-design §5.0): letters, H1/H2 and name matching."""

import pytest

from app.agent.tags import assign_place_tags, letter_tag, lodging_tag, normalize_name


@pytest.mark.parametrize(
    ("index", "tag"),
    [(0, "A"), (1, "B"), (25, "Z"), (26, "AA"), (27, "AB"), (51, "AZ"), (52, "BA"), (701, "ZZ"), (702, "AAA")],
)
def test_letter_tag_runs_a_to_z_then_aa(index, tag):
    assert letter_tag(index) == tag


def test_letter_tag_rejects_negative_index():
    with pytest.raises(ValueError):
        letter_tag(-1)


def test_lodging_tags_are_h1_h2():
    assert [lodging_tag(i) for i in range(2)] == ["H1", "H2"]


def test_normalize_name_ignores_case_punctuation_and_spacing():
    assert normalize_name("  Torchy's   Tacos ") == normalize_name("TORCHYS TACOS") == "torchys tacos"


def test_assign_place_tags_in_first_appearance_order():
    names = ["Franklin Barbecue", "Texas State Capitol", "franklin barbecue", "Zilker Park", "Texas State Capitol."]

    assert assign_place_tags(names) == {"franklin barbecue": "A", "texas state capitol": "B", "zilker park": "C"}


def test_assign_place_tags_goes_past_z():
    tags = assign_place_tags([f"Place {i}" for i in range(28)])

    assert list(tags.values())[24:] == ["Y", "Z", "AA", "AB"]
