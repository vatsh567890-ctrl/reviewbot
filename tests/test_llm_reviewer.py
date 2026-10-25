"""Unit tests for optional LLM architectural reviewer."""

import httpx
import respx

from reviewbot.llm.reviewer import LLMReviewer


def test_llm_reviewer_disabled_without_api_key(monkeypatch):
    monkeypatch.delenv("REVIEWBOT_LLM_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("LLM_API_KEY", raising=False)

    reviewer = LLMReviewer(api_key=None)
    assert not reviewer.is_configured
    result = reviewer.review_diff("src/service.py", "@@ -1 +1 @@\n+foo\n")
    assert result is None


@respx.mock
def test_llm_reviewer_successful_review():
    reviewer = LLMReviewer(api_key="test-secret-key", base_url="https://api.openai.com/v1")
    assert reviewer.is_configured

    mock_response = {
        "choices": [
            {
                "message": {
                    "content": "- Consider adding timeouts to network calls.\n- Use connection pooling."
                }
            }
        ]
    }

    route = respx.post("https://api.openai.com/v1/chat/completions").mock(
        return_value=httpx.Response(200, json=mock_response)
    )

    patch = "@@ -1,3 +1,4 @@\n def fetch():\n+    return requests.get(url)\n"
    feedback = reviewer.review_diff("src/service.py", patch)

    assert feedback is not None
    assert "Consider adding timeouts" in feedback
    assert route.called
    sent_body = route.calls.last.request.read().decode("utf-8")
    assert "src/service.py" in sent_body


@respx.mock
def test_llm_reviewer_handles_api_error():
    reviewer = LLMReviewer(api_key="test-secret-key", base_url="https://api.openai.com/v1")

    respx.post("https://api.openai.com/v1/chat/completions").mock(
        return_value=httpx.Response(500, text="Internal Server Error")
    )

    feedback = reviewer.review_diff("src/service.py", "@@ -1 +1 @@\n+x = 1\n")
    # Must fail gracefully without raising an exception
    assert feedback is None
