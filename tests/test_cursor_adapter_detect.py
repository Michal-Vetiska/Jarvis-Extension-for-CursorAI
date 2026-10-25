from jarvis.cursor_adapter import CursorAgentAdapter


def test_detect_installation_shape():
    adapter = CursorAgentAdapter()
    info = adapter.detect_installation()
    assert "cursor_cli" in info
    assert "agent_cli" in info
    assert "cursor_app" in info
    assert "ok" in info


def test_summarize_stream_json():
    adapter = CursorAgentAdapter()
    output = '\n'.join(
        [
            '{"type":"assistant","message":{"content":[{"type":"text","text":"Hotovo"}]}}',
            "not-json",
        ]
    )
    text = adapter.summarize_stream_json(output)
    assert "Hotovo" in text
