import pytest
import respx
import httpx
from update_ip.bark_notifier import BarkNotifier


@pytest.mark.asyncio
async def test_bark_not_configured():
    notifier = BarkNotifier(bark_key=None)
    assert not notifier.is_configured()
    success, msg = await notifier.send("Title", "Body")
    assert not success
    assert "not configured" in msg


@pytest.mark.asyncio
async def test_bark_send_success():
    notifier = BarkNotifier(
        bark_key="test_device_key",
        bark_server="https://api.day.app",
        default_group="TestGroup",
    )
    assert notifier.is_configured()

    with respx.mock(assert_all_called=True) as respx_mock:
        route = respx_mock.post("https://api.day.app/push").respond(
            200,
            json={"code": 200, "message": "success", "timestamp": 1234567890},
        )
        success, msg = await notifier.send(
            title="IP Changed",
            body="New IP: 1.2.3.4",
            sound="minuet",
        )
        assert success
        assert "Success" in msg
        assert route.called

        # Check payload
        request = route.calls.last.request
        data = httpx.Response(200, content=request.content).json()
        assert data["device_key"] == "test_device_key"
        assert data["title"] == "IP Changed"
        assert data["body"] == "New IP: 1.2.3.4"
        assert data["group"] == "TestGroup"
        assert data["sound"] == "minuet"


@pytest.mark.asyncio
async def test_bark_send_fallback_404():
    notifier = BarkNotifier(
        bark_key="my_key",
        bark_server="https://custom.bark.server",
    )
    with respx.mock(assert_all_called=True) as respx_mock:
        # /push returns 404
        respx_mock.post("https://custom.bark.server/push").respond(404)
        # fallback to /{key} returns 200
        respx_mock.post("https://custom.bark.server/my_key").respond(
            200,
            json={"code": 200, "message": "success"},
        )
        success, msg = await notifier.send("Title", "Body")
        assert success


@pytest.mark.asyncio
async def test_bark_server_error():
    notifier = BarkNotifier(bark_key="my_key")
    with respx.mock(assert_all_called=True) as respx_mock:
        respx_mock.post("https://api.day.app/push").respond(500, text="Internal Server Error")
        success, msg = await notifier.send("Title", "Body")
        assert not success
        assert "500" in msg


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [
    "<html>Proxy login required</html>",
    "null",
    "[]",
    "{}",
    '{"code": 500, "message": "success"}',
])
async def test_bark_rejects_invalid_success_response(body):
    notifier = BarkNotifier(bark_key="my_key")
    with respx.mock(assert_all_called=True) as respx_mock:
        respx_mock.post("https://api.day.app/push").respond(200, text=body)
        success, msg = await notifier.send("Title", "Body")

    assert not success
    assert msg
