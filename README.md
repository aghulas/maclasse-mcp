# maclasse-mcp

Serveur MCP **non officiel** pour l'espace établissement [ecole.maclasse.photo](https://ecole.maclasse.photo)
(photos scolaires). Il lit les pages HTML du site avec le compte de l'école (aucune API publique) et
prépare les photos des élèves pour Charlemagne (affectation automatique par IDELEVE) et Edumoov/Educartable.

## Outils

| Outil | Rôle | Écrit sur la plateforme |
|---|---|---|
| `maclasse_statut` | connexion, dossier local, écritures, jetons en attente | non |
| `maclasse_prises_de_vues` | prises de vues (uuid projet, commandes, CA) | non |
| `maclasse_classes` | classes d'une prise de vue (uuid, nb photos, noms associés) | non |
| `maclasse_eleves` | photos individuelles (uuid élève, nom associé, visites, commandes ; codes sur demande) | non |
| `maclasse_association_classe` | noms disponibles et photos d'une classe (page « Noms des élèves ») | non |
| `maclasse_commandes_html` | texte de la page des commandes (non cartographiée) | non |
| `maclasse_telecharger_vignettes` | ZIP des vignettes (400×533, sans filigrane) → dossier local | non |
| `maclasse_telecharger_trombinoscope` | PDF trombinoscope (`codes`, `nom_photo`, `aucun`) → dossier local | non |
| `maclasse_preparer_photos` | pipeline complet → `charlemagne_ideleve/`, `edumoov_par_classe/`, index, rapport | non |
| `maclasse_importer_noms_prepare` | import d'une liste Nom/Prénom pour une classe | oui (2 temps) |
| `maclasse_associer_noms_prepare` | association nom ↔ photo | oui (2 temps) |
| `maclasse_retirer_noms_prepare` | retrait d'un nom associé | oui (2 temps) |
| `maclasse_write_confirm` / `maclasse_write_cancel` | exécution / abandon d'une écriture préparée | — |

Toute écriture exige `MACLASSE_ENABLE_WRITES=1` **et** une confirmation explicite par jeton.

## Installation (Claude Desktop, macOS)

```bash
cd ~/dev/maclasse-mcp
python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"
.venv/bin/python -m pytest -q
mkdir -p ~/.maclasse-mcp && chmod 700 ~/.maclasse-mcp
# ~/.maclasse-mcp/credentials.json : {"email": "...", "password": "..."}  (chmod 600)
```

`claude_desktop_config.json` :

```json
"maclasse": {
  "command": "/Users/<moi>/dev/maclasse-mcp/.venv/bin/maclasse-mcp",
  "env": {"MACLASSE_DOWNLOAD_DIR": "/Users/<moi>/Charlemagne/photos/maclasse", "MACLASSE_ENABLE_WRITES": "0"}
}
```

Variables : `MACLASSE_EMAIL`/`MACLASSE_PASSWORD` ou `MACLASSE_CREDENTIALS` (fichier JSON), `MACLASSE_DOWNLOAD_DIR`,
`MACLASSE_ENABLE_WRITES`, `MACLASSE_TIMEOUT`.

## Pipeline hors MCP

```bash
.venv/bin/python -m maclasse_mcp.preparer --vignettes vignettes.zip --trombi-codes trombinoscope_codes.pdf \
  --trombi-noms trombinoscope_noms_photo.pdf --eleves liste_eleves.json --classes classes_map.json --sortie .
```

## Routes observées

Voir l'en-tête de `maclasse_mcp/client.py`. Découvertes le 15/10/2026 à partir du bundle FOS JS Routing
de l'application (`aTriNomsEleves.*.js`, `eEcole.*.js`). Les images affichées sur le site sont filigranées ;
seuls les exports sont exploitables.

## Données

Photos nominatives d'élèves mineurs et codes d'accès destinés aux familles : rien n'est versionné ici
(`.gitignore` exclut ZIP, PDF, JPG), les tests utilisent des pages synthétiques, les fichiers téléchargés
sont créés en 600 et jamais écrasés.
