"""Identification des photos de fratries maclasse.photo par rapprochement de visages avec les photos individuelles.

Contexte : le photographe nomme les photos de fratries « Fratrie NN.jpg » (aucun nom de famille) et la plateforme
ne sait pas qui est dessus. Ce script compare, EN LOCAL, chaque visage d'une photo de fratrie aux photos individuelles
déjà rapprochées des élèves Charlemagne (charlemagne_ideleve/IDELEVE.jpg), sous la contrainte que les enfants d'une
même photo appartiennent à une même fratrie Charlemagne (enfants partageant un responsable).

Il produit des PROPOSITIONS à valider par une personne (planche PDF), jamais une décision finale. Les empreintes de
visages ne sont pas conservées (calculées en mémoire). Données biométriques de mineurs : usage interne à l'école,
une seule fois par campagne, résultats dans un dossier non diffusé.

Dépendances optionnelles : pip install "maclasse-mcp[fratries]" (insightface, onnxruntime, opencv-python-headless,
reportlab) ; le modèle buffalo_l (~280 Mo) est téléchargé au premier lancement dans ~/.insightface.

Usage :
  python -m maclasse_mcp.fratries --fratries <dossier vignettes de la classe Fratries> \
      --eleves <dossier charlemagne_ideleve> --index <index_photos_eleves.csv> \
      --db <administration_consolidee.db> --sortie <dossier fratries>
Sorties : fratries_charlemagne.json, fratries_identification.csv, fratries_validation.pdf, fratries_sans_photo.csv,
noms_fratries_maclasse.csv + association_fratries.json (pour maclasse_importer_noms_prepare / maclasse_associer_noms_prepare),
par_famille/ (copies renommées).
"""
from __future__ import annotations

import argparse
import collections
import csv
import itertools
import json
import os
import re
import shutil
import sqlite3
import sys
from pathlib import Path


def fratries_charlemagne(db: Path, index_csv: Path) -> list[dict]:
    """Groupes d'élèves présents partageant au moins un responsable (COM_LIENER), ≥ 2 enfants."""
    c = sqlite3.connect(str(db))
    pres = {r[0] for r in c.execute("select IDELEVE from COM_ELEVES where EL_DATE_SORTIE is null or EL_DATE_SORTIE=''")}
    liens = c.execute("select IDELEVE, IDRESPONSABLE from COM_LIENER").fetchall()
    resp = {r[0]: (r[1] or "") for r in c.execute("select IDRESPONSABLE, RE_NOM1 from COM_RESPONSABLES")}
    parent: dict = {}

    def find(x):
        while parent.get(x, x) != x:
            x = parent[x]
        return x

    for ide, idr in liens:
        if ide in pres:
            a, b = find(("e", ide)), find(("r", idr))
            if a != b:
                parent[a] = b
    groupes: dict = collections.defaultdict(lambda: {"eleves": [], "responsables": set()})
    for ide, idr in liens:
        if ide in pres:
            g = groupes[find(("e", ide))]
            if ide not in g["eleves"]:
                g["eleves"].append(ide)
            g["responsables"].add(idr)
    idx = {r["ideleve"]: r for r in csv.DictReader(open(index_csv, encoding="utf-8"), delimiter=";")}
    out = []
    for g in groupes.values():
        if len(g["eleves"]) < 2:
            continue
        noms = sorted({resp[r] for r in g["responsables"] if resp.get(r)})
        out.append({"id": f"F{len(out) + 1:03d}", "familles": " / ".join(noms),
                    "enfants": [{"id": str(e), "nom": idx.get(str(e), {}).get("nom", ""), "prenom": idx.get(str(e), {}).get("prenom", ""),
                                 "classe": idx.get(str(e), {}).get("classe_charlemagne", "")} for e in g["eleves"]]})
    return out


def _embeddings(app, path: Path, scale_max: int = 640, un_seul: bool = False):
    import cv2
    img = cv2.imread(str(path))
    if img is None:
        return []
    h, w = img.shape[:2]
    scale = scale_max / max(h, w)
    img = cv2.resize(img, (int(w * scale), int(h * scale)))
    faces = sorted(app.get(img), key=lambda f: f.bbox[0])
    out = [(f.normed_embedding, [float(x) / scale for x in f.bbox]) for f in faces]
    if un_seul and len(out) > 1:
        out = [max(out, key=lambda t: (t[1][2] - t[1][0]) * (t[1][3] - t[1][1]))]
    return out


