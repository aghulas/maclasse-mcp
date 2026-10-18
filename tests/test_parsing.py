"""Tests hors ligne sur des pages synthétiques (aucune donnée réelle)."""
from maclasse_mcp import parsing

PROJET = """
<html><body>
<div class="widget-body bloc-classe"><div class="classe-name"><h3>CE1A </h3></div>
 <a href="#tab-photos-indiv-aaaa1111-1111-1111-1111-111111111111">Photos individuelles</a>
 <a href="/triNomParticipants/niveau/aaaa1111-1111-1111-1111-111111111111/tri">Noms des élèves</a>
 <div id="tab-photos-indiv-aaaa1111-1111-1111-1111-111111111111">
  <fieldset class="filter-eleve" data-classe-uuid-brut="aaaa1111-1111-1111-1111-111111111111"></fieldset>
  <div class="widget-body">
   <div class="eleve-block"><div class="widget-header"><h2 class="eleve-label">Élève</h2></div><div class="widget-body"><div class="d-inline-block">
     <img class="eleve-photo" src="https://lbcache.maclasse.photo/s1/x/small/bbbb2222-2222-2222-2222-222222222222.jpeg" alt="Photo élève - Code ABCD1234">
     <div>Visite(s) : 2</div><div>Commande(s) : 1</div>
     <div class="bloc-dashed"><div>Code : ABCD1234</div>
       <button class="btn-open-modal-dl-eleve-unique" data-eleve-uuid="cccc3333-3333-3333-3333-333333333333">Fiche élève</button></div>
   </div></div></div>
   <div class="eleve-block"><div class="widget-header"><h2 class="eleve-label">DUPONT Test</h2></div><div class="widget-body"><div class="d-inline-block">
     <img class="eleve-photo" src="https://lbcache.maclasse.photo/s1/x/small/dddd4444-4444-4444-4444-444444444444.jpeg" alt="">
     <div>Visite(s) : 0</div><div>Commande(s) : 0</div>
     <div class="bloc-dashed"><div>Code : EFGH5678</div>
       <button class="btn-open-modal-dl-eleve-unique" data-eleve-uuid="eeee5555-5555-5555-5555-555555555555">Fiche élève</button></div>
   </div></div></div>
  </div>
 </div>
 <div id="tab-photos-group-aaaa1111-1111-1111-1111-111111111111">
   <img src="https://lbcache.maclasse.photo/s1/x/small/ffff6666-6666-6666-6666-666666666666.jpeg" alt="Photo de groupe 1">
   <div>Code : GRP00001</div>
 </div>
</div></body></html>
"""

TRI = """
<html><body><h1>Association de noms aux élèves</h1><p>Classe de CE1A</p>
<div id="eleves-names">
 <div data-nom-index="0" class="eleve-drag">DUPONT Test</div>
 <div data-nom-index="1" class="eleve-drag">MARTIN Essai</div>
</div>
<div class="widget-image"><img class="eleve-photo" src="https://x/small/bbbb2222-2222-2222-2222-222222222222.jpeg">
 <div class="drop-container"><div class="empty-name">aucun nom associé</div><div id="block-eleve-cccc3333-3333-3333-3333-333333333333" class="drop-zone"> </div></div></div>
<div class="widget-image"><img class="eleve-photo" src="https://x/small/dddd4444-4444-4444-4444-444444444444.jpeg">
 <div class="drop-container"><div id="block-eleve-eeee5555-5555-5555-5555-555555555555" class="drop-zone"><div class="eleve-drag">ZOLA Exemple</div></div></div></div>
</body></html>
"""

ACCUEIL = """
<html><body><div class="card"><div>Ecole test</div><div>SM26</div><a href="/project/9999aaaa-0000-0000-0000-000000000000/infos">Détails</a>
<span>EN LIGNE</span> Commandes groupées Initiales Fin le 01/11/2026 Chiffre d'affaires 1125,00 € Nombre de commandes 44</div></body></html>
"""


def test_accueil():
    p = parsing.parser_accueil(ACCUEIL)
    assert len(p) == 1
    assert p[0].uuid == "9999aaaa-0000-0000-0000-000000000000"
    assert p[0].nom == "SM26"
    assert p[0].nb_commandes == 44 and p[0].fin_commandes == "01/11/2026" and p[0].statut == "EN LIGNE"


def test_projet():
    cls = parsing.parser_projet(PROJET)
    assert len(cls) == 1
    c = cls[0]
    assert c.nom == "CE1A" and c.uuid.startswith("aaaa1111")
    assert c.nb_photos == 2 and c.nb_noms_associes == 1
    e0, e1 = c.eleves
    assert e0.code == "ABCD1234" and e0.uuid_eleve.startswith("cccc3333") and e0.photo_uuid.startswith("bbbb2222")
    assert e0.nom_associe is None and e0.visites == 2 and e0.commandes == 1
    assert e0.photo_url == "https://lbcache.maclasse.photo/s1/x/small/bbbb2222-2222-2222-2222-222222222222.jpeg"
    assert e1.nom_associe == "DUPONT Test"
    assert c.photos_groupe == [{"photo_uuid": "ffff6666-6666-6666-6666-666666666666", "code": "GRP00001"}]


def test_association():
    p = parsing.parser_association(TRI)
    assert p.classe == "CE1A"
    assert p.noms_disponibles == [{"index": 0, "nom": "DUPONT Test"}, {"index": 1, "nom": "MARTIN Essai"}]
    assert p.photos[0]["uuid_eleve"].startswith("cccc3333") and p.photos[0]["nom_associe"] is None
    assert p.photos[1]["nom_associe"] == "ZOLA Exemple"


def test_normaliser():
    assert parsing.normaliser("  DE\tLA  Tour  Élodie ") == "de la tour elodie"


FRATRIES = """
<html><body>
<div class="bloc-classe"><div class="classe-name"><h3 class="no-mb">Fratries
 <span class="badge-fratrie" data-toggle="popover"><i class="las la-user-friends"></i> Fratrie</span></h3></div>
 <a href="/triNomParticipants/niveau/ffff1111-1111-1111-1111-111111111111/tri">Noms des élèves</a>
 <div id="tab-photos-indiv-ffff1111-1111-1111-1111-111111111111">
  <fieldset class="filter-eleve" data-classe-uuid-brut="ffff1111-1111-1111-1111-111111111111"></fieldset>
 </div></div>
</body></html>
"""


def test_projet_classe_fratries():
    c = parsing.parser_projet(FRATRIES)[0]
    assert c.nom == "Fratries" and c.type_classe == "fratrie"
    assert parsing.parser_projet(PROJET)[0].type_classe == "classe"
