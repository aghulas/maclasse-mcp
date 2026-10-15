from maclasse_mcp.parsing import parser_versements, parser_statistiques, parser_paiements_a_valider

VERS = """<table><tr><th>Réf.</th><th>Prise de vues</th><th>Date</th><th>CA Total</th><th>CA Réel établissement</th>
<th>Part pour l'établissement</th><th>Chéques et espèces établissement</th><th>Votre versement</th><th>État</th><th>Récap.</th><th>Détail</th></tr>
<tr><td><a href="/structure/versement/projet/1/orders">1</a></td><td>Test 2025</td><td>25/02/2026</td><td>128,50 €</td><td>112,50 €</td>
<td>Commission de 30 %</td><td>0,00 €</td><td>33,75 €</td><td><span>Payé</span></td><td><a href="/versements/projet/createRecap/recapitulatif-versement-1.pdf">pdf</a></td><td>-</td></tr></table>"""

STATS = """<html><body>Codes d'accès créés 506 Utilisateurs connectés avec code d'accès 163 Codes d'accès utilisés pour une commande 28.22 %
Nombre total de visites 256 Élèves ayant commandé 70 / 506 Nombre total de commandes 46 Panier moyen par commande 25,13 € Panier moyen par code d'accès 7,09 €
<table id="rapport-ventes-table"><tr><th>Nom du produit</th><th>Type de classe</th><th>Prix</th><th>Ventes</th><th>Quantité</th><th>Montant</th><th>Répartition</th></tr>
<tr><td>Pochette A</td><td>Classe</td><td>12,00 €</td><td>10</td><td>120,00 €</td><td>50,00 %</td></tr></table></body></html>"""

VALID = """<table><tr><th>Réf.</th><th>Client</th><th>Montant</th></tr>
<tr><td>2438465</td><td>Parent Test</td><td>22,00 €</td><td><input type="hidden" name="validation[]" value="abc"></td></tr></table>"""


def test_versements():
    v = parser_versements(VERS)
    assert len(v) == 1 and v[0]["reference"] == "1" and v[0]["versement"] == 33.75 and v[0]["etat"] == "Payé"
    assert v[0]["recap_pdf"].endswith("versement-1.pdf") and v[0]["ca_total"] == 128.5


def test_statistiques():
    s = parser_statistiques(STATS)
    k = s["indicateurs"]
    assert k["codes_acces_crees"] == "506" and k["eleves_ayant_commande"] == ["70", "506"] and k["panier_moyen_commande"] == "25.13"
    assert s["produits"][0]["produit"] == "Pochette A" and s["produits"][0]["montant"] == 120.0
    assert s["produits"][0]["quantite"] == 10 and s["produits"][0]["repartition_pct"] == 50.0


def test_paiements():
    p = parser_paiements_a_valider(VALID)
    assert len(p) == 1 and p[0]["Réf."] == "2438465" and p[0]["_validation_id"] == "abc"
    assert parser_paiements_a_valider("<html><p>Vous n'avez aucune commande</p></html>") == []
