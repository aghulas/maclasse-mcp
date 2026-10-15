"""Serveur MCP maclasse (espace établissement ecole.maclasse.photo).

Lecture : prises de vues, classes et élèves (codes d'accès, uuid, nom associé, visites, commandes),
page d'association d'une classe. Exports locaux : ZIP des vignettes, trombinoscopes PDF, et
pipeline complet de préparation Charlemagne/Edumoov (preparer.py). Écriture (import de noms,
association nom ↔ photo, retrait) : toujours en deux temps *_prepare_* puis maclasse_write_confirm,
et seulement si MACLASSE_ENABLE_WRITES=1.

Les fichiers téléchargés restent sous MACLASSE_DOWNLOAD_DIR ; aucun binaire n'est renvoyé à l'appelant.
"""
from __future__ import annotations

import csv
import datetime
import io
import json
from pathlib import Path
from typing import Any

from mcp.server.mcpserver import MCPServer

from .client import MaclasseClient, MaclasseError
from .config import SETTINGS
from .parsing import normaliser, to_dict
from .writes import GATE
from . import preparer as prep

mcp = MCPServer(
    name="maclasse",
    title="maclasse.photo (espace école, non officiel)",
    instructions=(
        "Accès à l'espace établissement ecole.maclasse.photo (photos scolaires de l'École Sainte-Marie) "
        "par le compte du secrétariat, via les pages HTML du site (pas d'API officielle). Lecture libre. "
        "Les images du site sont filigranées : seuls les exports (vignettes ZIP, trombinoscopes PDF) sont "
        "exploitables, et ils sont enregistrés localement sans être renvoyés. Toute écriture (import de noms, "
        "association d'un nom à une photo, retrait) passe par un outil *_prepare_* qui renvoie un aperçu et un "
        "jeton : montrer l'aperçu à l'utilisateur et n'appeler maclasse_write_confirm qu'après son accord "
        "explicite. Les codes d'accès des élèves sont destinés aux familles : ne pas les recopier inutilement. "
        "Procédure complète : skill « maclasse-photos-eleves »."
    ),
)

_client: MaclasseClient | None = None


def _c() -> MaclasseClient:
    global _client
    if _client is None:
        _client = MaclasseClient()
    return _client


def _dossier(uuid_projet: str) -> Path:
    d = SETTINGS.download_dir / uuid_projet[:8]
    d.mkdir(parents=True, exist_ok=True)
    return d


def _horodatage() -> str:
    return datetime.datetime.now().strftime("%Y%m%d-%H%M%S")


# ------------------------------------------------------------------ lecture
@mcp.tool()
def maclasse_prises_de_vues() -> list[dict[str, Any]]:
    """Liste les prises de vues de l'école (nom, uuid projet, statut, fin des commandes groupées, nb de commandes, CA)."""
    return to_dict(_c().prises_de_vues())


@mcp.tool()
def maclasse_classes(uuid_projet: str) -> list[dict[str, Any]]:
    """Classes d'une prise de vue : nom, uuid de classe, nombre de photos individuelles, nombre de noms associés, photos de groupe."""
    out = []
    for c in _c().projet(uuid_projet):
        out.append({"nom": c.nom, "uuid": c.uuid, "nb_photos": c.nb_photos, "nb_noms_associes": c.nb_noms_associes,
                    "nb_photos_groupe": len(c.photos_groupe),
                    "visites": sum(e.visites or 0 for e in c.eleves), "commandes": sum(e.commandes or 0 for e in c.eleves)})
    return out


@mcp.tool()
def maclasse_eleves(uuid_projet: str, classe: str | None = None, avec_codes: bool = False) -> list[dict[str, Any]]:
    """Photos individuelles d'une prise de vue (toutes classes ou une classe par nom maclasse, ex. « CE1A ») :
    uuid élève, nom associé, visites, commandes. Les codes d'accès ne sont renvoyés que si avec_codes=True."""
    out = []
    for c in _c().projet(uuid_projet):
        if classe and normaliser(c.nom) != normaliser(classe):
            continue
        for e in c.eleves:
            d = {"classe": c.nom, "uuid_eleve": e.uuid_eleve, "nom_associe": e.nom_associe, "visites": e.visites, "commandes": e.commandes}
            if avec_codes:
                d["code"] = e.code
            out.append(d)
    return out


