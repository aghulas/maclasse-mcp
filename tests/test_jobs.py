import time

from maclasse_mcp import server


def test_preparer_en_arriere_plan(tmp_path, monkeypatch):
    appels = []

    def faux(**kw):
        appels.append(kw)
        time.sleep(0.3)
        return {"photos_copiees": 1, "silhouettes": []}

    monkeypatch.setattr(server, "_preparer", faux)
    r = server.maclasse_preparer_photos("u", "liste.json", {}, sortie=str(tmp_path / "out"))
    assert r["etat"] == "en_cours" and r["job"]
    assert server.maclasse_rapport(job=r["job"])["etat"] == "en_cours"
    time.sleep(0.6)
    s = server.maclasse_rapport(job=r["job"])
    assert s["etat"] == "termine" and s["resultat"]["photos_copiees"] == 1
    assert appels[0]["out_dir"] == tmp_path / "out"
    assert any(j["job"] == r["job"] for j in server.maclasse_rapport()["jobs"])


def test_preparer_erreur_visible(tmp_path, monkeypatch):
    def casse(**kw):
        raise RuntimeError("plateforme indisponible")

    monkeypatch.setattr(server, "_preparer", casse)
    r = server.maclasse_preparer_photos("u", "liste.json", {}, sortie=str(tmp_path / "out2"))
    time.sleep(0.3)
    s = server.maclasse_rapport(job=r["job"])
    assert s["etat"] == "erreur" and "plateforme indisponible" in s["erreur"]


def test_preparer_refuse_dossier_non_vide(tmp_path):
    d = tmp_path / "plein"
    d.mkdir()
    (d / "x.txt").write_text("x")
    try:
        server.maclasse_preparer_photos("u", "liste.json", {}, sortie=str(d))
    except server.MaclasseError:
        return
    raise AssertionError("un dossier non vide doit être refusé")
