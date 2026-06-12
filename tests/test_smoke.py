from forward_nautobot.views import ForwardHomeView
from forward_nautobot.views import ForwardStatusView


def _content_text(response):
    content = response.content
    return content.decode() if isinstance(content, bytes) else content


def test_smoke_renders_key_cards_and_links():
    home = ForwardHomeView().get()
    status = ForwardStatusView().get()

    assert home.status_code == 200
    assert status.status_code == 200

    for response in (home, status):
        text = _content_text(response)
        assert "Forward Nautobot Dashboard" in text or "Forward Status" in text
        assert "Saved profiles" in text
        assert "Ready profiles" in text
        assert "Last snapshot" in text
        assert "Ingestion coverage" in text
        assert 'href="/plugins/forward_nautobot/configuration/"' in text
        assert 'href="/plugins/forward_nautobot/"' in text
        assert 'href="/plugins/forward_nautobot/diagnostics/"' in text

    status_text = _content_text(status)
    home_text = _content_text(home)
    assert "Forward Status" in status_text
    assert "Profile Status" in status_text
    assert "ipv4_prefixes" in home_text
    assert "modules" in home_text
