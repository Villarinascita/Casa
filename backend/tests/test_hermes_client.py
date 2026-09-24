import httpx
import pytest

from app.hermes_client import HermesClient, HermesUnavailable
from app.security import Ctx


def test_hermes_output_is_parsed_as_actions():
    def respond(request):
        assert request.url.path == "/v1/chat/completions"
        assert request.headers["authorization"] == "Bearer secret"
        return httpx.Response(200, json={"choices": [{"message": {"content":
            '{"actions":[{"kind":"shopping","data":{"label":"Latte"}}]}'}}]})

    client = HermesClient("http://hermes:8642", "secret", "insieme",
                          httpx.Client(transport=httpx.MockTransport(respond)))
    result = client.interpret("Aggiungi latte", Ctx("u", "luca", "h", "admin"), "Europe/Rome")
    assert result["actions"][0]["data"]["label"] == "Latte"


def test_hermes_invalid_json_fails_closed():
    client = HermesClient("http://hermes:8642", "secret", "insieme",
                          httpx.Client(transport=httpx.MockTransport(
                              lambda request: httpx.Response(200, json={"choices": [
                                  {"message": {"content": "Ho salvato tutto."}}]}))))
    with pytest.raises(HermesUnavailable):
        client.interpret("Aggiungi latte", Ctx("u", "luca", "h", "admin"), "Europe/Rome")
