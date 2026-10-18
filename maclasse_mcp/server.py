"""Serveur MCP maclasse (espace établissement ecole.maclasse.photo).

Lecture : prises de vues, classes et élèves (codes d'accès, uuid, nom associé, visites, commandes),
page d'association d'une classe. Exports locaux : ZIP des vignettes, trombinoscopes PDF, fiches d'accès
(coupons), aperçus filigranés pour les relances, et pipeline complet de préparation des photos pour
Charlemagne (preparer.py) ; identification des photos de fratries hors MCP (fratries.py). Écriture (import de noms,
association nom ↔ photo, retrait) : toujours en deux temps *_prepare_* puis maclasse_write_confirm,
et seulement si MACLASSE_ENABLE_WRITES=1.

Les fichiers téléchargés restent sous MACLASSE_DOWNLOAD_DIR ; aucun binaire n'est renvoyé à l'appelant.
"""
from __future__ import annotations

import csv
import datetime
import io
import json
import threading
import traceback
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
_JOBS: dict[str, dict[str, Any]] = {}  # préparations lancées en arrière-plan : id → état


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
def maclasse_prises_de_vues(archives: bool = False) -> list[dict[str, Any]]:
    """Liste les prises de vues de l'école (nom, uuid projet, statut, fin des commandes groupées, nb de commandes, CA).
    archives=True ajoute les prises de vues des années précédentes (page « archives » de l'établissement)."""
    c = _c()
    out = to_dict(c.prises_de_vues())
    if archives:
        us = c.uuid_structure()
        if us:
            vus = {p["uuid"] for p in out}
            out += [dict(p, archive=True) for p in to_dict(c.archives(us)) if p["uuid"] not in vus]
    return out


@mcp.tool()
def maclasse_versements(telecharger_recaps: bool = False) -> dict[str, Any]:
    """Versements de la plateforme à l'établissement (calculés les 10 et 25 du mois) : référence, prise de vues, date,
    CA total, CA réel, part établissement, chèques/espèces encaissés à l'école, montant versé, état. telecharger_recaps
    enregistre les récapitulatifs PDF (pièces pour la comptabilité) dans MACLASSE_DOWNLOAD_DIR/versements/."""
    c = _c()
    rows = c.versements()
    fichiers = []
    if telecharger_recaps:
        d = SETTINGS.download_dir / "versements"
        for r in rows:
            if r.get("recap_pdf"):
                dest = d / f"recapitulatif-versement-{r['reference']}.pdf"
                if not dest.exists():
                    c._telecharger(r["recap_pdf"], dest)
                fichiers.append(str(dest))
    total = round(sum(r["versement"] or 0 for r in rows), 2)
    return {"nb_versements": len(rows), "total_verse": total, "versements": rows, "fichiers": fichiers}


@mcp.tool()
def maclasse_statistiques(uuid_projet: str, telecharger_pdf: bool = False) -> dict[str, Any]:
    """Statistiques d'une prise de vue : codes créés, connectés, visites, élèves ayant commandé, panier moyen, et rapport
    détaillé des ventes par produit. telecharger_pdf enregistre rapport-ventes.pdf et recap-stats.pdf localement."""
    c = _c()
    res = c.statistiques(uuid_projet)
    if telecharger_pdf:
        d = _dossier(uuid_projet)
        res["fichiers"] = []
        for name in ("rapport-ventes.pdf", "recap-stats.pdf"):
            dest = d / f"{name[:-4]}_{_horodatage()}.pdf"
            c._telecharger(f"/stats/{uuid_projet}/{name}", dest)
            res["fichiers"].append(str(dest))
    return res


@mcp.tool()
def maclasse_paiements_a_valider(mode: str = "cheques") -> dict[str, Any]:
    """Commandes payées par chèque ou en espèces à l'école, en attente de validation sur la plateforme (mode : cheques |
    especes). Lecture seule : la validation est irréversible et se fait à la main sur le site après réception du paiement."""
    rows = _c().paiements_a_valider(mode)
    return {"mode": mode, "nb": len(rows), "commandes": rows,
            "note": "Validation à faire sur ecole.maclasse.photo › Chèques/Espèces, paiement en main (irréversible)."}





