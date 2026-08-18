async def test_list_skills_reflects_disabled_tools(auth_client, db_session, test_user):
    r = await auth_client.get("/api/skills")
    assert r.status_code == 200
    skills = r.json()
    assert len(skills) > 0
    assert all(s["enabled"] for s in skills)

    toggleable = next(s for s in skills if s["toggleable"])
    test_user.disabled_tools = [toggleable["name"]]
    await db_session.commit()

    r = await auth_client.get("/api/skills")
    skills = r.json()
    disabled = next(s for s in skills if s["name"] == toggleable["name"])
    assert disabled["enabled"] is False