@mcp.tool()
def maclasse_association_classe(uuid_classe: str) -> dict[str, Any]:
    """Page « Noms des élèves » d'une classe : noms disponibles (index, nom) et, pour chaque photo, uuid élève et nom déjà associé."""
    p = _c().page_association(uuid_classe)
    return {"classe": p.classe, "noms_disponibles": p.noms_disponibles, "photos": p.photos,
            "nb_sans_nom": sum(1 for x in p.photos if not x["nom_associe"])}


@mcp.tool()
def maclasse_commandes(uuid_projet: str, classe: str | None = None, avec_emails: bool = False, enregistrer: bool = True) -> dict[str, Any]:
    """Toutes les commandes d'une prise de vue (récapitulatif CSV de la plateforme) : par commande classe, montant,
    référence, mode de paiement, code élève, élève(s), client, date, type, encaissement, part établissement ; plus des
    totaux par classe et par mode de paiement. Les emails des clients ne sont renvoyés que si avec_emails=True.
    Si enregistrer, le CSV brut est conservé dans MACLASSE_DOWNLOAD_DIR/<projet>/commandes_<horodatage>.csv."""
    from .parsing import parser_commandes_csv

    texte = _c().commandes_csv(uuid_projet)
    fichier = None
    if enregistrer:
        p = _dossier(uuid_projet) / f"commandes_{_horodatage()}.csv"
        p.write_text(texte, encoding="utf-8")
        p.chmod(0o600)
        fichier = str(p)
    rows = parser_commandes_csv(texte)
    if classe:
        rows = [r for r in rows if normaliser(r.get("classe")) == normaliser(classe)]
    par_classe: dict[str, dict[str, Any]] = {}
    par_paiement: dict[str, dict[str, Any]] = {}
    for r in rows:
        for key, agg in ((r.get("classe", ""), par_classe), (r.get("paiement", ""), par_paiement)):
            a = agg.setdefault(key, {"commandes": 0, "montant": 0.0, "part_etablissement": 0.0})
            a["commandes"] += 1
            a["montant"] += r["montant"] if isinstance(r.get("montant"), float) else 0.0
            a["part_etablissement"] += r["part_etablissement"] if isinstance(r.get("part_etablissement"), float) else 0.0
    for agg in (par_classe, par_paiement):
        for a in agg.values():
            a["montant"] = round(a["montant"], 2)
            a["part_etablissement"] = round(a["part_etablissement"], 2)
    if not avec_emails:
        rows = [{k: v for k, v in r.items() if k != "email_client"} for r in rows]
    return {"nb_commandes": len(rows), "total": round(sum(r["montant"] for r in rows if isinstance(r.get("montant"), float)), 2),
            "part_etablissement": round(sum(r["part_etablissement"] for r in rows if isinstance(r.get("part_etablissement"), float)), 2),
            "par_classe": par_classe, "par_paiement": par_paiement, "commandes": rows, "fichier": fichier}


@mcp.tool()
def maclasse_commandes_html(uuid_projet: str, max_chars: int = 20000) -> str:
    """Texte brut de la page « Détail des commandes » (structure non encore cartographiée) — pour lecture ponctuelle."""
    from bs4 import BeautifulSoup

    txt = BeautifulSoup(_c().commandes_html(uuid_projet), "html.parser").get_text("\n", strip=True)
    return txt[:max_chars]


# ------------------------------------------------------------------ exports locaux
@mcp.tool()
def maclasse_telecharger_vignettes(uuid_projet: str, format_nom: str = "Nom Prenom") -> dict[str, Any]:
    """Télécharge le ZIP « Vignettes élèves » (un dossier par classe, JPG 400×533 sans filigrane ; nom = nom associé
    ou code d'accès) dans MACLASSE_DOWNLOAD_DIR/<projet>/. format_nom : NomPrenom | Nom Prenom | Nom.Prenom | Nom-Prenom."""
    dest = _dossier(uuid_projet) / f"vignettes_{_horodatage()}.zip"
    p = _c().telecharger_vignettes(uuid_projet, dest, format_nom)
    return {"fichier": str(p), "octets": p.stat().st_size}


@mcp.tool()
def maclasse_telecharger_trombinoscope(uuid_projet: str, libelle: str = "codes", par_page: int = 6) -> dict[str, Any]:
    """Télécharge le trombinoscope PDF (une classe par page, `par_page` photos par page, 0 = toutes sur une page).
    libelle : codes|nom_eleve (nom associé, sinon code d'accès) · nom_photo (nom de fichier du photographe) · aucun."""
    dest = _dossier(uuid_projet) / f"trombinoscope_{libelle}_{_horodatage()}.pdf"
    p = _c().telecharger_trombinoscope(uuid_projet, dest, libelle, par_page or None)
    return {"fichier": str(p), "octets": p.stat().st_size}


