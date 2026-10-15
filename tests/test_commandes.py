from maclasse_mcp.parsing import parser_commandes_csv

CSV = '''Classe,"Montant (€)","N° de commande","Mode de paiement","Code élève","Nom et prénom du/des élève(s)","Email du client","Nom et prénom du client","Date de paiement","Type de commande","Mode d'encaissement comptable","Part pour l'établissement"
CE1B,"22,00",1000001,"Carte bancaire",ABCD1234,"DUPONT Test",test@example.org,"Dupont Parent","15/10/2026","Commande groupée","Au nom de l'établissement","6,60"
CM2B,"9,00",1000002,"Chèque",EFGH5678,"MARTIN Essai",m@example.org,"Martin Parent","15/10/2026","Commande groupée","Au nom de l'établissement","2,70"
'''


def test_parser_commandes():
    rows = parser_commandes_csv(CSV)
    assert len(rows) == 2
    assert rows[0]["classe"] == "CE1B" and rows[0]["montant"] == 22.0 and rows[0]["part_etablissement"] == 6.6
    assert rows[1]["paiement"] == "Chèque" and rows[1]["reference"] == "1000002" and rows[1]["code"] == "EFGH5678"
    assert rows[0]["email_client"] == "test@example.org"
