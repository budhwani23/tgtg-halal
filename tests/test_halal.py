from app.halal import classify_text, score_store
from app.tgtg_source import grid_points, parse_item


def test_classify():
    assert classify_text("Great halal kebab") == ["positive"]
    assert classify_text("Everything is 100% halal") == ["strong"]
    assert classify_text("The chicken is not halal") == ["negative"]
    assert classify_text("They have some halal options") == ["partial"]
    assert classify_text("Nice coffee") == []


def test_classify_german():
    assert classify_text("Bester Halal-Döner im Viertel") == ["positive"]
    assert classify_text("Alles ist halal zertifiziert") == ["strong"]
    assert classify_text("Die belegten Brötchen sind nicht halal.") == ["negative"]
    assert classify_text("Leider kein Halal-Fleisch") == ["negative"]
    assert classify_text("Hat einige Halal-Optionen im Kühlregal") == ["partial"]


def test_score_levels():
    store = {"name": "X", "description": ""}
    strong = score_store({"name": "Halal Grill", "description": "HMC certified"}, [])
    assert strong["level"] == "likely"
    neg = score_store(store, [], {"id": "p", "reviews": [{"text": {"text": "sadly not halal"}}]})
    assert neg["level"] == "unlikely"
    none = score_store(store, [], {"id": "p", "reviews": [{"text": {"text": "tasty"}}]})
    assert none["level"] == "unknown"
    diet = score_store(store, [{"diet_categories": ["HALAL"]}])
    assert diet["level"] == "likely"


def test_review_points_are_capped():
    reviews = [{"text": {"text": "halal and tasty"}}] * 10
    r = score_store({"name": "X", "description": ""}, [], {"id": "p", "reviews": reviews})
    assert r["score"] == 4


def test_parse_item_handles_old_and_new_price_fields():
    new = {"item": {"item_id": 1, "item_price": {"minor_units": 399, "decimals": 2, "code": "EUR"}},
           "store": {"store_id": 9, "store_name": "S"}}
    old = {"item": {"item_id": 2, "price_including_taxes": {"minor_units": 500, "decimals": 2, "code": "GBP"}},
           "store": {"store_id": 9, "store_name": "S"}}
    assert parse_item(new)[1]["price"] == 3.99
    assert parse_item(old)[1]["currency"] == "GBP"


def test_scraped_record_scores_like_a_place():
    from app.gosom_import import to_place
    rec = {"place_id": "x", "title": "Kirvem Grill Haus", "category": "Türkisches Restaurant",
           "description": "", "about": [{"id": "accessibility", "options": [{"name": "Halal-Speisen", "enabled": False}]}],
           "user_reviews": [{"Description": "Alles halal, sehr lecker"}, {"Description": "Super Döner"}]}
    place = to_place(rec)
    assert place["about_halal"] == []  # disabled option is ignored
    assert score_store({"name": "Kirvem", "description": ""}, [], place)["score"] == 2  # "alles halal" is strong


def test_grid_covers_area():
    assert len(grid_points(51.5, -0.1, 2, 3)) == 1
    assert len(grid_points(51.5, -0.1, 10, 3)) > 4