def identifier(fratries_dir: Path, eleves_dir: Path, groupes: list[dict], penalite: float = 0.03) -> list[dict]:
    import numpy as np
    from insightface.app import FaceAnalysis

    app = FaceAnalysis(name="buffalo_l", providers=["CPUExecutionProvider"])
    app.prepare(ctx_id=0, det_size=(640, 640))
    E: dict[str, object] = {}
    for f in sorted(eleves_dir.glob("*.jpg")):
        e = _embeddings(app, f, un_seul=True)
        if e:
            E[f.stem] = e[0][0]
    print(f"élèves avec visage : {len(E)}", file=sys.stderr)

    def score(faces, g):
        kids = [k for k in g["enfants"] if k["id"] in E]
        if not kids:
            return -1, []
        n = min(len(faces), len(kids))
        best = (-1.0, [])
        for perm in itertools.permutations(range(len(kids)), n):
            for fsel in itertools.combinations(range(len(faces)), n):
                det = [(fi, kids[ki], float(np.dot(faces[fi][0], E[kids[ki]["id"]]))) for fi, ki in zip(fsel, perm)]
                s = sum(d[2] for d in det) / n
                if s > best[0]:
                    best = (s, det)
        return best[0] - penalite * abs(len(faces) - len(kids)), best[1]

    rows = []
    for f in sorted(fratries_dir.glob("*.jpg")):
        faces = _embeddings(app, f)
        if not faces:
            rows.append({"code": f.stem, "nb_visages": 0, "enfants": [], "familles": "", "score": 0, "marge": 0})
            continue
        cands = sorted(((*score(faces, g), g) for g in groupes), key=lambda t: -t[0])
        s1, d1, g1 = cands[0]
        s2, _, g2 = cands[1]
        rows.append({"code": f.stem, "nb_visages": len(faces), "fratrie_id": g1["id"], "familles": g1["familles"],
                     "enfants": [{"id": k["id"], "nom": k["nom"], "prenom": k["prenom"], "classe": k["classe"], "sim": round(sim, 3)} for _, k, sim in d1],
                     "score": round(s1, 3), "marge": round(s1 - s2, 3), "candidat2": {"familles": g2["familles"], "score": round(s2, 3)}})
    return rows


def libelle(r: dict) -> tuple[str, str]:
    noms: list[str] = []
    for e in r["enfants"]:
        if e["nom"] not in noms:
            noms.append(e["nom"])
    pr = [e["prenom"] for e in r["enfants"]]
    return " / ".join(noms), (pr[0] if len(pr) == 1 else ", ".join(pr[:-1]) + " et " + pr[-1])