@mcp.tool()
def maclasse_classes(uuid_projet: str) -> list[dict[str, Any]]:
    """Classes d'une prise de vue : nom, uuid de classe, nombre de photos individuelles, nombre de noms associés, photos de groupe."""
    out = []
    for c in _c().projet(uuid_projet):
        out.append({"nom": c.nom, "uuid": c.uuid, "type_classe": c.type_classe, "nb_photos": c.nb_photos, "nb_noms_associes": c.nb_noms_associes,
                    "nb_photos_groupe": len(c.photos_groupe),
                    "visites": sum(e.visites or 0 for e in c.eleves), "commandes": sum(e.commandes or 0 for e in c.eleves)})
    return out


@mcp.tool()
def maclasse_eleves(uuid_projet: str, classe: str | None = None, avec_codes: bool = False, sans_visite: bool = False) -> list[dict[str, Any]]:
    """Photos individuelles d'une prise de vue (toutes classes ou une classe par nom maclasse, ex. « CE1A » ou « Fratries ») :
    uuid élève, nom associé, visites, commandes. sans_visite=True ne garde que les photos jamais consultées par la famille
    (cible d'une relance). Les codes d'accès ne sont renvoyés que si avec_codes=True."""
    out = []
    for c in _c().projet(uuid_projet):
        if classe and normaliser(c.nom) != normaliser(classe):
            continue
        for e in c.eleves:
            if sans_visite and (e.visites or 0) > 0:
                continue
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
        classes_cmd = [x.strip() for x in (r.get("classe") or "").split(",") if x.strip()] or [""]
        cle_classe = classes_cmd[0] if len(classes_cmd) == 1 else "plusieurs classes"
        for key, agg in ((cle_classe, par_classe), (r.get("paiement", ""), par_paiement)):
            a = agg.setdefault(key, {"commandes": 0, "montant": 0.0, "part_etablissement": 0.0})
            a["commandes"] += 1
            a["montant"] += r["montant"] if isinstance(r.get("montant"), float) else 0.0
            a["part_etablissement"] += r["part_etablissement"] if isinstance(r.get("part_etablissement"), float) else 0.0
        if len(classes_cmd) > 1:  # une commande multi-enfants compte aussi, en nombre seulement, pour chaque classe concernée
            for cl in classes_cmd:
                par_classe.setdefault(cl, {"commandes": 0, "montant": 0.0, "part_etablissement": 0.0})
                par_classe[cl].setdefault("dont_multi_classes", 0)
                par_classe[cl]["dont_multi_classes"] += 1
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
def maclasse_fiches_acces(uuid_projet: str) -> dict[str, Any]:
    """Télécharge le PDF des fiches d'accès (coupons remis aux familles : URL https://apdl.maclasse.photo/, QR code, code
    d'accès ; un coupon par élève ou fratrie + un coupon « photos de groupe » par classe) dans MACLASSE_DOWNLOAD_DIR/<projet>/.
    Sert à réimprimer le coupon d'une famille qui a perdu son code. Le PDF contient tous les codes : ne pas le diffuser."""
    dest = _dossier(uuid_projet) / f"fiches_acces_{_horodatage()}.pdf"
    p = _c().telecharger_fiches_acces(uuid_projet, dest)
    return {"fichier": str(p), "octets": p.stat().st_size}


