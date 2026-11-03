"""OCR receipt normalization: item sum must match stored totals."""

from app.services.ocr_normalize import normalize_parsed_receipt


def test_subtotal_is_sum_of_line_items_not_ocr_subtotal():
    parsed = {
        "items": [
            {"name": "Pizza", "price": 8000, "quantity": 1},
            {"name": "Beer", "price": 3000, "quantity": 2},
        ],
        "subtotal": 999999,
        "tax": 0,
        "tip": 0,
        "total": 14000,
    }

    out = normalize_parsed_receipt(parsed)

    assert out["subtotal"] == 14000
    assert out["total"] == 14000
    assert out["tax"] == 0


def test_line_total_stored_as_price_is_divided_by_quantity():
    parsed = {
        "items": [
            {"name": "Pizza", "price": 16000, "quantity": 2},
            {"name": "Coke", "price": 2000, "quantity": 1},
        ],
        "subtotal": 18000,
        "tax": 0,
        "tip": 0,
        "total": 18000,
    }

    out = normalize_parsed_receipt(parsed)
    pizza = next(i for i in out["items"] if i["name"] == "Pizza")

    assert pizza["quantity"] == 2
    assert abs(pizza["price"] - 8000) < 1e-6
    assert out["subtotal"] == 18000
    assert out["total"] == 18000


def test_drops_summary_rows_and_parses_qty_prefix():
    parsed = {
        "items": [
            {"name": "3x Cerveza", "price": 3000, "quantity": 1},
            {"name": "TOTAL", "price": 3000, "quantity": 1},
            {"name": "IVA", "price": 0, "quantity": 1},
        ],
        "subtotal": 3000,
        "tax": 0,
        "tip": 0,
        "total": 3000,
    }

    out = normalize_parsed_receipt(parsed)
    names = [i["name"] for i in out["items"]]

    assert names == ["Cerveza"]
    assert out["items"][0]["quantity"] == 3
    assert abs(out["items"][0]["price"] - 1000) < 1e-6
    assert out["subtotal"] == 3000


def test_tax_not_added_when_items_already_match_total():
    parsed = {
        "items": [{"name": "Menu", "price": 11900, "quantity": 1}],
        "subtotal": 10000,
        "tax": 1900,
        "tip": 0,
        "total": 11900,
    }

    out = normalize_parsed_receipt(parsed)

    assert out["subtotal"] == 11900
    assert out["tax"] == 0
    assert out["total"] == 11900


def test_keeps_tax_when_it_explains_the_receipt_total():
    parsed = {
        "items": [{"name": "Menu", "price": 10000, "quantity": 1}],
        "subtotal": 10000,
        "tax": 1900,
        "tip": 0,
        "total": 11900,
    }

    out = normalize_parsed_receipt(parsed)

    assert out["subtotal"] == 10000
    assert out["tax"] == 1900
    assert out["total"] == 11900


def test_thousands_lost_in_json_are_restored_from_receipt_total():
    parsed = {
        "items": [
            {"name": "Steak", "price": 12.5, "quantity": 1},
            {"name": "Wine", "price": 8.0, "quantity": 1},
        ],
        "subtotal": 20500,
        "tax": 0,
        "tip": 0,
        "total": 20500,
    }

    out = normalize_parsed_receipt(parsed)

    assert abs(out["subtotal"] - 20500) < 1
    assert abs(out["items"][0]["price"] - 12500) < 1
    assert abs(out["items"][1]["price"] - 8000) < 1


def test_missing_lines_become_an_adjustment_so_items_sum_to_total():
    parsed = {
        "items": [{"name": "Pizza", "price": 8000, "quantity": 1}],
        "subtotal": 12000,
        "tax": 0,
        "tip": 0,
        "total": 12000,
    }

    out = normalize_parsed_receipt(parsed)
    names = {i["name"] for i in out["items"]}

    assert "Ajuste (faltante OCR)" in names
    assert out["subtotal"] == 12000
    assert out["total"] == 12000


def test_line_total_field_wins_over_unit_price():
    parsed = {
        "items": [
            {"name": "Beer", "price": 9999, "quantity": 4, "line_total": 8000},
        ],
        "subtotal": 8000,
        "tax": 0,
        "tip": 0,
        "total": 8000,
    }

    out = normalize_parsed_receipt(parsed)

    assert abs(out["items"][0]["price"] - 2000) < 1e-6
    assert out["subtotal"] == 8000
