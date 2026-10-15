import dataclasses

import httpx
import pytest
import respx

from maclasse_mcp import client as cl, config


@pytest.fixture
def creds(monkeypatch):
    monkeypatch.setenv("MACLASSE_EMAIL", "x@example.org")
    monkeypatch.setenv("MACLASSE_PASSWORD", "secret")
    monkeypatch.setattr(cl, "SETTINGS", dataclasses.replace(config.SETTINGS, base_url="https://ecole.example"))


@respx.mock
def test_login_puis_lecture(creds):
    respx.post("https://ecole.example/login").mock(return_value=httpx.Response(302, headers={"location": "/"}))
    respx.get("https://ecole.example/").mock(return_value=httpx.Response(200, text="<html></html>"))
    c = cl.MaclasseClient(base_url="https://ecole.example")
    assert c.prises_de_vues() == []
    assert respx.calls.call_count == 2


@respx.mock
def test_login_refuse(creds):
    respx.post("https://ecole.example/login").mock(return_value=httpx.Response(200, text="<form id='formLogin'>"))
    c = cl.MaclasseClient(base_url="https://ecole.example")
    with pytest.raises(cl.MaclasseError):
        c.prises_de_vues()


@respx.mock
def test_telechargement_refuse_html(creds, tmp_path):
    respx.post("https://ecole.example/login").mock(return_value=httpx.Response(302, headers={"location": "/"}))
    respx.get("https://ecole.example/vignettesParticipants/u.zip").mock(return_value=httpx.Response(200, text="<html>", headers={"content-type": "text/html"}))
    c = cl.MaclasseClient(base_url="https://ecole.example")
    with pytest.raises(cl.MaclasseError):
        c.telecharger_vignettes("u", tmp_path / "v.zip")
    assert not (tmp_path / "v.zip").exists() or (tmp_path / "v.zip").stat().st_size == 0
