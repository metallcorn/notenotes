"""Только детерминированная часть — сам вызов ASR/TTS-провайдера
сознательно не покрыт тестами (реальные внешние API), см. tests/README.md."""


async def test_transcribe_requires_auth(client):
    r = await client.post("/api/voice/transcribe", files={"audio": ("a.webm", b"", "audio/webm")})
    assert r.status_code == 401


async def test_transcribe_empty_file_rejected(auth_client):
    r = await auth_client.post("/api/voice/transcribe", files={"audio": ("a.webm", b"", "audio/webm")})
    assert r.status_code in (400, 503)  # 503, если ASR вообще не настроен в этом окружении
