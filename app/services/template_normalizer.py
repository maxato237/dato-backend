"""Normalisation d'un modèle de devis .docx pour un rendu PDF **identique**
entre Microsoft Word et LibreOffice.

Problème résolu
---------------
Les modèles d'entreprise (en-tête / pied de page = bandeau, logo, WordArt…)
utilisent souvent des images **flottantes ancrées à un paragraphe**
(``positionV relativeFrom="paragraph"``). Word et LibreOffice ne calculent
pas la position d'un tel ancrage de la même façon (hauteur cumulée des
paragraphes, métriques de police), d'où un **décalage** quand le serveur rend
avec LibreOffice alors que le modèle a été conçu sous Word.

Une image **ancrée à la page** (position absolue) se rend, elle, de façon
identique dans les deux moteurs.

Ce module convertit donc, pour **n'importe quel** modèle, toutes les images
flottantes de l'en-tête/pied de page vers un ancrage **page absolu**, en
plaçant chaque image exactement là où **Word** la dessine. La position cible
est apprise par **mesure** (et non codée en dur) : on rend le modèle via Word,
on retire l'image, on diffe les pixels → empreinte visible réelle. Cette
mesure marche pour tout type de dessin (raster, JPEG étiré, WordArt).

Dépendances (présentes uniquement là où l'ingestion tourne, p.ex. un poste /
worker Windows avec Word) : ``docx2pdf`` (Word COM), ``PyMuPDF`` (fitz),
``Pillow``. La normalisation est faite **une fois** à l'enregistrement du
modèle ; le rendu de production des devis reste sur LibreOffice.

Usage programme :
    from app.services.template_normalizer import normalize_letterhead
    fixed_bytes = normalize_letterhead(open('model.docx', 'rb').read())

Usage CLI :
    python -m app.services.template_normalizer entree.docx sortie.docx
"""
from __future__ import annotations

import io
import os
import re
import tempfile
import zipfile
from dataclasses import dataclass

EMU_PER_CM = 360000
_DIFF_THRESHOLD = 30      # delta de luminance considéré « changé »
_ROW_MIN_PIXELS = 4       # pixels changés (échantillonnés) pour retenir une ligne/colonne
_A4_FALLBACK_CM = (21.0, 29.7)

# Parties du document qui portent l'en-tête / le pied de page.
_PART_RE = re.compile(r'word/(header|footer)\d*\.xml$')
_DRAWING_RE = re.compile(r'<w:drawing>.*?</w:drawing>', re.S)
_POS_H_RE = re.compile(r'<wp:positionH relativeFrom="[^"]+">.*?</wp:positionH>', re.S)
_POS_V_RE = re.compile(r'<wp:positionV relativeFrom="[^"]+">.*?</wp:positionV>', re.S)


# ---------------------------------------------------------------------------
# Représentation du .docx en mémoire (chemin -> octets)
# ---------------------------------------------------------------------------

def _load(docx_bytes: bytes) -> dict[str, bytes]:
    with zipfile.ZipFile(io.BytesIO(docx_bytes)) as z:
        return {n: z.read(n) for n in z.namelist()}


