"""Préparation des photos pour Charlemagne et Edumoov à partir des exports maclasse.photo.

Principe : le trombinoscope « nom de l'élève » (= code d'accès tant qu'aucun nom n'est associé)
et le trombinoscope « nom de la photo » (= nom de fichier du photographe, `NOM Prénom.jpg`)
listent les photos dans le même ordre. On en déduit, par position, la correspondance
fichier du ZIP ↔ nom du photographe, puis on rapproche ce nom de la liste Charlemagne (IDELEVE).

Aucun appariement douteux n'est décidé en silence : il est listé « à arbitrer » dans le rapport.
Fonctions pures (fichiers locaux uniquement) — réutilisées par l'outil MCP et par le script CLI.
"""
from __future__ import annotations

import csv
import datetime
import difflib
import json
import os
import re
import shutil
import zipfile
from pathlib import Path
from typing import Any

from .parsing import normaliser

CODE_LIKE = re.compile(r"^[A-Z0-9]{6,12}$")
POIDS_MAX = 100_000  # Aplim : « poids maxi des fichiers image 100 ko », résolution conseillée 480×640, .jpg


def est_silhouette(path: Path, max_couleurs: int = 300) -> bool:
    """Vrai si l'image est le pictogramme gris « pas de photo » du photographe (très peu de couleurs distinctes)."""
    from PIL import Image

    with Image.open(path) as im:
        couleurs = im.convert("RGB").getcolors(maxcolors=max_couleurs + 1)
    return couleurs is not None and len(couleurs) <= max_couleurs


def optimiser_jpeg(src: Path, dest: Path) -> int:
    """Copie en JPEG sans métadonnées (EXIF, GPS, orientation) et sous POIDS_MAX en baissant la qualité si besoin."""
    from PIL import Image

    with Image.open(src) as im:
        im = im.convert("RGB")
        q = 92
        while True:
            im.save(dest, "JPEG", quality=q, optimize=True)
            if dest.stat().st_size <= POIDS_MAX or q <= 60:
                break
            q -= 5
    return dest.stat().st_size


def labels_trombinoscope(path: str | Path) -> dict[str, dict[str, Any]]:
    """{classe: {"n": effectif annoncé, "labels": [libellé sous chaque photo, ordre de lecture]}}."""
    import pdfplumber

    out: dict[str, dict[str, Any]] = {}
    with pdfplumber.open(str(path)) as pdf:
        for p in pdf.pages:
            words = p.extract_words(use_text_flow=False, keep_blank_chars=True)
            title = " ".join(w["text"] for w in words if w["top"] < 60)
            m = re.search(r"CLASSE\s+(\S+)\s+\((\d+)", title, re.I)
            if not m:
                continue
            cls = m.group(1)
            imgs = sorted(p.images, key=lambda i: (round(i["top"] / 10), i["x0"]))
            labs = []
            for im in imgs:
                cx = (im["x0"] + im["x1"]) / 2
                ws = [w for w in words if im["bottom"] < w["top"] < im["bottom"] + 40 and abs((w["x0"] + w["x1"]) / 2 - cx) < 70]
                ws.sort(key=lambda w: (round(w["top"]), w["x0"]))
                labs.append(" ".join(w["text"] for w in ws).strip())
            out.setdefault(cls, {"n": int(m.group(2)), "labels": []})["labels"].extend(labs)
    return out


def charger_eleves(path: str | Path) -> list[dict[str, str]]:
    """Liste Charlemagne : JSON de `liste_eleves` (clé `eleves`) ou CSV `;` avec id_eleve/nom/prenom/classe."""
    path = str(path)
    if path.lower().endswith(".json"):
        d = json.load(open(path, encoding="utf-8"))
        rows = d.get("eleves", d) if isinstance(d, dict) else d
    else:
        with open(path, encoding="utf-8", newline="") as f:
            rows = list(csv.DictReader(f, delimiter=";"))
    return [{"id": str(r.get("id_eleve") or r.get("IDELEVE") or r.get("id")),
             "nom": r.get("nom") or r.get("NOM") or "", "prenom": r.get("prenom") or r.get("PRENOM") or "",
             "classe": r.get("classe") or r.get("CLASSE") or ""} for r in rows]