@mcp.tool()
def maclasse_telecharger_apercus(uuid_projet: str, classe: str, codes: list[str] | None = None, sans_visite: bool = False,
                                 dossier: str | None = None) -> dict[str, Any]:
    """Télécharge les aperçus FILIGRANÉS (« COPIE INTERDITE », 1000×750, ~190 Ko) des photos d'une classe (ou de la
    pseudo-classe « Fratries »), à joindre à un message de relance aux familles. Filtres : codes (liste de codes d'accès)
    et/ou sans_visite (photos jamais consultées). Fichiers `apercu_<classe>_<nom associé ou code>.jpg` dans `dossier`
    (défaut MACLASSE_DOWNLOAD_DIR/<projet>/apercus_<classe>/), jamais écrasés. Ce ne sont pas les photos livrables
    (export « Vignettes élèves » pour cela)."""
    import re as _re
    cible = Path(dossier) if dossier else _dossier(uuid_projet) / f"apercus_{normaliser(classe).replace(' ', '_')}"
    voulus = {c.upper() for c in (codes or [])}
    faits, ignores = [], []
    for c in _c().projet(uuid_projet):
        if normaliser(c.nom) != normaliser(classe):
            continue
        for e in c.eleves:
            if voulus and e.code.upper() not in voulus:
                continue
            if sans_visite and (e.visites or 0) > 0:
                continue
            if not e.photo_url:
                ignores.append(e.code)
                continue
            base = _re.sub(r"[^A-Za-z0-9]+", "_", e.nom_associe or e.code).strip("_")
            dest = cible / f"apercu_{normaliser(c.nom).replace(' ', '_')}_{base}.jpg"
            if dest.exists():
                ignores.append(f"{e.code} (déjà présent)")
                continue
            _c().telecharger_apercu(e.photo_url, dest)
            faits.append({"code": e.code, "nom_associe": e.nom_associe, "uuid_eleve": e.uuid_eleve, "fichier": str(dest)})
    return {"dossier": str(cible), "nb": len(faits), "apercus": faits, "ignores": ignores}


def _preparer(uuid_projet: str, liste_eleves: str, classes_map: dict[str, str] | None, out_dir: Path, par_page: int) -> dict[str, Any]:
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
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "classes_map.json").write_text(json.dumps(classes_map, ensure_ascii=False, indent=1), encoding="utf-8")
    zip_path = c.telecharger_vignettes(uuid_projet, out_dir / "vignettes.zip")
    t_codes = c.telecharger_trombinoscope(uuid_projet, out_dir / "trombinoscope_codes.pdf", "codes", par_page or None)
    t_noms = c.telecharger_trombinoscope(uuid_projet, out_dir / "trombinoscope_noms_photo.pdf", "nom_photo", par_page or None)
    res = prep.preparer(zip_path, t_codes, t_noms, liste_eleves, classes_map, out_dir)
    res["classes_map"] = classes_map
    res["classes_sans_correspondance"] = manquantes
    return res


def _job_run(job_id: str, **kw: Any) -> None:
    j = _JOBS[job_id]
    try:
        j["resultat"] = _preparer(**kw)
        j["etat"] = "termine"
    except Exception as e:  # noqa: BLE001 — l'erreur est rendue par maclasse_rapport
        j["etat"] = "erreur"
        j["erreur"] = f"{type(e).__name__}: {e}"
        j["trace"] = traceback.format_exc()[-2000:]
    finally:
        j["fin"] = datetime.datetime.now().isoformat(timespec="seconds")


@mcp.tool()
def maclasse_preparer_photos(uuid_projet: str, liste_eleves: str, classes_map: dict[str, str] | None = None,
                             sortie: str | None = None, par_page: int = 6, en_arriere_plan: bool = True) -> dict[str, Any]:
    """Pipeline complet : télécharge vignettes + trombinoscopes (codes, nom_photo), rapproche chaque photo de la liste
    Charlemagne et produit charlemagne_ideleve/ (IDELEVE.jpg), index CSV et RAPPORT.md (pas de dossier Edumoov :
    Edumoov n'a pas de photo élève). Le dossier de sortie doit être nouveau (aucun fichier n'est écrasé).
    Dure 2 à 4 minutes (génération côté plateforme) : par défaut le traitement part en arrière-plan et l'outil renvoie
    tout de suite {job, sortie} ; suivre avec maclasse_rapport(job=…) ou maclasse_rapport(sortie=…). en_arriere_plan=False
    attend la fin (scripts). liste_eleves : chemin du JSON de l'outil Charlemagne liste_eleves (ou CSV). classes_map :
    {classe maclasse: classe Charlemagne} ; si absent, correspondance automatique sur le nom normalisé (ex. CE1A ↔ CE1 A)
    avec les écarts signalés."""
    out_dir = Path(sortie) if sortie else _dossier(uuid_projet) / f"preparation_{_horodatage()}"
    if out_dir.exists() and any(out_dir.iterdir()):
        raise MaclasseError(f"Dossier de sortie non vide, choisir un dossier nouveau : {out_dir}")
    kw = dict(uuid_projet=uuid_projet, liste_eleves=liste_eleves, classes_map=classes_map, out_dir=out_dir, par_page=par_page)
    if not en_arriere_plan:
        return _preparer(**kw)
    job_id = _horodatage()
    _JOBS[job_id] = {"etat": "en_cours", "sortie": str(out_dir), "debut": datetime.datetime.now().isoformat(timespec="seconds")}
    threading.Thread(target=_job_run, args=(job_id,), kwargs=kw, daemon=True, name=f"maclasse-prep-{job_id}").start()
    return {"job": job_id, "etat": "en_cours", "sortie": str(out_dir),
            "consigne": "Relire dans 2 à 4 minutes avec maclasse_rapport(job=…) ; ne pas relancer la préparation."}


