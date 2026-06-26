"""Service de stockage des images (logo, couverture d'en-tête, bannière).

Stratégie (offline-/panne-tolérante) :
- Si Supabase Storage est configuré (SUPABASE_URL + SUPABASE_SERVICE_ROLE_KEY),
  on tente l'upload dans le bucket (avec quelques essais en cas de coupure
  réseau / DNS) et on retourne l'URL publique.
- En cas d'échec **réseau** (DNS, timeout, 5xx) on **bascule automatiquement
  sur le disque local** au lieu de renvoyer une erreur : l'utilisateur n'est
  jamais bloqué, le fichier est servi via `GET /uploads/<filename>`.
- Si Supabase n'est pas configuré (tests, clé absente), disque local direct.

L'upload Supabase se fait avec la clé `service_role` (côté serveur uniquement),
ce qui contourne les policies RLS. La lecture est publique car le bucket l'est.
"""
import logging
import os
import time
import uuid

import requests
from flask import current_app, request

logger = logging.getLogger(__name__)

_CONTENT_TYPES = {
    'png': 'image/png',
    'jpg': 'image/jpeg',
    'jpeg': 'image/jpeg',
    'gif': 'image/gif',
    'webp': 'image/webp',
}

# Types MIME Office forcés côté serveur (le client peut envoyer un type
# incohérent). Le bucket Supabase doit les autoriser (allowed_mime_types).
_OFFICE_TYPES = {
    'doc': 'application/msword',
    'docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
}


def supabase_enabled() -> bool:
    return bool(
        current_app.config.get('SUPABASE_URL')
        and current_app.config.get('SUPABASE_SERVICE_ROLE_KEY')
    )


def save_image(file_storage, ext: str, folder: str = 'uploads') -> str:
    """Persiste un fichier (Werkzeug FileStorage) et retourne son URL publique.

    Args:
        file_storage: objet Werkzeug FileStorage.
        ext: extension du fichier sans le point (ex. 'png', 'docx').
        folder: sous-dossier de stockage ('logos', 'templates', …).
                Évite de mélanger images et documents dans le même répertoire.
    """
    filename = f'{folder}/{uuid.uuid4().hex}.{ext}'
    data = file_storage.read()
    content_type = file_storage.mimetype or _CONTENT_TYPES.get(
        ext, 'application/octet-stream'
    )
    # On force le vrai type MIME Office pour .doc/.docx (déterministe). Le
    # bucket Supabase doit l'autoriser via allowed_mime_types.
    if ext in _OFFICE_TYPES:
        content_type = _OFFICE_TYPES[ext]

    if supabase_enabled():
        url = _upload_to_supabase(filename, data, content_type)
        if url is not None:
            return url
        # Supabase momentanément injoignable → repli disque local (jamais d'erreur).
        logger.warning(
            'Supabase Storage injoignable, repli sur le disque local pour %s',
            filename,
        )
    return _save_local(filename, data)


# Nombre de tentatives d'upload Supabase avant repli sur le disque local.
_SUPABASE_MAX_ATTEMPTS = 3


def _upload_to_supabase(filename: str, data: bytes, content_type: str):
    """Tente l'upload Supabase. Retourne l'URL publique, ou ``None`` si le
    stockage est injoignable (l'appelant bascule alors sur le disque local)."""
    base = current_app.config['SUPABASE_URL'].rstrip('/')
    bucket = current_app.config['SUPABASE_STORAGE_BUCKET']
    key = current_app.config['SUPABASE_SERVICE_ROLE_KEY']

    upload_url = f'{base}/storage/v1/object/{bucket}/{filename}'
    headers = {
        'Authorization': f'Bearer {key}',
        'apikey': key,
        'Content-Type': content_type,
        'x-upsert': 'true',
    }

    last_error = None
    for attempt in range(1, _SUPABASE_MAX_ATTEMPTS + 1):
        try:
            resp = requests.post(upload_url, data=data, headers=headers, timeout=30)
        except requests.RequestException as exc:
            # Coupure réseau / DNS (ex. getaddrinfo failed) : on réessaie.
            last_error = exc
            logger.warning(
                'Upload Supabase tentative %s/%s échouée (%s)',
                attempt, _SUPABASE_MAX_ATTEMPTS, exc,
            )
            if attempt < _SUPABASE_MAX_ATTEMPTS:
                time.sleep(0.8 * attempt)
            continue

        if resp.status_code in (200, 201):
            return f'{base}/storage/v1/object/public/{bucket}/{filename}'

        # 5xx côté Supabase : transitoire, on réessaie ; sinon on abandonne
        # proprement (repli local) sans bloquer l'utilisateur.
        logger.warning(
            'Upload Supabase a renvoyé %s : %s',
            resp.status_code, resp.text[:200],
        )
        if 500 <= resp.status_code < 600 and attempt < _SUPABASE_MAX_ATTEMPTS:
            time.sleep(0.8 * attempt)
            continue
        return None

    logger.error('Upload Supabase abandonné après %s tentatives : %s',
                 _SUPABASE_MAX_ATTEMPTS, last_error)
    return None


def _save_local(filename: str, data: bytes) -> str:
    root = current_app.config['UPLOAD_FOLDER']
    dest = os.path.join(root, filename)
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    with open(dest, 'wb') as fh:
        fh.write(data)
    return f"{request.host_url.rstrip('/')}/uploads/{filename}"


def delete_object(url: str) -> None:
    """Supprime un fichier précédemment uploadé à partir de son URL publique.

    Best-effort : un échec n'est jamais propagé (l'orphelin restera, sans
    bloquer l'utilisateur). Gère aussi bien les URLs Supabase publiques que les
    fichiers servis localement (`/uploads/...`).
    """
    if not url:
        return

    # Cas Supabase : .../storage/v1/object/public/<bucket>/<path>
    marker = '/storage/v1/object/public/'
    if marker in url and supabase_enabled():
        try:
            base = current_app.config['SUPABASE_URL'].rstrip('/')
            bucket = current_app.config['SUPABASE_STORAGE_BUCKET']
            key = current_app.config['SUPABASE_SERVICE_ROLE_KEY']
            path = url.split(f'{marker}{bucket}/', 1)[-1]
            requests.delete(
                f'{base}/storage/v1/object/{bucket}/{path}',
                headers={'Authorization': f'Bearer {key}', 'apikey': key},
                timeout=15,
            )
        except requests.RequestException as exc:
            logger.warning('Suppression Supabase échouée pour %s : %s', url, exc)
        return

    # Cas local : /uploads/<path>
    if '/uploads/' in url:
        try:
            rel = url.split('/uploads/', 1)[1]
            dest = os.path.join(current_app.config['UPLOAD_FOLDER'], rel)
            if os.path.isfile(dest):
                os.remove(dest)
        except OSError as exc:
            logger.warning('Suppression locale échouée pour %s : %s', url, exc)
