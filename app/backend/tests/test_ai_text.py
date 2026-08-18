"""Только детерминированная часть — сам вызов LLM (действия summarize/
reformat/rewrite при валидном вводе) сознательно не покрыт тестами, см.
tests/README.md."""


async def test_transform_requires_auth(client):
    r = await client.post("/api/ai/transform", json={"action": "summarize", "text": "x"})
    assert r.status_code == 401


async def test_transform_rewrite_without_instruction_rejected(auth_client):
    r = await auth_client.post("/api/ai/transform", json={"action": "rewrite", "text": "some text", "instruction": ""})
    assert r.status_code == 400


async def test_transform_empty_text_rejected(auth_client):
    r = await auth_client.post("/api/ai/transform", json={"action": "summarize", "text": ""})
    assert r.status_code == 422
