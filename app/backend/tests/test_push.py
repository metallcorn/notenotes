async def test_vapid_public_key(client):
    r = await client.get("/api/push/vapid-public-key")
    assert r.status_code == 200
    assert "key" in r.json()


async def test_subscribe_update_unsubscribe(auth_client):
    payload = {"endpoint": "https://push.example/abc", "p256dh": "key1", "auth": "auth1"}
    r = await auth_client.post("/api/push/subscribe", json=payload)
    assert r.status_code == 204

    # тот же endpoint снова — обновление на месте, не конфликт
    payload["p256dh"] = "key2"
    r = await auth_client.post("/api/push/subscribe", json=payload)
    assert r.status_code == 204

    r = await auth_client.post("/api/push/unsubscribe", json={"endpoint": payload["endpoint"]})
    assert r.status_code == 204
