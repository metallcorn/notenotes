async def _make_space(auth_client, **kwargs):
    r = await auth_client.post("/api/spaces", json={"name": "Tables", **kwargs})
    return r.json()["id"]


async def test_table_crud_columns_and_rows(auth_client):
    space_id = await _make_space(auth_client)

    r = await auth_client.post(
        "/api/tables", json={"space_id": space_id, "title": "Workouts", "columns": [{"name": "Exercise"}, {"name": "Weight"}]}
    )
    assert r.status_code == 201
    table_id = r.json()["id"]
    columns = r.json()["columns"]
    assert [c["name"] for c in columns] == ["Exercise", "Weight"]
    assert r.json()["rows"] == []

    r = await auth_client.get(f"/api/tables/{table_id}")
    assert r.status_code == 200

    exercise_id, weight_id = columns[0]["id"], columns[1]["id"]
    r = await auth_client.post(f"/api/tables/{table_id}/rows", json={"cells": {exercise_id: "Squat", weight_id: "80"}})
    assert r.status_code == 200
    assert len(r.json()["rows"]) == 1
    row_id = r.json()["rows"][0]["id"]
    assert r.json()["rows"][0]["cells"] == {exercise_id: "Squat", weight_id: "80"}

    r = await auth_client.patch(f"/api/tables/{table_id}/rows/{row_id}", json={"cells": {weight_id: "85"}})
    assert r.status_code == 200
    row = r.json()["rows"][0]
    assert row["cells"][weight_id] == "85"
    assert row["cells"][exercise_id] == "Squat"  # непереданная ячейка не тронута

    r = await auth_client.delete(f"/api/tables/{table_id}/rows/{row_id}")
    assert r.status_code == 200
    assert r.json()["rows"] == []


async def test_table_add_and_delete_column_cleans_cells(auth_client):
    space_id = await _make_space(auth_client)
    r = await auth_client.post("/api/tables", json={"space_id": space_id, "title": "T", "columns": [{"name": "A"}]})
    table_id = r.json()["id"]
    col_a = r.json()["columns"][0]["id"]

    r = await auth_client.post(f"/api/tables/{table_id}/columns", json={"name": "B"})
    assert r.status_code == 200
    assert len(r.json()["columns"]) == 2
    col_b = r.json()["columns"][1]["id"]

    r = await auth_client.post(f"/api/tables/{table_id}/rows", json={"cells": {col_a: "x", col_b: "y"}})
    row_id = r.json()["rows"][0]["id"]

    r = await auth_client.delete(f"/api/tables/{table_id}/columns/{col_b}")
    assert r.status_code == 200
    assert len(r.json()["columns"]) == 1
    row = next(row for row in r.json()["rows"] if row["id"] == row_id)
    assert col_b not in row["cells"]
    assert row["cells"][col_a] == "x"


async def test_table_rename_column(auth_client):
    space_id = await _make_space(auth_client)
    r = await auth_client.post("/api/tables", json={"space_id": space_id, "title": "T", "columns": [{"name": "Old"}]})
    table_id = r.json()["id"]
    col_id = r.json()["columns"][0]["id"]

    r = await auth_client.patch(f"/api/tables/{table_id}/columns/{col_id}", json={"name": "New", "type": "number"})
    assert r.status_code == 200
    assert r.json()["columns"][0]["name"] == "New"
    assert r.json()["columns"][0]["type"] == "number"


async def test_table_delete(auth_client):
    space_id = await _make_space(auth_client)
    r = await auth_client.post("/api/tables", json={"space_id": space_id, "title": "T"})
    table_id = r.json()["id"]
    r = await auth_client.delete(f"/api/items/{table_id}")
    assert r.status_code == 204
    r = await auth_client.get(f"/api/tables/{table_id}")
    assert r.status_code == 404


async def test_table_not_supported_in_vault(auth_client):
    r = await auth_client.post(
        "/api/spaces", json={"name": "V", "is_vault": True, "vault_salt": "s", "vault_verifier": "{}"}
    )
    space_id = r.json()["id"]
    r = await auth_client.post("/api/tables", json={"space_id": space_id, "title": "T"})
    assert r.status_code == 400


async def test_table_export_csv(auth_client):
    space_id = await _make_space(auth_client)
    r = await auth_client.post(
        "/api/tables", json={"space_id": space_id, "title": "T", "columns": [{"name": "A"}, {"name": "B"}]}
    )
    table_id = r.json()["id"]
    col_a, col_b = r.json()["columns"][0]["id"], r.json()["columns"][1]["id"]
    await auth_client.post(f"/api/tables/{table_id}/rows", json={"cells": {col_a: "1", col_b: "2"}})

    r = await auth_client.get(f"/api/tables/{table_id}/export.csv")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/csv")
    body = r.text.replace("\r\n", "\n")
    assert body == "A,B\n1,2\n"
