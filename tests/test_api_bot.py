import uuid

from backend.config import settings
from telegram_bot.locales import TEXT, tr


def auth():
    return {"Authorization": "Bearer " + settings().service_token.get_secret_value()}


def test_authorization_and_body_validation(client):
    assert client.get("/admin/999/stats").status_code == 401
    assert client.get("/admin/123/stats", headers=auth()).status_code == 403
    assert client.post("/v1/activate", json={"key": "bad", "device_id": "IMEI"}).status_code == 422
    assert client.post("/bot/5/register", json={"username": "name"}, headers=auth()).status_code == 200
    assert (
        client.post(
            "/bot/5/purchase",
            json={"plan_id": "1", "expected_amount": "20", "request_key": "q", "admin": True},
            headers=auth(),
        ).status_code
        == 422
    )


def test_full_license_api_contract(client):
    client.post("/bot/5/register", json={}, headers=auth())
    lic = client.post("/bot/5/trial", headers=auth()).json()
    assert lic["expires_at"] is None
    activated = client.post("/v1/activate", json={"key": lic["key"], "device_id": str(uuid.uuid4())})
    assert activated.status_code == 200
    token = activated.json()["session_token"]
    response = client.get("/v1/license", headers={"Authorization": "Bearer " + token})
    assert response.status_code == 200
    assert response.json()["status"] == "active"
    assert "key" not in response.json()
    assert "key_ciphertext" not in response.json()
    assert response.headers["cache-control"] == "no-store"
    assert client.get("/bot/6/licenses/" + lic["id"], headers=auth()).status_code == 404


def test_rate_limit_shared_database(client):
    for _ in range(30):
        assert client.get("/v1/updates").status_code == 200
    assert client.get("/v1/updates").status_code == 429


def test_languages_and_complete_menu_callback_routing():
    from telegram_bot.main import menu

    for key, templates in TEXT.items():
        assert len(templates) == 3 and all(templates), key
    for lang in ["ru", "uk", "en"]:
        rows = menu(lang).inline_keyboard
        assert len(rows) == 11
        assert tr(lang, "shop") == rows[3][0].text
        assert {row[0].callback_data for row in rows} == {
            "profile",
            "keys",
            "trial",
            "shop",
            "wallet",
            "referrals",
            "promo",
            "channel",
            "support",
            "settings",
            "menu",
        }
