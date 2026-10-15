"""Client HTTP de l'espace établissement ecole.maclasse.photo.

Routes observées (15/10/2026, bundle FOS JS Routing de l'application) :
  POST /login                                   _username, _password (formulaire Symfony, pas de jeton CSRF)
  GET  /                                        prises de vues
  GET  /project/{uuidProjet}/infos              classes, élèves (codes, uuid), photos de groupe
  GET  /project/{uuidProjet}/orders             détail des commandes (20 par page, formulaire de recherche POST)
  POST /project/{uuidProjet}/orders?nbResultByPage=20&recapitulatif=1   → CSV (virgule, UTF-8) de toutes les commandes
  GET  /structure/{uuidStructure}/archives      prises de vues des années précédentes (uuidStructure : lien « archives » de l'accueil)
  GET  /structure/versement                     versements (10 et 25 du mois) ; /versements/projet/createRecap/recapitulatif-versement-{ref}.pdf
  GET  /project/{uuidProjet}/stats/             statistiques ; ?recapitulatifCSV=1 ; /stats/{uuidProjet}/rapport-ventes.pdf, recap-stats.pdf
  GET  /validation/cheques | /validation/especes  commandes payées à l'école en attente de validation (POST validation[] : IRRÉVERSIBLE, non exposé)
  /api/couponAcces (fiches d'accès PDF/JPG/Excel) : appel JSON puis POST vers UrlApiGeneration — non cartographié
  GET  /vignettesParticipants/{uuidProjet}.zip?affName=nameCamel|nameEspace|namePoint|nameTiret
  GET  /trombinoscope/projet/{uuidProjet}/{affName}/{presentation}[/{nbPhoto}]
         affName = nameChild (nom associé, sinon code d'accès) | namePhoto (nom du fichier du photographe) | withoutName
         presentation = byPage (+ nbPhoto) | allOnPage
  GET  /triNomParticipants/niveau/{uuidClasse}/tri         page d'association (noms disponibles, photos)
  POST /triNomParticipants/niveau/{uuidClasse}/tri         multipart : options=nomPrenom|prenomNom, order=alphabetique|file,
                                                           entete=entete, csv=<fichier UTF-8 « Nom;Prénom »>
  POST /api/nomToEleve   nomToMove=<index>, uuidEleveToAttribute=<uuidEleve>   → {"actionIsOK": true}
  PUT  /api/nomToEleve   uuidEleveToEmpty, uuidEleveToAttribute (déplacer un nom)
  DELETE /api/nomToEleve uuidEleveToEmpty (retirer le nom d'une photo)

Les images affichées (lbcache.maclasse.photo) sont filigranées : seul l'export ZIP est exploitable.
Journalisation sur stderr uniquement, jamais d'identifiant ni de contenu nominatif.
"""
from __future__ import annotations

import logging
import re
import sys
from pathlib import Path

import httpx

from .config import SETTINGS
from . import parsing

log = logging.getLogger("maclasse_mcp")
if not log.handlers:
    h = logging.StreamHandler(sys.stderr)
    h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s maclasse: %(message)s"))
    log.addHandler(h)
log.setLevel(logging.INFO)

AFF_NAME_VIGNETTES = {"NomPrenom": "nameCamel", "Nom Prenom": "nameEspace", "Nom.Prenom": "namePoint", "Nom-Prenom": "nameTiret"}
LIBELLE_TROMBI = {"nom_eleve": "nameChild", "codes": "nameChild", "nom_photo": "namePhoto", "aucun": "withoutName"}


class MaclasseError(RuntimeError):
    pass


