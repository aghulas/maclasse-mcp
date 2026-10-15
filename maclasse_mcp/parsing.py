"""Analyse des pages HTML de ecole.maclasse.photo (aucune API JSON côté école).

Fonctions pures, testables hors ligne. Structures observées le 15/10/2026 :
- Accueil `/` : une carte par prise de vue avec un lien « Détails » vers /project/{uuid}/infos.
- Page projet `/project/{uuid}/infos` : pour chaque classe un `fieldset.filter-eleve[data-classe-uuid-brut]`,
  un onglet `#tab-photos-indiv-{uuid}` (cartes élèves : img.eleve-photo, « Code : XXXXXXXX »,
  bouton `.btn-open-modal-dl-eleve-unique[data-eleve-uuid]`), un onglet `#tab-photos-group-{uuid}`
  et un lien « Noms des élèves » vers /triNomParticipants/niveau/{uuid}/tri.
- Page d'association `/triNomParticipants/niveau/{uuid}/tri` : `#eleves-names .eleve-drag[data-nom-index]`
  (noms disponibles) et, par photo, `.drop-zone#block-eleve-{uuidEleve}` contenant le nom attribué.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field, asdict
from typing import Any

from bs4 import BeautifulSoup

CODE_RE = re.compile(r"Code\s*:\s*([A-Z0-9]{6,12})")
UUID_RE = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")


def normaliser(s: str | None) -> str:
    """Minuscules, sans accents, espaces réduits — pour comparer des noms."""
    s = re.sub(r"\s+", " ", (s or "").replace("\t", " ")).strip()
    return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()


@dataclass
class PriseDeVues:
    nom: str
    uuid: str
    statut: str = ""
    fin_commandes: str = ""
    nb_commandes: int | None = None
    chiffre_affaires: str = ""


@dataclass
class Eleve:
    code: str
    uuid_eleve: str | None
    photo_uuid: str | None
    nom_associe: str | None
    visites: int | None
    commandes: int | None


@dataclass
class Classe:
    nom: str
    uuid: str
    eleves: list[Eleve] = field(default_factory=list)
    photos_groupe: list[dict[str, Any]] = field(default_factory=list)

    @property
    def nb_photos(self) -> int:
        return len(self.eleves)

    @property
    def nb_noms_associes(self) -> int:
        return sum(1 for e in self.eleves if e.nom_associe)


def _int(s: str | None) -> int | None:
    if s is None:
        return None
    m = re.search(r"-?\d+", s)
    return int(m.group(0)) if m else None


def parser_accueil(html: str) -> list[PriseDeVues]:
    soup = BeautifulSoup(html, "html.parser")
    out: list[PriseDeVues] = []
    for a in soup.select('a[href*="/project/"][href$="/infos"]'):
        m = UUID_RE.search(a["href"])
        if not m:
            continue
        card = a
        for _ in range(8):
            if card.parent is None:
                break
            card = card.parent
            txt = card.get_text(" ", strip=True)
            if "Chiffre d'affaires" in txt or "Nombre de commandes" in txt:
                break
        txt = card.get_text("\n", strip=True)
        lines = [line.strip() for line in txt.split("\n") if line.strip()]
        nom = ""
        for i, line in enumerate(lines):
            if line == "Détails" and i > 0:
                nom = lines[i - 1]
                break
        statut = "EN LIGNE" if "EN LIGNE" in txt else ("HORS LIGNE" if "HORS LIGNE" in txt else "")
        fin = ""
        mf = re.search(r"Fin le (\d{2}/\d{2}/\d{4})", txt)
        if mf:
            fin = mf.group(1)
        nb = None
        mn = re.search(r"Nombre de commandes\s*(\d+)", txt)
        if mn:
            nb = int(mn.group(1))
        ca = ""
        mc = re.search(r"Chiffre d'affaires\s*([\d\s,\.]+€)", txt)
        if mc:
            ca = mc.group(1).strip()
        if not any(p.uuid == m.group(0) for p in out):
            out.append(PriseDeVues(nom=nom, uuid=m.group(0), statut=statut, fin_commandes=fin, nb_commandes=nb, chiffre_affaires=ca))
    return out


def parser_projet(html: str) -> list[Classe]:
    soup = BeautifulSoup(html, "html.parser")
    classes: list[Classe] = []
    for fs in soup.select("fieldset.filter-eleve[data-classe-uuid-brut]"):
        uuid = fs["data-classe-uuid-brut"]
        # Nom de la classe : <div class="bloc-classe"><div class="classe-name"><h3>CE1A</h3> … (structure du 15/10/2026)
        link = soup.select_one(f'a[href*="triNomParticipants/niveau/{uuid}/tri"]')
        nom = ""
        if link is not None:
            bloc = link.find_parent(class_="bloc-classe")
            h = bloc.select_one(".classe-name h3, .classe-name h4, .classe-name") if bloc is not None else None
            if h is not None:
                nom = h.get_text(" ", strip=True)
            else:  # repli : premier titre du conteneur
                card = link
                for _ in range(10):
                    if card.parent is None:
                        break
                    card = card.parent
                    hh = card.find(["h3", "h4"])
                    if hh is not None:
                        nom = hh.get_text(" ", strip=True)
                        break
        classe = Classe(nom=nom, uuid=uuid)
        indiv = soup.select_one(f"#tab-photos-indiv-{uuid}")
        if indiv is not None:
            for btn in indiv.select("button.btn-open-modal-dl-eleve-unique"):
                card = btn
                for _ in range(6):
                    if card.parent is None:
                        break
                    card = card.parent
                    if CODE_RE.search(card.get_text(" ", strip=True)) and card.find("img") is not None:
                        break
                txt = card.get_text("\n", strip=True)
                code = CODE_RE.search(txt)
                img = card.find("img")
                photo_uuid = None
                if img is not None:
                    pm = UUID_RE.search(img.get("src", ""))
                    photo_uuid = pm.group(0) if pm else None
                # Nom associé : <div class="eleve-block"><div class="widget-header"><h2 class="eleve-label">NOM Prénom</h2>
                # (« Élève » tant qu'aucun nom n'est associé — structure vérifiée le 15/10/2026)
                nom_associe = None
                bloc = btn.find_parent(class_="eleve-block")
                lab = bloc.select_one(".eleve-label") if bloc is not None else None
                if lab is not None:
                    t = lab.get_text(" ", strip=True)
                    if t and t.lower() not in ("élève", "eleve"):
                        nom_associe = t
                classe.eleves.append(
                    Eleve(
                        code=code.group(1) if code else "",
                        uuid_eleve=btn.get("data-eleve-uuid"),
                        photo_uuid=photo_uuid,
                        nom_associe=nom_associe,
                        visites=_int(re.search(r"Visite\(s\)\s*:\s*(\d+)", txt).group(1)) if re.search(r"Visite\(s\)\s*:\s*(\d+)", txt) else None,
                        commandes=_int(re.search(r"Commande\(s\)\s*:\s*(\d+)", txt).group(1)) if re.search(r"Commande\(s\)\s*:\s*(\d+)", txt) else None,
                    )
                )
        group = soup.select_one(f"#tab-photos-group-{uuid}")
        if group is not None:
            txt = group.get_text("\n", strip=True)
            codes = CODE_RE.findall(txt)
            imgs = [i.get("src") for i in group.select("img[alt^='Photo de groupe']")]
            for i, src in enumerate(imgs):
                pm = UUID_RE.search(src or "")
                classe.photos_groupe.append({"photo_uuid": pm.group(0) if pm else None, "code": codes[i] if i < len(codes) else None})
        classes.append(classe)
    return classes


@dataclass
class PageAssociation:
    classe: str
    noms_disponibles: list[dict[str, Any]]  # {index, nom}
    photos: list[dict[str, Any]]  # {uuid_eleve, photo_uuid, nom_associe}


def parser_association(html: str) -> PageAssociation:
    soup = BeautifulSoup(html, "html.parser")
    m = re.search(r"Classe de (\S+)", soup.get_text(" ", strip=True))
    noms = [{"index": int(d["data-nom-index"]), "nom": d.get_text(" ", strip=True)}
            for d in soup.select("#eleves-names .eleve-drag[data-nom-index]") if d.get("data-nom-index", "") != ""]
    photos = []
    for dz in soup.select(".drop-zone[id^='block-eleve-']"):
        uuid_eleve = dz["id"][len("block-eleve-"):]
        card = dz.parent.parent if dz.parent is not None else None
        img = card.find("img") if card is not None else None
        pm = UUID_RE.search(img.get("src", "")) if img is not None else None
        assoc = dz.get_text(" ", strip=True) or None
        photos.append({"uuid_eleve": uuid_eleve, "photo_uuid": pm.group(0) if pm else None, "nom_associe": assoc})
    return PageAssociation(classe=m.group(1) if m else "", noms_disponibles=noms, photos=photos)


def to_dict(obj: Any) -> Any:
    if isinstance(obj, list):
        return [to_dict(o) for o in obj]
    if hasattr(obj, "__dataclass_fields__"):
        d = asdict(obj)
        if isinstance(obj, Classe):
            d["nb_photos"] = obj.nb_photos
            d["nb_noms_associes"] = obj.nb_noms_associes
        return d
    return obj
