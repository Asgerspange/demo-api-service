"""Stage 18 — collections + shared external refs at the repo layer."""
import pytest

from app.storage.repos import CollectionRepo, DemoRepo, RefRepo, UserRepo

pytestmark = pytest.mark.integration


async def _owner(db, email="coll@x.com"):
    return await UserRepo(db).create(email)


async def test_collection_get_or_create_is_idempotent_per_match(db):
    uid = await _owner(db)
    cr = CollectionRepo(db)
    c1 = await cr.get_or_create(uid, source="hltv", external_id="2378001", name="match")
    c2 = await cr.get_or_create(uid, source="hltv", external_id="2378001", name="match again")
    assert c1 == c2                                   # same (owner, source, match) → same collection
    # a different owner with the same match id gets a distinct collection
    uid2 = await _owner(db, "other@x.com")
    assert await cr.get_or_create(uid2, source="hltv", external_id="2378001") != c1


async def test_ad_hoc_collections_without_a_ref_are_distinct(db):
    uid = await _owner(db)
    cr = CollectionRepo(db)
    a = await cr.get_or_create(uid, source=None, external_id=None, name="upload A")
    b = await cr.get_or_create(uid, source=None, external_id=None, name="upload B")
    assert a != b                                     # NULL ref → never merged


async def test_demos_link_to_a_collection_and_list_back(db):
    uid = await _owner(db)
    cid = await CollectionRepo(db).get_or_create(uid, source="hltv", external_id="55", name="bo3")
    demos = DemoRepo(db)
    ids = []
    for i, mp in enumerate(("de_nuke", "de_mirage", "de_inferno")):
        did = await demos.create(uid, f"{i:064d}", mp, mp, status="ready", collection_id=cid)
        ids.append(did)
    listed = await demos.list_for_collection(cid)
    assert [d["id"] for d in listed] == ids
    assert {d["map"] for d in listed} == {"de_nuke", "de_mirage", "de_inferno"}


async def test_shared_ref_resolves_to_all_maps(db):
    uid = await _owner(db)
    demos, refs = DemoRepo(db), RefRepo(db)
    a = await demos.create(uid, "a" * 64, "de_nuke", "A", status="ready")
    b = await demos.create(uid, "b" * 64, "de_mirage", "B", status="ready")
    await refs.add(a, "hltv", "777", uid)
    await refs.add(b, "hltv", "777", uid)
    await refs.add(a, "hltv", "777", uid)   # idempotent per (demo, source, ext, user)

    all_refs = await refs.resolve_all("hltv", "777", uid)
    assert {r["demo_id"] for r in all_refs} == {a, b}
    assert len(all_refs) == 2          # no duplicate from the repeat add


async def test_shared_demo_appears_in_each_tenants_collection(db):
    # A demo deduped across tenants must show up in EACH tenant's own collection (membership is
    # many-to-many), not only the first ingester's.
    demos = DemoRepo(db)
    uid_a = await _owner(db, "coll-a@x.com")
    uid_b = await _owner(db, "coll-b@x.com")

    coll_a = await CollectionRepo(db).get_or_create(uid_a, source="hltv", external_id="900", name="A")
    demo_id = await demos.create(uid_a, "d" * 64, "de_nuke", "shared", status="ready",
                                 collection_id=coll_a)

    # tenant B dedups to the same demo and files it under B's own collection
    coll_b = await CollectionRepo(db).get_or_create(uid_b, source="hltv", external_id="900", name="B")
    await demos.grant_access(demo_id, uid_b)
    await demos.add_to_collection(demo_id, coll_b)

    assert coll_a != coll_b
    assert [d["id"] for d in await demos.list_for_collection(coll_a)] == [demo_id]
    assert [d["id"] for d in await demos.list_for_collection(coll_b)] == [demo_id]
