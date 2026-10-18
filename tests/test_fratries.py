"""Tests hors ligne du module fratries (données synthétiques, pas de modèle de visages)."""
import csv
import sqlite3

from maclasse_mcp import fratries


def test_libelle():
    r = {"enfants": [{"nom": "X", "prenom": "A"}, {"nom": "X", "prenom": "B"}, {"nom": "Y", "prenom": "C"}]}
    assert fratries.libelle(r) == ("X / Y", "A, B et C")
    assert fratries.libelle({"enfants": [{"nom": "X", "prenom": "A"}, {"nom": "X", "prenom": "B"}]}) == ("X", "A et B")


def test_fratries_charlemagne(tmp_path):
    db = tmp_path / "a.db"
    c = sqlite3.connect(db)
    c.executescript("""
      create table COM_ELEVES(IDELEVE, EL_DATE_SORTIE);
      create table COM_LIENER(IDELEVE, IDRESPONSABLE);
      create table COM_RESPONSABLES(IDRESPONSABLE, RE_NOM1);
      insert into COM_ELEVES values (1,''),(2,''),(3,''),(4,'20250630'),(5,'');
      insert into COM_LIENER values (1,10),(1,11),(2,10),(3,12),(4,12),(5,13);
      insert into COM_RESPONSABLES values (10,'DUR'),(11,'BEL'),(12,'LEM'),(13,'SOL');
    """)
    c.commit()
    idx = tmp_path / "index.csv"
    with open(idx, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(["ideleve", "nom", "prenom", "classe_charlemagne"])
        for i, n in enumerate(["A", "B", "C", "D", "E"], 1):
            w.writerow([i, "N" + n, "P" + n, "CP A"])
    g = fratries.fratries_charlemagne(db, idx)
    assert len(g) == 1 and g[0]["familles"] == "BEL / DUR"      # 1 et 2 partagent le responsable 10 ; 4 est sorti ; 5 seul
    assert sorted(e["id"] for e in g[0]["enfants"]) == ["1", "2"]
