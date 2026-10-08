import re


def test_settings_groups_management_without_changing_routes(logged_in):
    response = logged_in.get("/dashboard")
    assert response.status_code == 200
    navigation = re.search(r'<nav id="workspace-nav".*?</nav>', response.text, re.S).group(0)
    for path in ("/providers", "/operations", "/audit"):
        assert f'href="{path}"' not in navigation
        assert f'href="{path}"' in response.text
        detail = logged_in.get(path)
        assert detail.status_code == 200
        assert 'class="settings-breadcrumb"' in detail.text
    assert "Appearance settings" not in response.text
    assert 'id="settings-dialog"' in response.text
    assert 'id="appearance-title">Appearance' in response.text
    assert 'href="/imports"' in navigation


def test_guest_settings_only_exposes_appearance(client):
    response = client.get("/login")
    assert response.status_code == 200
    assert 'id="settings-dialog"' in response.text
    assert 'id="theme-choice"' in response.text
    for path in ("/providers", "/operations", "/audit"):
        assert f'href="{path}"' not in response.text
        protected = client.get(path, follow_redirects=False)
        assert protected.status_code == 303
        assert protected.headers["location"] == "/login"
