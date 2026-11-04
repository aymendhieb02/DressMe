from sqlalchemy import select
from datetime import timedelta

from app.models import Garment, utcnow
from tests.test_garment_export import _register, _seed_garment, _seed_pending_only


def test_search_filters_precede_pagination_and_keep_owner_scope(client, origin):
    _, owner_id = _register(client, origin, "search-owner@example.invalid")
    factory = client.app.state.testing_session_factory
    target_id, _ = _seed_garment(factory, owner_id, description="Blue needle 50%_literal, quoted \"line\"\nCaf\u00e9")
    owned = {str(target_id)}
    for index in range(49):
        garment_id, _ = _seed_garment(factory, owner_id, description=f"Bulk garment {index}")
        owned.add(str(garment_id))
    with factory() as db:
        target = db.scalar(select(Garment).where(Garment.id == target_id))
        target.category, target.color = "shirt", "blue"
        # SQLite defaults have second precision. Place this row explicitly on
        # page two rather than depending on test-machine insertion speed.
        target.created_at = utcnow() - timedelta(days=1)
        db.commit()
    _seed_pending_only(factory, owner_id)
    client.cookies.clear()
    _, other_id = _register(client, origin, "search-other@example.invalid")
    _seed_garment(factory, other_id, description="Blue needle 50%_literal, other owner")
    client.cookies.clear()
    client.post("/auth/login", headers=origin, json={"email": "search-owner@example.invalid", "password": "correct horse battery staple"})
    first = client.get("/garments?page_size=48").json()
    second = client.get("/garments?page=2&page_size=48").json()
    assert first["total"] == second["total"] == 50
    assert len(first["items"]) == 48 and len(second["items"]) == 2
    assert {row["id"] for row in first["items"] + second["items"]} == owned
    assert str(target_id) not in {row["id"] for row in first["items"]}
    for query in ("NEEDLE", "50%_literal", "caf\u00e9"):
        result = client.get("/garments", params={"q": query, "category": "shirt", "color": "blue"}).json()
        assert result["total"] == 1 and result["items"][0]["id"] == str(target_id)
    for params in ({"q": "needle", "color": "red"}, {"q": "missing"}, {"q": "' OR 1=1 --"}):
        assert client.get("/garments", params=params).json()["total"] == 0
    assert client.get("/garments", params={"q": " "}).json()["total"] == 50
    assert client.get("/garments", params={"q": "x" * 201}).status_code == 422


def test_csv_neutralizes_formula_prefixes_and_leading_controls():
    from app.garments.router import _csv_cell
    for value in ("=1+1", " +1", "\t@SUM(1,1)", "\n-1", "\r=1", "\v=1", "\f+1", "\u00a0=1", "\x00=1", "\x7f@x"):
        assert _csv_cell(value) == "'" + value
    assert _csv_cell(None) == ""
    assert _csv_cell('safe, \"quoted\"\ntext') == 'safe, \"quoted\"\ntext'


def test_timestamp_sort_is_stable_across_pages_and_filters(client, origin):
    _, owner_id = _register(client, origin, "sort-owner@example.invalid")
    factory = client.app.state.testing_session_factory
    ids = [_seed_garment(factory, owner_id, description="Sort needle")[0] for _ in range(7)]
    with factory() as db:
        for index, garment_id in enumerate(ids):
            row = db.get(Garment, garment_id)
            row.category = "shirt"
            row.created_at = utcnow().replace(microsecond=0) - timedelta(days=index // 2)
        db.commit()
    def pages(sort):
        return [row["id"] for page in range(1, 4) for row in client.get("/garments", params={
            "sort": sort, "page": page, "page_size": 3, "q": "needle", "category": "shirt",
        }).json()["items"]]
    newest, oldest = pages("newest"), pages("oldest")
    assert len(newest) == len(set(newest)) == 7
    assert oldest == newest[::-1]
    assert client.get("/garments").json()["items"][0]["id"] == newest[0]
    assert client.get("/garments?sort=invalid").status_code == 422
