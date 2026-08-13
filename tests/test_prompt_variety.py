from src.core.enums import Audience, Category, OpportunityStatus
from src.db.models.opportunity import Opportunity
from src.publisher.live_background import (
    _MOODS,
    _PALETTES,
    _SCENE_HINTS,
    _STYLES,
    _compose_prompt,
)


def _make_opp(id_: int | None, category: Category = Category.Hackathon) -> Opportunity:
    opp = Opportunity(
        title="Some Opportunity",
        category=category,
        audience=Audience.both,
        status=OpportunityStatus.pending,
    )
    opp.id = id_
    return opp


def _axes(id_: int, category: Category = Category.Hackathon) -> tuple[str, str, str, str]:
    scenes = _SCENE_HINTS[category.value]
    style = _STYLES[(id_ * 7) % len(_STYLES)]
    mood = _MOODS[(id_ * 3) % len(_MOODS)]
    palette = _PALETTES[(id_ * 5) % len(_PALETTES)]
    scene = scenes[(id_ * 11) % len(scenes)]
    return (style, mood, palette, scene)


def test_ids_1_to_20_produce_20_distinct_tuples():
    tuples = {_axes(i) for i in range(1, 21)}
    assert len(tuples) == 20


def test_consecutive_ids_differ_on_all_four_axes():
    for i in range(1, 20):
        a, b = _axes(i), _axes(i + 1)
        assert all(x != y for x, y in zip(a, b)), (i, a, b)


def test_prompt_reflects_deterministic_scene_for_id():
    opp = _make_opp(id_=3)
    prompt = _compose_prompt(opp)
    _, _, _, scene = _axes(3)
    assert scene in prompt


def test_opp_id_none_still_returns_valid_prompt():
    opp = _make_opp(id_=None)
    prompt = _compose_prompt(opp)
    assert isinstance(prompt, str) and len(prompt) > 0
    assert "Some Opportunity" in prompt
