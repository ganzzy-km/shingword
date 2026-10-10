def test_library_preferences_use_existing_settings_store(client):
    values = {"theme": "bookshelf", "pageAnimation": False, "bookTexture": False}
    response = client.patch("/api/settings", json=values)
    assert response.status_code == 200
    saved = client.get("/api/settings").get_json()["data"]
    assert all(saved[key] == value for key, value in values.items())
    assert "autosaveInterval" in saved
    assert client.patch("/api/settings", json={"theme": "third-theme"}).status_code == 400
    assert client.patch("/api/settings", json={"pageAnimation": "yes"}).status_code == 400
