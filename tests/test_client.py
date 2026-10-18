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


@respx.mock
def test_fiches_acces_pdf(creds, tmp_path):
    respx.post("https://ecole.example/login").mock(return_value=httpx.Response(302, headers={"location": "/"}))
    respx.post("https://ecole.example/api/couponAcces").mock(return_value=httpx.Response(200, content=b"%PDF-1.4 fake"))
    c = cl.MaclasseClient()
    p = c.telecharger_fiches_acces("u", tmp_path / "fiches.pdf")
    assert p.read_bytes().startswith(b"%PDF") and respx.calls.last.request.content == b"uuidProjet=u"
    with pytest.raises(cl.MaclasseError):
        c.telecharger_fiches_acces("u", tmp_path / "fiches.pdf")  # jamais écrasé


@respx.mock
def test_fiches_acces_refuse_html(creds, tmp_path):
    respx.post("https://ecole.example/login").mock(return_value=httpx.Response(302, headers={"location": "/"}))
    respx.post("https://ecole.example/api/couponAcces").mock(return_value=httpx.Response(200, text="<html>"))
    with pytest.raises(cl.MaclasseError):
        cl.MaclasseClient().telecharger_fiches_acces("u", tmp_path / "f.pdf")


@respx.mock
def test_apercu_filigrane(creds, tmp_path):
    respx.get("https://lbcache.maclasse.photo/s1/x/medium/abcd.jpeg").mock(
        return_value=httpx.Response(200, content=b"\xff\xd8jpg", headers={"content-type": "image/jpeg"}))
    c = cl.MaclasseClient()
    p = c.telecharger_apercu("https://lbcache.maclasse.photo/s1/x/small/abcd.jpeg", tmp_path / "a.jpg")
    assert p.read_bytes().startswith(b"\xff\xd8")
    with pytest.raises(cl.MaclasseError):
        c.telecharger_apercu("https://autre.example/x.jpg", tmp_path / "b.jpg")
