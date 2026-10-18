---
name: "maclasse-suivi-commandes"
description: "Suivre les commandes de photos scolaires de l'École Sainte-Marie sur ecole.maclasse.photo (MCP maclasse) : commandes par classe, statistiques, paiements par chèque/espèces à valider, versements à l'OGEC et récapitulatifs pour la comptabilité."
---

# Suivi des commandes et encaissements maclasse.photo

À utiliser quand l'utilisateur demande où en sont les commandes de photos, combien de familles ont commandé, s'il reste des chèques ou espèces à valider, ce que la plateforme a versé à l'OGEC, ou veut les pièces pour la comptabilité. Tout passe par le MCP `maclasse` (lecture seule ici). Pour les photos elles-mêmes : skill `maclasse-photos-eleves`.

## Ce qu'il faut savoir

- Une prise de vue par an (`maclasse_prises_de_vues`, `archives=True` pour les années précédentes). Commandes groupées jusqu'à une date de fin (ex. 01/11/2026 pour SM26), livraison par le photographe ; commandes individuelles désactivées à Sainte-Marie.
- Encaissement « au nom de l'établissement » : carte bancaire sur la plateforme, ou chèque / espèces déposés sous enveloppe à l'école. Un paiement reçu à l'école doit être **validé sur la plateforme** (menus Chèques / Espèces) pour que la commande parte en production : action **irréversible**, faite à la main par le secrétariat, paiement en main. Le MCP ne la fait pas (`maclasse_paiements_a_valider` liste seulement l'attente).
- Part pour l'établissement : commission nette de 30 % du CA. La plateforme calcule les versements les 10 et 25 du mois à 3h01 et paie le solde en faveur de l'OGEC ces jours-là ; une commande non expédiée au calcul passe au versement suivant. Chaque versement a un récapitulatif PDF (`maclasse_versements(telecharger_recaps=True)` → `~/Charlemagne/photos/maclasse/versements/`) : pièce justificative à rapprocher du relevé bancaire de l'OGEC.
- Codes d'accès des élèves : destinés aux familles, ne pas les recopier dans la conversation (`maclasse_eleves` ne les renvoie que sur demande). Une famille qui a perdu son code : `maclasse_fiches_acces(uuid_projet)` télécharge le PDF de tous les coupons (URL famille **https://apdl.maclasse.photo/**, QR code, code) : extraire la page de la famille, ne jamais transmettre le PDF entier. Les codes de fratrie sont distincts des codes individuels.

## Déroulé

1. **Point commandes** : `maclasse_commandes(uuid_projet)` → nombre, total, totaux par classe (les commandes multi-enfants sont sous « plusieurs classes » et comptées, en nombre, pour chaque classe) et par mode de paiement ; CSV conservé localement. Compléter par `maclasse_statistiques` (codes créés, connectés, taux de commande, panier moyen, ventes par produit). Pour une classe : `maclasse_classes` (visites, commandes par classe).
2. **Paiements à l'école** : `maclasse_paiements_a_valider("cheques")` et `("especes")` ; s'il y en a, lister référence, client, montant et rappeler la validation manuelle (paiement en main, irréversible). Prévenir le secrétariat si des commandes attendent depuis longtemps : non validées, elles ne sont pas produites.
3. **Versements** : `maclasse_versements` → référence, date, CA, part, montant versé, état (Payé / en attente). Avec `telecharger_recaps=True`, enregistrer les PDF et les proposer comme pièces pour la comptabilité (skill `charlemagne-compta-encaissements` pour le rapprochement côté Charlemagne, skill `coffre-fort-ogec` pour l'archivage).
4. **Relances familles** (avant la fin de période groupée) : cibler les photos **jamais consultées** (`maclasse_eleves(uuid_projet, classe=…, sans_visite=True)` ; compteur `visites` par photo), pas les familles qui ont vu et choisi de ne pas commander. Message EcoleDirecte via la skill `ecoledirecte-communication-familles`, un message par famille quand il contient un code (code + prénoms + aperçu **filigrané** `maclasse_telecharger_apercus(uuid_projet, classe, sans_visite=True)` en pièce jointe, jamais la vignette propre), destinataires = tous les responsables en Cci. Texte de référence (18/10/2026, fratries, 63 brouillons sur le compte du secrétariat) : rappel de la prise de vue, aperçu joint, « cette photo n'a pas encore été consultée », étapes (1. https://apdl.maclasse.photo/ 2. code), code différent des codes individuels, livraison offerte jusqu'à la date de fin de commande groupée puis frais de livraison, photo facultative. Jamais de liste nominative des familles n'ayant pas commandé dans la conversation sans demande explicite ; pendant les vacances, prévoir qui enverra les brouillons avant l'échéance.
5. **Rapport** en quelques lignes : commandes et CA, paiements en attente, versements reçus / à venir, pièces enregistrées.

## Vigilance données

Données nominatives des familles (noms, emails, montants) : les résumés en chat restent agrégés par classe ; les emails ne sont renvoyés que si `avec_emails=True` est demandé. Rien n'est écrit sur la plateforme par cette skill.