@mcp.tool()
def maclasse_preparer_photos(uuid_projet: str, liste_eleves: str, classes_map: dict[str, str] | None = None,
                             sortie: str | None = None, par_page: int = 6) -> dict[str, Any]:
    """Pipeline complet : télécharge vignettes + trombinoscopes (codes, nom_photo), rapproche chaque photo de la liste
    Charlemagne et produit charlemagne_ideleve/ (IDELEVE.jpg), edumoov_par_classe/, index CSV et RAPPORT.md.
    Dure 2 à 4 minutes (génération côté plateforme) : si le client expire, ne pas relancer — lire le résultat avec
    maclasse_rapport(sortie). Le dossier de sortie doit être nouveau (aucun fichier n'est écrasé).
    liste_eleves : chemin du JSON de l'outil Charlemagne liste_eleves (ou CSV). classes_map : {classe maclasse: classe
    Charlemagne} ; si absent, correspondance automatique sur le nom normalisé (ex. CE1A ↔ CE1 A) avec les écarts signalés."""
    c = _c()
    classes = c.projet(uuid_projet)
    eleves = prep.charger_eleves(liste_eleves)
    classes_charl = sorted({e["classe"] for e in eleves})
    if classes_map is None:
        classes_map = {}
        for cl in classes:
            cands = [x for x in classes_charl if normaliser(x).replace(" ", "").replace("/", "-") == normaliser(cl.nom).replace(" ", "")]
            if len(cands) == 1:
                classes_map[cl.nom] = cands[0]
    manquantes = [cl.nom for cl in classes if cl.nom not in classes_map]
    out_dir = Path(sortie) if sortie else _dossier(uuid_projet) / f"preparation_{_horodatage()}"
    out_dir.mkdir(parents=True, exist_ok=True)
    zip_path = c.telecharger_vignettes(uuid_projet, out_dir / "vignettes.zip")
    t_codes = c.telecharger_trombinoscope(uuid_projet, out_dir / "trombinoscope_codes.pdf", "codes", par_page or None)
    t_noms = c.telecharger_trombinoscope(uuid_projet, out_dir / "trombinoscope_noms_photo.pdf", "nom_photo", par_page or None)
    (out_dir / "classes_map.json").write_text(json.dumps(classes_map, ensure_ascii=False, indent=1), encoding="utf-8")
    res = prep.preparer(zip_path, t_codes, t_noms, liste_eleves, classes_map, out_dir)
    res["classes_map"] = classes_map
    res["classes_sans_correspondance"] = manquantes
    return res


@mcp.tool()
def maclasse_rapport(sortie: str) -> dict[str, Any]:
    """Relit le RAPPORT.md et les compteurs d'une préparation déjà faite (utile si l'appel à maclasse_preparer_photos
    a dépassé le délai du client : le traitement continue sur le Mac et se termine en 2 à 4 minutes)."""
    d = Path(sortie)
    rap = d / "RAPPORT.md"
    if not rap.exists():
        attendus = ["vignettes.zip", "trombinoscope_codes.pdf", "trombinoscope_noms_photo.pdf"]
        return {"termine": False, "fichiers_presents": [f for f in attendus if (d / f).exists()],
                "conseil": "Traitement en cours ou échoué : réessayer dans une minute, puis vérifier les journaux du serveur."}
    n_charl = len(list((d / "charlemagne_ideleve").glob("*.jpg"))) if (d / "charlemagne_ideleve").exists() else 0
    classes = sorted(p.name for p in (d / "edumoov_par_classe").iterdir()) if (d / "edumoov_par_classe").exists() else []
    return {"termine": True, "photos_charlemagne": n_charl, "classes_edumoov": classes, "rapport": rap.read_text(encoding="utf-8")}