def _fichiers_zip(src: Path, cls: str) -> dict[str, Path]:
    d = src / cls
    if not d.is_dir():
        return {}
    return {normaliser(p.stem): p for p in d.iterdir() if p.suffix.lower() in (".jpg", ".jpeg")}


def preparer(vignettes: str | Path, trombi_codes: str | Path, trombi_noms: str | Path, eleves: str | Path,
             classes_map: dict[str, str], sortie: str | Path, seuil: float = 0.80) -> dict[str, Any]:
    sortie = Path(sortie)
    sortie.mkdir(parents=True, exist_ok=True)
    src = Path(vignettes)
    if zipfile.is_zipfile(src):
        dest = sortie / "vignettes_codes"
        with zipfile.ZipFile(src) as z:
            z.extractall(dest)
        src = dest
    liste = charger_eleves(eleves)
    codes = labels_trombinoscope(trombi_codes)
    noms = labels_trombinoscope(trombi_noms)

    d_charl = sortie / "charlemagne_ideleve"
    d_edu = sortie / "edumoov_par_classe"
    d_charl.mkdir(exist_ok=True)
    d_edu.mkdir(exist_ok=True)
    mapping: dict[str, list[dict[str, Any]]] = {}
    index: list[dict[str, Any]] = []
    total = 0
    approx: list[str] = []
    sans_photo: list[str] = []
    non_apparies: list[str] = []
    ignorees: list[str] = []
    silhouettes: list[str] = []
    d_excl = sortie / "exclus_silhouettes"

    for cls, cd in codes.items():
        if cls not in classes_map:
            ignorees.append(f"{cls} ({len(cd['labels'])} photos)")
            continue
        cls_charl = classes_map[cls]
        els = [e for e in liste if e["classe"] == cls_charl]
        nd = noms.get(cls)
        if not nd or len(nd["labels"]) != len(cd["labels"]):
            non_apparies.append(f"{cls} : trombinoscopes incohérents ({len(cd['labels'])} / {len(nd['labels']) if nd else 0} photos) — les regénérer avec les mêmes options")
            continue
        fichiers = _fichiers_zip(src, cls)
        used: set[str] = set()
        rows = []
        for i, (label, lab_photo) in enumerate(zip(cd["labels"], nd["labels"])):
            label = re.sub(r"\s+", " ", label.replace("\t", " ")).strip()  # code d'accès, ou nom associé une fois l'association faite
            nom_photo = re.sub(r"\.jpe?g$", "", lab_photo.replace("\t", " ").strip(), flags=re.I).strip()
            row: dict[str, Any] = {"pos": i + 1, "code": label, "nom_photographe": nom_photo, "id": None, "nom": None, "prenom": None, "score": 1.0}
            exact = [e for e in els if e["id"] not in used and normaliser(e["nom"] + " " + e["prenom"]) == normaliser(nom_photo)]
            e = None
            if len(exact) == 1:
                e = exact[0]
            else:
                free = [x for x in els if x["id"] not in used]
                scored = sorted(((difflib.SequenceMatcher(None, normaliser(nom_photo), normaliser(x["nom"] + " " + x["prenom"])).ratio(), x) for x in free), key=lambda t: -t[0])
                if scored and scored[0][0] >= seuil and (len(scored) == 1 or scored[0][0] - scored[1][0] > 0.1):
                    e = scored[0][1]
                    row["score"] = round(scored[0][0], 2)
                    approx.append(f"{cls_charl} : « {nom_photo} » → {e['nom']} {e['prenom']} (score {row['score']})")
                else:
                    non_apparies.append(f"{cls_charl} : photo {label} « {nom_photo} » — candidats : " + ", ".join(f"{x['nom']} {x['prenom']} ({s:.2f})" for s, x in scored[:3]))
            if e is not None:
                row.update({"id": e["id"], "nom": e["nom"], "prenom": e["prenom"]})
                used.add(e["id"])
                f = fichiers.get(normaliser(label))
                if f is None:
                    non_apparies.append(f"{cls_charl} : aucun fichier du ZIP ne porte le libellé « {label} »")
                elif est_silhouette(f):
                    d_excl.mkdir(exist_ok=True)
                    shutil.copy2(f, d_excl / f"{e['id']}.jpg")
                    silhouettes.append(f"{cls_charl} : {e['nom']} {e['prenom']} (IDELEVE {e['id']}) — silhouette du photographe, pas de photo prise")
                    row["silhouette"] = True
                else:
                    optimiser_jpeg(f, d_charl / f"{e['id']}.jpg")
                    cdir = d_edu / cls_charl.replace("/", "-")
                    cdir.mkdir(exist_ok=True)
                    optimiser_jpeg(f, cdir / f"{e['nom']} {e['prenom']}.jpg")
                    total += 1
            rows.append(row)
            index.append({"classe_maclasse": cls, "classe_charlemagne": cls_charl, "code": label, "ideleve": row["id"] or "",
                          "nom": row["nom"] or "", "prenom": row["prenom"] or "", "nom_photographe": nom_photo, "position": i + 1,
                          "score": row["score"], "statut": "silhouette" if row.get("silhouette") else ("ok" if row["id"] else "non apparié")})
        mapping[cls] = rows
        for e in els:
            if e["id"] not in used:
                sans_photo.append(f"{cls_charl} : {e['nom']} {e['prenom']} (IDELEVE {e['id']})")

    (sortie / "mapping_codes_noms.json").write_text(json.dumps(mapping, ensure_ascii=False, indent=1), encoding="utf-8")
    if index:
        with open(sortie / "index_photos_eleves.csv", "w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(index[0].keys()), delimiter=";")
            w.writeheader()
            w.writerows(index)

    def section(t: str, items: list[str]) -> str:
        return f"\n## {t} ({len(items)})\n\n" + ("\n".join("- " + x for x in items) if items else "- aucun") + "\n"

    rapport = (f"# Photos élèves — rapport du {datetime.date.today():%d/%m/%Y}\n\n"
               f"- Photos appariées et copiées : **{total}** (JPEG sans métadonnées, ≤ 100 Ko)\n"
               f"- Dossiers : `charlemagne_ideleve/` (IDELEVE.jpg) et `edumoov_par_classe/<classe>/NOM Prénom.jpg`\n")
    rapport += section("Silhouettes exclues (élève listé par le photographe mais non photographié) — `exclus_silhouettes/`", silhouettes)
    rapport += section("Rapprochements approximatifs (orthographe photographe ≠ Charlemagne) — à relire", approx)
    rapport += section("Photos non appariées — à arbitrer", non_apparies)
    rapport += section("Élèves sans photo", sans_photo)
    rapport += section("Classes du trombinoscope ignorées (hors correspondance)", ignorees)
    rapport += ("\n## Étapes Charlemagne (manuelles, session RDP)\n\n"
                "1. Copier `charlemagne_ideleve/` dans `~/Downloads/charlemagne_auto/` (seul dossier visible de la session : `\\\\tsclient\\Downloads`)\n"
                "2. Administratif › Outils › Affectation des photos › Élèves – Adultes : RAZ (optionnelle, ne supprime rien), bouton de copie du dossier, puis Affectation automatique (fichiers nommés par identifiant logiciel)\n"
                "3. Vérifier quelques fiches, puis Charlemagne Outils › EcoleDirecte : « À intégrer au prochain envoi » et transfert\n")
    (sortie / "RAPPORT.md").write_text(rapport, encoding="utf-8")
    return {"photos_copiees": total, "approximatifs": approx, "non_apparies": non_apparies, "sans_photo": sans_photo,
            "silhouettes": silhouettes, "classes_ignorees": ignorees, "sortie": str(sortie), "rapport": rapport}


def main() -> None:  # CLI : python -m maclasse_mcp.preparer ...
    import argparse

    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--vignettes", required=True)
    ap.add_argument("--trombi-codes", required=True)
    ap.add_argument("--trombi-noms", required=True)
    ap.add_argument("--eleves", required=True)
    ap.add_argument("--classes", required=True, help="JSON {classe maclasse: classe Charlemagne}")
    ap.add_argument("--sortie", required=True)
    ap.add_argument("--seuil", type=float, default=0.80)
    a = ap.parse_args()
    res = preparer(a.vignettes, a.trombi_codes, a.trombi_noms, a.eleves, json.load(open(a.classes, encoding="utf-8")), a.sortie, a.seuil)
    print(res["rapport"])


if __name__ == "__main__":
    main()