def _dump(parts: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as z:
        for name, data in parts.items():
            z.writestr(name, data)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Repérage des images flottantes
# ---------------------------------------------------------------------------

@dataclass
class _Anchor:
    part: str          # ex. 'word/header1.xml'
    index: int         # n-ième dessin flottant dans cette partie
    off_h: int = 0     # offset page horizontal (EMU), rempli pendant la normalisation
    off_v: int = 0     # offset page vertical (EMU)


def _anchored_drawings(xml: str) -> list[str]:
    """Dessins de la partie qui sont des images FLOTTANTES (``wp:anchor``)."""
    return [d for d in _DRAWING_RE.findall(xml) if '<wp:anchor' in d]


def _find_anchors(parts: dict[str, bytes]) -> list[_Anchor]:
    anchors: list[_Anchor] = []
    for name, data in parts.items():
        if not _PART_RE.search(name):
            continue
        xml = data.decode('utf-8')
        for i in range(len(_anchored_drawings(xml))):
            anchors.append(_Anchor(part=name, index=i))
    return anchors


def _map_nth_anchored(xml: str, n: int, transform):
    """Applique ``transform(drawing_xml)`` au n-ième dessin flottant.

    ``transform`` renvoie le nouveau XML du dessin, ou '' pour le supprimer."""
    counter = {'i': 0}

    def repl(m):
        d = m.group(0)
        if '<wp:anchor' not in d:
            return d
        idx = counter['i']
        counter['i'] += 1
        if idx == n:
            return transform(d)
        return d

    return _DRAWING_RE.sub(repl, xml)


def _set_page_anchor(drawing: str, off_h: int, off_v: int) -> str:
    """Force l'ancrage du dessin à la page (positions absolues)."""
    drawing = _POS_H_RE.sub(
        f'<wp:positionH relativeFrom="page"><wp:posOffset>{off_h}</wp:posOffset>'
        f'</wp:positionH>', drawing, count=1)
    drawing = _POS_V_RE.sub(
        f'<wp:positionV relativeFrom="page"><wp:posOffset>{off_v}</wp:posOffset>'
        f'</wp:positionV>', drawing, count=1)
    return drawing


def _variant_remove(parts: dict[str, bytes], a: _Anchor) -> dict[str, bytes]:
    """Copie des parties avec l'image ``a`` retirée (pour le delete-diff)."""
    out = dict(parts)
    xml = out[a.part].decode('utf-8')
    out[a.part] = _map_nth_anchored(xml, a.index, lambda d: '').encode('utf-8')
    return out


def _variant_reanchor(parts: dict[str, bytes], anchors: list[_Anchor]) -> dict[str, bytes]:
    """Copie des parties avec toutes les images ré-ancrées à la page."""
    out = dict(parts)
    by_part: dict[str, list[_Anchor]] = {}
    for a in anchors:
        by_part.setdefault(a.part, []).append(a)
    for part, lst in by_part.items():
        xml = out[part].decode('utf-8')
        for a in lst:
            xml = _map_nth_anchored(
                xml, a.index,
                lambda d, a=a: _set_page_anchor(d, a.off_h, a.off_v))
        out[part] = xml.encode('utf-8')
    return out


# ---------------------------------------------------------------------------
# Rendu (Word) + rasterisation (page 1)
# ---------------------------------------------------------------------------

def _render_page1(parts: dict[str, bytes], dpi: int):
    """Rend le .docx via Word et renvoie (image PIL RGB page 1, largeur_cm, hauteur_cm)."""
    from PIL import Image  # import paresseux (dépendances d'ingestion)
    import fitz

    try:
        import pythoncom
        pythoncom.CoInitialize()
    except Exception:
        pass

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        docx_path = os.path.join(tmp, 'm.docx')
        pdf_path = os.path.join(tmp, 'm.pdf')
        with open(docx_path, 'wb') as fh:
            fh.write(_dump(parts))
        from docx2pdf import convert
        convert(docx_path, pdf_path)
        if not os.path.exists(pdf_path):
            raise RuntimeError('Conversion Word→PDF échouée (Word requis pour la normalisation).')
        # Tout lire en mémoire puis fermer les handles : sinon Windows verrouille
        # le PDF/PNG et le nettoyage du dossier temporaire échoue.
        doc = fitz.open(pdf_path)
        page = doc[0]
        w_cm = page.rect.width / 72 * 2.54
        h_cm = page.rect.height / 72 * 2.54
        png_bytes = page.get_pixmap(dpi=dpi).tobytes('png')
        doc.close()
        img = Image.open(io.BytesIO(png_bytes)).convert('RGB')
        img.load()
        return img, w_cm, h_cm


def _visible_box_cm(full, cut, w_cm: float, h_cm: float):
    """Empreinte visible (top, left, bottom, right en cm) de l'image présente
    dans ``full`` mais absente de ``cut`` (delete-diff)."""
    from PIL import ImageChops
    diff = ImageChops.difference(full, cut).convert('L')
    bw = diff.point(lambda p: 255 if p > _DIFF_THRESHOLD else 0)
    W, H = bw.size
    px = bw.load()
    rows = [y for y in range(H)
            if sum(1 for x in range(0, W, 4) if px[x, y]) >= _ROW_MIN_PIXELS]
    cols = [x for x in range(W)
            if sum(1 for y in range(0, H, 4) if px[x, y]) >= _ROW_MIN_PIXELS]
    if not rows or not cols:
        return None
    return (min(rows) / H * h_cm, min(cols) / W * w_cm,
            max(rows) / H * h_cm, max(cols) / W * w_cm)


# ---------------------------------------------------------------------------
# API publique
# ---------------------------------------------------------------------------

def normalize_letterhead(docx_bytes: bytes, *, dpi: int = 150,
                         verbose: bool = False) -> bytes:
    """Renvoie une copie du modèle où toutes les images flottantes de l'en-tête
    et du pied de page sont ré-ancrées **à la page** (position absolue), placées
    exactement là où Word les dessine.

    Idempotent et sans effet si le modèle ne contient aucune image flottante
    d'en-tête/pied de page : on renvoie alors les octets d'origine.

    Nécessite Microsoft Word (docx2pdf), PyMuPDF et Pillow là où il s'exécute.
    """
    parts = _load(docx_bytes)
    anchors = _find_anchors(parts)
    if not anchors:
        return docx_bytes

    log = (lambda *a: print(*a)) if verbose else (lambda *a: None)

    # 1. Cibles : position visible réelle de chaque image dans le rendu Word.
    full, w_cm, h_cm = _render_page1(parts, dpi)
    targets = []
    for a in anchors:
        box = _visible_box_cm(full, _render_page1(_variant_remove(parts, a), dpi)[0],
                              w_cm, h_cm)
        targets.append(box)
        log(f'  cible {a.part}#{a.index}: {box}')

    # 2. 1ère estimation : ancrage page = position visible cible.
    for a, box in zip(anchors, targets):
        if box is None:
            continue
        a.off_v = round(box[0] * EMU_PER_CM)
        a.off_h = round(box[1] * EMU_PER_CM)
    cand_parts = _variant_reanchor(parts, anchors)
    cand, _, _ = _render_page1(cand_parts, dpi)

    # 3. Correction en une passe (offset↔visible de pente 1 → exact).
    for a, box in zip(anchors, targets):
        if box is None:
            continue
        got = _visible_box_cm(cand, _render_page1(_variant_remove(cand_parts, a), dpi)[0],
                             w_cm, h_cm)
        if got is None:
            continue
        a.off_v += round((box[0] - got[0]) * EMU_PER_CM)
        a.off_h += round((box[1] - got[1]) * EMU_PER_CM)
        log(f'  corrige {a.part}#{a.index}: dv={box[0]-got[0]:+.2f}cm dh={box[1]-got[1]:+.2f}cm')

    return _dump(_variant_reanchor(parts, anchors))


def _main(argv: list[str]) -> int:
    if len(argv) != 2:
        print('usage: python -m app.services.template_normalizer <entree.docx> <sortie.docx>')
        return 2
    src, dst = argv
    data = open(src, 'rb').read()
    out = normalize_letterhead(data, verbose=True)
    with open(dst, 'wb') as fh:
        fh.write(out)
    print('OK ->', dst)
    return 0


if __name__ == '__main__':
    import sys
    raise SystemExit(_main(sys.argv[1:]))