# ------------------------------------------------------------------ écriture (deux temps)
@mcp.tool()
def maclasse_importer_noms_prepare(uuid_classe: str, eleves: list[dict[str, str]]) -> dict[str, Any]:
    """Prépare l'import de la liste de noms d'une classe (remplace la liste existante sur la plateforme).
    eleves : [{"nom": ..., "prenom": ...}, ...]. Renvoie un aperçu et un jeton pour maclasse_write_confirm."""
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";")
    w.writerow(["Nom", "Prénom"])
    for e in sorted(eleves, key=lambda x: (x.get("nom", ""), x.get("prenom", ""))):
        w.writerow([e.get("nom", "").strip(), e.get("prenom", "").strip()])
    data = buf.getvalue().encode("utf-8")
    page = _c().page_association(uuid_classe)
    apercu = {"classe": page.classe, "nb_noms": len(eleves), "nb_photos": len(page.photos),
              "liste_actuelle_remplacee": len(page.noms_disponibles) + sum(1 for p in page.photos if p["nom_associe"]),
              "premiers": [f"{e.get('nom','')} {e.get('prenom','')}" for e in eleves[:3]]}

    def run() -> dict[str, Any]:
        p = _c().importer_noms(uuid_classe, data)
        return {"classe": p.classe, "noms_disponibles": len(p.noms_disponibles), "photos": len(p.photos)}

    return GATE.prepare("importer_noms", apercu, run)


@mcp.tool()
def maclasse_associer_noms_prepare(uuid_classe: str, associations: list[dict[str, str]]) -> dict[str, Any]:
    """Prépare l'association nom ↔ photo pour une classe dont la liste de noms est déjà importée.
    associations : [{"uuid_eleve": ..., "nom": "NOM Prénom"}] (uuid élève via maclasse_eleves ou maclasse_association_classe).
    Chaque nom doit exister dans les noms disponibles de la page ; les photos déjà nommées sont ignorées."""
    page = _c().page_association(uuid_classe)
    dispo = {normaliser(n["nom"]): n for n in page.noms_disponibles}
    photos = {p["uuid_eleve"]: p for p in page.photos}
    plan, erreurs = [], []
    for a in associations:
        u, nom = a.get("uuid_eleve", ""), a.get("nom", "")
        if u not in photos:
            erreurs.append(f"photo inconnue : {u}")
            continue
        if photos[u]["nom_associe"]:
            erreurs.append(f"photo déjà nommée ({photos[u]['nom_associe']}) : {u}")
            continue
        n = dispo.get(normaliser(nom))
        if n is None:
            erreurs.append(f"nom absent de la liste disponible : {nom}")
            continue
        plan.append({"uuid_eleve": u, "index": n["index"], "nom": n["nom"]})
    apercu = {"classe": page.classe, "nb_associations": len(plan), "erreurs": erreurs, "exemples": [p["nom"] for p in plan[:5]]}

    def run() -> dict[str, Any]:
        ok, ko = 0, []
        for p in plan:
            if _c().associer_nom(p["index"], p["uuid_eleve"]):
                ok += 1
            else:
                ko.append(p["nom"])
        return {"classe": page.classe, "associees": ok, "echecs": ko}

    return GATE.prepare("associer_noms", apercu, run)


@mcp.tool()
def maclasse_retirer_noms_prepare(uuid_classe: str, uuids_eleves: list[str]) -> dict[str, Any]:
    """Prépare le retrait du nom associé à des photos (le nom redevient disponible dans la liste)."""
    page = _c().page_association(uuid_classe)
    photos = {p["uuid_eleve"]: p for p in page.photos}
    plan = [u for u in uuids_eleves if u in photos and photos[u]["nom_associe"]]
    apercu = {"classe": page.classe, "nb_retraits": len(plan), "noms": [photos[u]["nom_associe"] for u in plan[:5]]}

    def run() -> dict[str, Any]:
        return {"classe": page.classe, "retires": sum(1 for u in plan if _c().retirer_nom(u))}

    return GATE.prepare("retirer_noms", apercu, run)


@mcp.tool()
def maclasse_write_confirm(jeton: str) -> dict[str, Any]:
    """Exécute une écriture préparée (après accord explicite de l'utilisateur)."""
    return GATE.confirm(jeton)


@mcp.tool()
def maclasse_write_cancel(jeton: str) -> dict[str, Any]:
    """Abandonne une écriture préparée."""
    return {"annule": GATE.cancel(jeton)}


@mcp.tool()
def maclasse_statut() -> dict[str, Any]:
    """État du connecteur : connexion à la plateforme, dossier de téléchargement, écritures activées, jetons en attente."""
    try:
        n = len(_c().prises_de_vues())
        conn = f"ok ({n} prise(s) de vues)"
    except MaclasseError as e:
        conn = f"échec : {e}"
    except Exception as e:  # réseau, etc.
        conn = f"erreur : {type(e).__name__}"
    return {"connexion": conn, "download_dir": str(SETTINGS.download_dir), "ecritures": SETTINGS.enable_writes, "en_attente": GATE.pending()}