def ecrire_sorties(rows: list[dict], groupes: list[dict], fratries_dir: Path, eleves_dir: Path, sortie: Path) -> dict:
    sortie.mkdir(parents=True, exist_ok=True)
    rows = sorted(rows, key=lambda r: (r["familles"], r["code"]))
    with open(sortie / "fratries_identification.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(["code_acces", "familles", "enfants", "classes", "ideleves", "nb_visages", "similarite_min", "marge_vs_2e", "a_verifier"])
        for r in rows:
            sims = [e["sim"] for e in r["enfants"]] or [0]
            w.writerow([r["code"], r["familles"], " ; ".join(f"{e['nom']} {e['prenom']}" for e in r["enfants"]),
                        " ; ".join(e["classe"] for e in r["enfants"]), " ; ".join(e["id"] for e in r["enfants"]),
                        r["nb_visages"], min(sims), r["marge"], "oui" if (min(sims) < 0.5 or r["marge"] < 0.2 or not r["enfants"]) else "non"])
    assoc = []
    with open(sortie / "noms_fratries_maclasse.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(["Nom", "Prénom"])
        for r in rows:
            if not r["enfants"]:
                continue
            n, p = libelle(r)
            w.writerow([n, p])
            assoc.append({"nom": n, "prenom": p, "code": r["code"]})
    json.dump(assoc, open(sortie / "association_fratries.json", "w"), ensure_ascii=False, indent=1)
    (sortie / "par_famille").mkdir(exist_ok=True)
    for r in rows:
        if not r["enfants"]:
            continue
        n, p = libelle(r)
        nom_sur = re.sub(r"[^\w\s\-]", "", n)
        dest = sortie / "par_famille" / f"{nom_sur} - {p} ({r['code']}).jpg"
        if not dest.exists():
            shutil.copy2(fratries_dir / f"{r['code']}.jpg", dest)
    vues = {r.get("fratrie_id") for r in rows}
    with open(sortie / "fratries_sans_photo.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(["familles", "enfants", "classes"])
        for g in groupes:
            if g["id"] not in vues:
                w.writerow([g["familles"], " ; ".join(f"{e['nom']} {e['prenom']}" for e in g["enfants"]), " ; ".join(e["classe"] for e in g["enfants"])])
    planche(rows, fratries_dir, eleves_dir, sortie / "fratries_validation.pdf")
    return {"photos": len(rows), "identifiees": sum(1 for r in rows if r["enfants"]),
            "a_verifier": sum(1 for r in rows if not r["enfants"] or min(e["sim"] for e in r["enfants"]) < 0.5 or r["marge"] < 0.2),
            "fratries_sans_photo": sum(1 for g in groupes if g["id"] not in vues)}


def planche(rows: list[dict], fratries_dir: Path, eleves_dir: Path, pdf: Path) -> None:
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.pdfgen import canvas

    for cand in ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/Library/Fonts/Arial Unicode.ttf", "/System/Library/Fonts/Supplemental/Arial.ttf"):
        if os.path.exists(cand):
            pdfmetrics.registerFont(TTFont("F", cand))
            font = "F"
            break
    else:
        font = "Helvetica"
    c = canvas.Canvas(str(pdf), pagesize=A4)
    W, H = A4
    per, p = 4, 1

    def header():
        c.setFont(font, 11)
        c.drawString(15 * mm, H - 12 * mm, "Photos de fratries — identification proposée, à valider")
        c.setFont(font, 8)
        c.drawString(15 * mm, H - 17 * mm, f"Page {p}/{(len(rows) + per - 1) // per} — photo de fratrie à gauche, photos individuelles des enfants proposés à droite. Document interne, ne pas diffuser.")

    header()
    for i, r in enumerate(rows):
        k = i % per
        if k == 0 and i > 0:
            c.showPage()
            p += 1
            header()
        y = H - 25 * mm - k * 63 * mm
        c.drawImage(str(fratries_dir / f"{r['code']}.jpg"), 15 * mm, y - 45 * mm, width=60 * mm, height=45 * mm)
        c.setFont(font, 10)
        c.drawString(80 * mm, y - 4 * mm, r["familles"] or "(aucune fratrie proposée)")
        c.setFont(font, 8)
        c.drawString(80 * mm, y - 9 * mm, f"code {r['code']} · {r['nb_visages']} visage(s) · marge avec la 2e famille candidate {r['marge']:.2f}")
        x = 80 * mm
        for e in r["enfants"]:
            c.drawImage(str(eleves_dir / f"{e['id']}.jpg"), x, y - 40 * mm, width=22 * mm, height=29 * mm)
            c.setFont(font, 6.5)
            c.drawString(x, y - 43.5 * mm, e["prenom"][:18])
            c.drawString(x, y - 46.5 * mm, e["nom"][:18])
            c.drawString(x, y - 49.5 * mm, f"{e['classe']} · sim {e['sim']:.2f}")
            x += 27 * mm
        c.setFont(font, 8)
        c.drawString(15 * mm, y - 49.5 * mm, "Validé [ ]    À corriger [ ]  ______________________")
    c.save()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--fratries", required=True, type=Path, help="dossier des vignettes de la classe Fratries (<code>.jpg)")
    ap.add_argument("--eleves", required=True, type=Path, help="dossier charlemagne_ideleve (<IDELEVE>.jpg)")
    ap.add_argument("--index", required=True, type=Path, help="index_photos_eleves.csv")
    ap.add_argument("--db", required=True, type=Path, help="administration_consolidee.db (COM_ELEVES, COM_LIENER, COM_RESPONSABLES)")
    ap.add_argument("--sortie", required=True, type=Path)
    a = ap.parse_args(argv)
    if a.sortie.exists() and any(a.sortie.iterdir()):
        print(f"dossier de sortie non vide, rien n'est écrasé : {a.sortie}", file=sys.stderr)
        return 2
    groupes = fratries_charlemagne(a.db, a.index)
    a.sortie.mkdir(parents=True, exist_ok=True)
    json.dump(groupes, open(a.sortie / "fratries_charlemagne.json", "w"), ensure_ascii=False, indent=1)
    print(f"fratries Charlemagne : {len(groupes)}", file=sys.stderr)
    rows = identifier(a.fratries, a.eleves, groupes)
    bilan = ecrire_sorties(rows, groupes, a.fratries, a.eleves, a.sortie)
    print(json.dumps(bilan, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
