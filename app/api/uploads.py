"""Upload et service d'images (logo, couverture d'en-tête, bannière de pied).

En dev/local, les fichiers sont stockés sur le disque du backend (dossier
`UPLOAD_FOLDER`) et servis via `GET /uploads/<filename>`. L'URL retournée est
construite à partir de l'hôte de la requête (ex. http://192.168.1.128:5000/...)
afin d'être joignable depuis le téléphone sur le même réseau WiFi.
"""
from flask import Blueprint, request, current_app, send_from_directory

from app.services.storage_service import save_image, delete_object
from app.utils.auth import login_required
from app.utils.errors import ApiError
from app.utils.responses import success, no_content

uploads_bp = Blueprint('uploads', __name__)


def _extension(filename: str) -> str:
    return filename.rsplit('.', 1)[-1].lower() if '.' in filename else ''


@uploads_bp.post('/api/uploads')
@login_required
def upload_image():
    if 'file' not in request.files:
        raise ApiError('Aucun fichier fourni (champ « file » manquant).', 400)

    file = request.files['file']
    if not file or not file.filename:
        raise ApiError('Fichier vide.', 400)

    ext = _extension(file.filename)
    allowed = current_app.config['ALLOWED_IMAGE_EXTENSIONS']
    if ext not in allowed:
        raise ApiError(
            f'Format non supporté. Formats acceptés : {", ".join(sorted(allowed))}.',
            400,
        )

    # Supabase Storage si configuré, sinon disque local (cf. storage_service).
    url = save_image(file, ext, folder='logos')
    # Extraire le chemin relatif depuis /uploads/ (mode local : 'logos/abc.png')
    # ou juste le dernier segment pour Supabase (usage affichage uniquement).
    filename = url.split('/uploads/', 1)[1] if '/uploads/' in url else url.rsplit('/', 1)[-1]
    return success(data={'url': url, 'filename': filename})


@uploads_bp.delete('/api/uploads')
@login_required
def delete_upload():
    """Supprime un fichier précédemment uploadé à partir de son URL.

    L'URL peut être passée en query (`?url=`) ou dans le corps JSON (`{"url": …}`).
    Best-effort : renvoie 204 même si le fichier n'existe plus.
    """
    url = request.args.get('url')
    if not url and request.is_json:
        url = (request.get_json(silent=True) or {}).get('url')
    if url:
        delete_object(url)
    return no_content()


@uploads_bp.get('/uploads/<path:filename>')
def serve_upload(filename):
    """Service local des images (fallback quand Supabase n'est pas configuré)."""
    return send_from_directory(current_app.config['UPLOAD_FOLDER'], filename)