@mcp.tool()
def maclasse_rapport(sortie: str | None = None, job: str | None = None) -> dict[str, Any]:
    """État d'une préparation : par identifiant de job (lancée en arrière-plan dans cette session du serveur) ou par
    dossier de sortie (relecture de RAPPORT.md, y compris après redémarrage). Sans argument : liste des jobs connus."""
    if job is not None:
        j = _JOBS.get(job)
        if j is None:
            return {"job": job, "etat": "inconnu", "jobs_connus": sorted(_JOBS)}
        out = {k: v for k, v in j.items() if k != "resultat"}
        out["job"] = job
        if j["etat"] == "termine":
            out["resultat"] = j["resultat"]
        return out
    if sortie is None:
        return {"jobs": [{"job": k, "etat": v["etat"], "sortie": v["sortie"]} for k, v in sorted(_JOBS.items())]}
    d = Path(sortie)
    rap = d / "RAPPORT.md"
    if not rap.exists():
        attendus = ["vignettes.zip", "trombinoscope_codes.pdf", "trombinoscope_noms_photo.pdf"]
        return {"termine": False, "fichiers_presents": [f for f in attendus if (d / f).exists()],
                "conseil": "Traitement en cours ou échoué : réessayer dans une minute, ou maclasse_rapport(job=…) pour l'erreur."}
    n_charl = len(list((d / "charlemagne_ideleve").glob("*.jpg"))) if (d / "charlemagne_ideleve").exists() else 0
    return {"termine": True, "photos_charlemagne": n_charl, "rapport": rap.read_text(encoding="utf-8")}


# ------------------------------------------------------------------ écriture (deux temps)
@mcp.tool()
def maclasse_importer_noms_prepare(uuid_classe: str, eleves: list[dict[str, str]]) -> dict[str, Any]:
    """Prépare l'import de la liste de noms d'une classe. Vérifié le 15/10/2026 : l'import remplace la liste des noms
    DISPONIBLES (non encore attribués) et conserve les associations déjà faites ; les noms déjà associés ne doivent donc
    pas être réimportés (sinon ils apparaissent en double). Pour une classe entièrement associée, n'importer que les
    noms manquants (absents, nouveaux élèves).
    eleves : [{"nom": ..., "prenom": ...}, ...]. Renvoie un aperçu et un jeton pour maclasse_write_confirm."""
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";")
    w.writerow(["Nom", "Prénom"])
    for e in sorted(eleves, key=lambda x: (x.get("nom", ""), x.get("prenom", ""))):
        w.writerow([e.get("nom", "").strip(), e.get("prenom", "").strip()])
    data = buf.getvalue().encode("utf-8")
    page = _c().page_association(uuid_classe)
    apercu = {"classe": page.classe, "nb_noms": len(eleves), "nb_photos": len(page.photos),
              "noms_disponibles_remplaces": len(page.noms_disponibles), "photos_deja_nommees": sum(1 for p in page.photos if p["nom_associe"]),
              "deja_associes_dans_la_liste": [f"{e.get('nom','')} {e.get('prenom','')}" for e in eleves
                                             if normaliser(f"{e.get('nom','')} {e.get('prenom','')}") in {normaliser(p["nom_associe"]) for p in page.photos if p["nom_associe"]}][:10],
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
