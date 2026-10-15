---
name: "maclasse-photos-eleves"
description: "Récupérer les photos individuelles des élèves de l'École Sainte-Marie sur ecole.maclasse.photo et les préparer pour Charlemagne (affectation automatique) et Edumoov/Educartable, avec rapprochement par trombinoscopes et liste Charlemagne."
---

# Photos élèves maclasse.photo → Charlemagne / Edumoov

À utiliser dès que l'utilisateur parle de photos de classe, photos des élèves, maclasse.photo, trombinoscope, vignettes, ou veut charger les photos dans Charlemagne, EcoleDirecte ou Educartable. Produit un dossier `IDELEVE.jpg` pour l'affectation automatique Charlemagne et un dossier par classe `NOM Prénom.jpg` pour Edumoov, plus un rapport. La skill ne fait jamais l'affectation dans Charlemagne ni l'envoi vers Edumoov : elle livre les dossiers, l'utilisateur lance les traitements natifs.

## Ce qu'il faut savoir sur la plateforme

- Espace école : https://ecole.maclasse.photo (compte secretariat@saintemarie-fontainebleau.fr ; le mot de passe est saisi par l'utilisateur dans le navigateur intégré, jamais par Claude). La session persiste dans le navigateur intégré.
- Une prise de vue par an (ex. SM26 = 17/09/2026). Page projet `/project/{uuid}/infos` : boutons « Vignettes élèves », « Trombinoscope », accordéon par classe avec onglet « Noms des élèves » (`/triNomParticipants/niveau/{uuid}/tri`).
- Les images affichées sur le site sont **filigranées** : ne jamais les récupérer. Le seul export propre est « Vignettes élèves » (ZIP, un dossier par classe, JPG 400×533 ~60 Ko, sans filigrane, nommé par code d'accès tant qu'aucun nom n'est associé). Le CDN et le site ne sont joignables que depuis le navigateur intégré (pas depuis le shell).
- Le trombinoscope PDF (par classe, 6 colonnes, ordre de création des fiches) peut afficher sous chaque photo soit « le nom de l'élève » (= code d'accès si rien n'est associé), soit « le nom de la photo » (= nom de fichier du photographe, en pratique `NOM Prénom.jpg`). **La paire de ces deux PDF donne la correspondance code ↔ élève** sans association manuelle. Les deux PDF doivent être générés avec les mêmes options de disposition.
- Les photos de groupe ne sont pas téléchargeables sans filigrane par l'école : les demander au photographe.
- Détails complets (uuid des classes, formulaires, pistes MCP) : doc projet `maclasse-photo-fonctionnement.md` du projet « MCP et skills pour ecole.maclasse.photo ».

## Déroulé

1. **Liste élèves Charlemagne** : appeler l'outil MCP `liste_eleves` (tous actifs) et enregistrer la réponse JSON telle quelle dans `~/Charlemagne/photos/maclasse/<année>/liste_eleves.json`. Vérifier que les effectifs par classe sont cohérents avec ceux de la plateforme (nb de photos par classe) et signaler les écarts (absents le jour de la prise de vue).
2. **Correspondance classes** : écrire `classes_map.json` = `{ "classe maclasse": "classe Charlemagne" }` (ex. `"CE1A": "CE1 A"`, `"MS-GS": "MGS"`, `"PS": "TPSPS"`, `"PS-MS": "PS/MS"`). Les classes maclasse hors correspondance (« Fratries ») sont ignorées par le script.
3. **(Optionnel, pour les familles)** importer les noms sur la plateforme : un CSV par classe `Nom;Prénom` UTF-8 avec entête, option « Nom / Prénom », via l'onglet « Noms des élèves ». Dans le navigateur intégré, le fichier peut être injecté dans l'input `csv` du formulaire (`DataTransfer`) puis le formulaire soumis. Ne jamais lancer « Attribution automatique » sans contrôle : l'ordre de prise de vue n'est pas l'ordre alphabétique (absents, enfants photographiés dans le désordre).
4. **Exports depuis le navigateur intégré** (demander l'accord avant chaque téléchargement, les fichiers arrivent dans `~/Downloads`) :
   - « Vignettes élèves » → ZIP (format de nom indifférent tant que rien n'est associé).
   - « Trombinoscope » avec « Ajouter le nom de l'élève » → `trombinoscope_codes.pdf`.
   - « Trombinoscope » avec « Ajouter le nom de la photo » → `trombinoscope_noms_photo.pdf`.
   Ranger ces trois fichiers dans `~/Charlemagne/photos/maclasse/<année>/`.
5. **Script** (sur le Mac, pdfplumber est installé) :
   `python3 ~/Charlemagne/photos/maclasse/preparer_photos.py --vignettes vignettes.zip --trombi-codes trombinoscope_codes.pdf --trombi-noms trombinoscope_noms_photo.pdf --eleves liste_eleves.json --classes classes_map.json --sortie .`
   Il produit `charlemagne_ideleve/`, `edumoov_par_classe/`, `index_photos_eleves.csv`, `mapping_codes_noms.json`, `RAPPORT.md`. Il n'écrase jamais les sources.
6. **Relire le rapport avec l'utilisateur** : rapprochements approximatifs (orthographe du photographe ≠ Charlemagne — chacun doit être unique et plausible), photos non appariées (à arbitrer, jamais devinées), élèves sans photo. Si les deux trombinoscopes n'ont pas le même nombre de photos par classe, les regénérer avec les mêmes options.
7. **Rappeler les étapes natives** : Charlemagne › Administratif › Outils › Affectation des photos › Élèves (RAZ optionnelle, puis affectation automatique sur `charlemagne_ideleve/`, nommage par identifiant), puis « À intégrer au prochain envoi » pour EcoleDirecte ; Edumoov : photos de profil depuis `edumoov_par_classe/`. Conseiller une relecture du trombinoscope « avec noms » par les enseignant·e·s avant l'import : une photo mal affectée écrase la mauvaise fiche.

## Vigilance données

Photos nominatives d'élèves mineurs : pas de photos ni de noms dans des exemples ou du code versionné, dossiers livrés uniquement à l'utilisateur, rien de publié. Le mot de passe de la plateforme n'est jamais saisi par Claude ni recopié dans des fichiers.