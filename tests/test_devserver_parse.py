from jarvis.devserver.manager import DevelopmentServerManager


def test_parse_vite_url():
    text = "  ➜  Local:   http://localhost:5173/\n"
    parsed = DevelopmentServerManager.parse_url_port(text)
    assert parsed["port"] == 5173
    assert "5173" in parsed["url"]


def test_parse_next_url():
    text = "ready - started server on 0.0.0.0:3000, url: http://localhost:3000"
    parsed = DevelopmentServerManager.parse_url_port(text)
    assert parsed["port"] == 3000
    assert "127.0.0.1" in parsed["url"] or "localhost" in parsed["url"]


def test_detect_package_json(tmp_path):
    (tmp_path / "package.json").write_text(
        '{"scripts":{"dev":"vite"},"devDependencies":{"vite":"^5.0.0"}}',
        encoding="utf-8",
    )
    mgr = DevelopmentServerManager()
    found = mgr.detect(str(tmp_path))
    assert found
    assert found[0].framework == "vite"
    assert found[0].suggested_port == 5173
