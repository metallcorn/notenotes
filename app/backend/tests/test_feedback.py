async def test_feedback_anonymous_and_listed_by_auth(client, auth_client):
    r = await client.post("/api/feedback", data={"message": "Нашёл баг", "page_url": "/notes"})
    assert r.status_code == 201

    r = await client.get("/api/feedback")
    assert r.status_code == 401  # список требует авторизации

    r = await auth_client.get("/api/feedback")
    assert r.status_code == 200
    assert any(f["message"] == "Нашёл баг" for f in r.json())


async def test_feedback_empty_message_rejected(client):
    r = await client.post("/api/feedback", data={"message": "   "})
    assert r.status_code == 400
