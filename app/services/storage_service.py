"""Service de stockage des images (logo, couverture d'en-tête, bannière).

Stratégie :
- Si Supabase Storage est configuré (SUPABASE_URL + SUPABASE_SERVICE_ROLE_KEY),
  l'image est uploadée dans le bucket et l'URL publique est retournée.
- Sinon (ex. tests, ou clé non renseignée), l'image est sauvegardée sur le
  disque local et servie via `GET /uploads/<filename>`.

L'upload Supabase se fait avec la clé `service_role` (côté serveur uniquement),
ce qui contourne les policies RLS — aucune policy n'est donc nécessaire sur le
bucket. La lecture est publique car le bucket est public.
"""
import os
import uuid

import requests
from flask import current_app, request

from app.utils.errors import ApiError

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
        return _upload_to_supabase(filename, data, content_type)
    return _save_local(filename, data)


def _upload_to_supabase(filename: str, data: bytes, content_type: str) -> str:
    base = current_app.config['SUPABASE_URL'].rstrip('/')
    bucket = current_app.config['SUPABASE_STORAGE_BUCKET']
    key = current_app.config['SUPABASE_SERVICE_ROLE_KEY']

    upload_url = f'{base}/storage/v1/object/{bucket}/{filename}'
    try:
        resp = requests.post(
            upload_url,
            data=data,
            headers={
                'Authorization': f'Bearer {key}',
                'apikey': key,
                'Content-Type': content_type,
                'x-upsert': 'true',
            },
            timeout=30,
        )
    except requests.RequestException as exc:
        raise ApiError(f'Stockage Supabase injoignable : {exc}', 502)

    if resp.status_code not in (200, 201):
        raise ApiError(
            f'Échec de l\'upload vers Supabase ({resp.status_code}) : {resp.text[:200]}',
            502,
        )

    return f'{base}/storage/v1/object/public/{bucket}/{filename}'


def _save_local(filename: str, data: bytes) -> str:
    root = current_app.config['UPLOAD_FOLDER']
    dest = os.path.join(root, filename)
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    with open(dest, 'wb') as fh:
        fh.write(data)
    return f"{request.host_url.rstrip('/')}/uploads/{filename}"
