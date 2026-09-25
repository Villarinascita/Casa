import httpx
import pytest

from app.hermes_client import HermesClient, HermesInvalidResponse, HermesUnavailable
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


def test_analyze_email_accepts_bills_and_requires_categories_in_prompt():
    captured = {}

    def respond(request):
        captured["body"] = request.content.decode()
        return httpx.Response(200, json={"choices": [{"message": {"content":
            '{"actions":[],"bills":[{"category":"Bollette","title":"Luce","amount":45.5}]}'}}]})

    client = HermesClient("http://hermes:8642", "secret", "insieme",
                          httpx.Client(transport=httpx.MockTransport(respond)))
    result = client.analyze_email("Bolletta luce 45,50€", "Europe/Rome", "insieme-email",
                                  ["Bollette", "Auto e assicurazione", "Altro"])
    assert result["bills"][0]["title"] == "Luce"
    assert "Bollette" in captured["body"] and "Auto e assicurazione" in captured["body"]


def test_analyze_email_rejects_non_list_bills():
    def respond(request):
        return httpx.Response(200, json={"choices": [{"message": {"content":
            '{"actions":[],"bills":"non è una lista"}'}}]})

    client = HermesClient("http://hermes:8642", "secret", "insieme",
                          httpx.Client(transport=httpx.MockTransport(respond)))
    with pytest.raises(HermesInvalidResponse):
        client.analyze_email("x", "Europe/Rome", "insieme-email", ["Altro"])