class MaclasseClient:
    def __init__(self, base_url: str | None = None, transport: httpx.BaseTransport | None = None):
        self.base_url = (base_url or SETTINGS.base_url).rstrip("/")
        self._http = httpx.Client(
            base_url=self.base_url,
            timeout=SETTINGS.timeout,
            follow_redirects=False,
            headers={"User-Agent": "maclasse-mcp/0.1 (+ecole Sainte-Marie Fontainebleau)"},
            transport=transport,
        )
        self._logged = False

    # ---------------------------------------------------------------- session
    def login(self) -> None:
        email, password = SETTINGS.credentials()
        r = self._http.post("/login", data={"_username": email, "_password": password})
        # Succès = redirection vers l'accueil ; échec = page de login (200) avec message.
        if r.status_code in (301, 302, 303) and not r.headers.get("location", "").endswith("/login"):
            self._logged = True
            log.info("connexion réussie")
            return
        raise MaclasseError("Connexion refusée par maclasse.photo (identifiants ?)")

    def _get(self, url: str, **kw) -> httpx.Response:
        if not self._logged:
            self.login()
        r = self._http.get(url, **kw)
        if r.status_code in (301, 302, 303) and "/login" in r.headers.get("location", ""):
            log.info("session expirée, reconnexion")
            self._logged = False
            self.login()
            r = self._http.get(url, **kw)
        r.raise_for_status()
        return r

    def _request(self, method: str, url: str, **kw) -> httpx.Response:
        if not self._logged:
            self.login()
        r = self._http.request(method, url, **kw)
        if r.status_code in (301, 302, 303) and "/login" in r.headers.get("location", ""):
            self._logged = False
            self.login()
            r = self._http.request(method, url, **kw)
        return r

    # ---------------------------------------------------------------- lecture
    def prises_de_vues(self) -> list[parsing.PriseDeVues]:
        return parsing.parser_accueil(self._get("/").text)

    def projet(self, uuid_projet: str) -> list[parsing.Classe]:
        return parsing.parser_projet(self._get(f"/project/{uuid_projet}/infos").text)

    def commandes_html(self, uuid_projet: str) -> str:
        return self._get(f"/project/{uuid_projet}/orders").text

    def commandes_csv(self, uuid_projet: str) -> str:
        """Récapitulatif CSV de toutes les commandes (bouton « Télécharger le récapitulatif »)."""
        r = self._request("POST", f"/project/{uuid_projet}/orders", params={"nbResultByPage": 20, "recapitulatif": 1})
        r.raise_for_status()
        if "text/csv" not in r.headers.get("content-type", ""):
            raise MaclasseError("La plateforme n'a pas renvoyé le CSV des commandes")
        return r.content.decode("utf-8-sig", "replace")

    def archives(self, uuid_structure: str) -> list[parsing.PriseDeVues]:
        return parsing.parser_accueil(self._get(f"/structure/{uuid_structure}/archives").text)

    def uuid_structure(self) -> str | None:
        m = re.search(r"/structure/([0-9a-f-]{36})/archives", self._get("/").text)
        return m.group(1) if m else None

    def versements(self) -> list[dict]:
        return parsing.parser_versements(self._get("/structure/versement").text)

    def statistiques(self, uuid_projet: str) -> dict:
        return parsing.parser_statistiques(self._get(f"/project/{uuid_projet}/stats/").text)

    def paiements_a_valider(self, mode: str) -> list[dict]:
        if mode not in ("cheques", "especes"):
            raise MaclasseError("mode = cheques | especes")
        return parsing.parser_paiements_a_valider(self._get(f"/validation/{mode}").text)

    def page_association(self, uuid_classe: str) -> parsing.PageAssociation:
        return parsing.parser_association(self._get(f"/triNomParticipants/niveau/{uuid_classe}/tri").text)

    # ---------------------------------------------------------------- exports
    def _telecharger(self, url: str, dest: Path, params: dict | None = None) -> Path:
        dest.parent.mkdir(parents=True, exist_ok=True)
        if dest.exists():
            raise MaclasseError(f"Fichier déjà présent, non écrasé : {dest}")
        if not self._logged:
            self.login()
        with self._http.stream("GET", url, params=params) as r:
            if r.status_code in (301, 302, 303):
                raise MaclasseError("Redirection inattendue pendant le téléchargement (session ?)")
            r.raise_for_status()
            ctype = r.headers.get("content-type", "")
            if "text/html" in ctype:
                raise MaclasseError("La plateforme a renvoyé une page HTML au lieu du fichier attendu")
            with open(dest, "wb") as f:
                for chunk in r.iter_bytes():
                    f.write(chunk)
        dest.chmod(0o600)
        log.info("téléchargé %s (%d octets)", dest.name, dest.stat().st_size)
        return dest

    def telecharger_vignettes(self, uuid_projet: str, dest: Path, format_nom: str = "Nom Prenom") -> Path:
        aff = AFF_NAME_VIGNETTES.get(format_nom, format_nom)
        return self._telecharger(f"/vignettesParticipants/{uuid_projet}.zip", dest, params={"affName": aff})

    def telecharger_trombinoscope(self, uuid_projet: str, dest: Path, libelle: str = "codes", par_page: int | None = 6) -> Path:
        aff = LIBELLE_TROMBI.get(libelle, libelle)
        if par_page:
            url = f"/trombinoscope/projet/{uuid_projet}/{aff}/byPage/{int(par_page)}"
        else:
            url = f"/trombinoscope/projet/{uuid_projet}/{aff}/allOnPage"
        return self._telecharger(url, dest)

    # ---------------------------------------------------------------- écriture (appelée uniquement via writes.py)
    def importer_noms(self, uuid_classe: str, csv_bytes: bytes, ordre: str = "nomPrenom", entete: bool = True) -> parsing.PageAssociation:
        data = {"options": ordre, "order": "alphabetique"}
        if entete:
            data["entete"] = "entete"
        r = self._request("POST", f"/triNomParticipants/niveau/{uuid_classe}/tri", data=data,
                          files={"csv": ("noms.csv", csv_bytes, "text/csv")})
        if r.status_code in (301, 302, 303):
            r = self._get(r.headers["location"])
        r.raise_for_status()
        return parsing.parser_association(r.text)

    def associer_nom(self, index_nom: int, uuid_eleve: str) -> bool:
        r = self._request("POST", "/api/nomToEleve", data={"nomToMove": str(index_nom), "uuidEleveToAttribute": uuid_eleve},
                          headers={"X-Requested-With": "XMLHttpRequest", "Accept": "application/json"})
        try:
            return bool(r.json().get("actionIsOK"))
        except Exception:
            return False

    def retirer_nom(self, uuid_eleve: str) -> bool:
        r = self._request("DELETE", "/api/nomToEleve", data={"uuidEleveToEmpty": uuid_eleve},
                          headers={"X-Requested-With": "XMLHttpRequest", "Accept": "application/json"})
        try:
            return bool(r.json().get("actionIsOK"))
        except Exception:
            return False
