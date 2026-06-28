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

# « Full-bleed » : un bandeau qui touche un bord de page (à FLUSH_CM près) et
# occupe toute la largeur (ou hauteur) est étendu de BLEED_CM AU-DELÀ du bord.
# Word rogne l'excédent (rendu inchangé), LibreOffice — qui rentre légèrement
# une image posée pile sur le bord — remplit alors jusqu'au bord.
_FLUSH_CM = 0.6
_BLEED_CM = 0.6

# Parties du document qui portent l'en-tête / le pied de page.
_PART_RE = re.compile(r'word/(header|footer)\d*\.xml$')
_DRAWING_RE = re.compile(r'<w:drawing>.*?</w:drawing>', re.S)
_POS_H_RE = re.compile(r'<wp:positionH relativeFrom="[^"]+">.*?</wp:positionH>', re.S)
_POS_V_RE = re.compile(r'<wp:positionV relativeFrom="[^"]+">.*?</wp:positionV>', re.S)
_EXTENT_RE = re.compile(r'<wp:extent cx="\d+" cy="\d+"/>')
_AEXT_RE = re.compile(r'<a:ext cx="\d+" cy="\d+"/>')


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
    cx: int | None = None  # largeur (EMU) à forcer si débordement, sinon inchangée
    cy: int | None = None  # hauteur (EMU) à forcer si débordement, sinon inchangée
    region: str = 'header'  # 'header' ou 'footer' (déduit du nom de partie)
    ext_cy_cm: float = 0.0  # hauteur nominale de l'image (cm), pour fenêtrer la mesure
    ocx: int = 0            # largeur d'origine (EMU)
    ocy: int = 0            # hauteur d'origine (EMU)


def _anchored_drawings(xml: str) -> list[str]:
    """Dessins de la partie qui sont des images FLOTTANTES (``wp:anchor``)."""
    return [d for d in _DRAWING_RE.findall(xml) if '<wp:anchor' in d]


def _find_anchors(parts: dict[str, bytes]) -> list[_Anchor]:
    anchors: list[_Anchor] = []
    for name, data in parts.items():
        m = _PART_RE.search(name)
        if not m:
            continue
        region = m.group(1)  # 'header' ou 'footer'
        xml = data.decode('utf-8')
        for i, d in enumerate(_anchored_drawings(xml)):
            ext = re.search(r'<wp:extent cx="(\d+)" cy="(\d+)"', d)
            ocx = int(ext.group(1)) if ext else 0
            ocy = int(ext.group(2)) if ext else 0
            anchors.append(_Anchor(part=name, index=i, region=region,
                                   ext_cy_cm=ocy / EMU_PER_CM, ocx=ocx, ocy=ocy))
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


def _set_page_anchor(drawing: str, off_h: int, off_v: int,
                     cx: int | None = None, cy: int | None = None) -> str:
    """Force l'ancrage du dessin à la page (positions absolues).

    Si ``cx``/``cy`` sont fournis, redimensionne aussi le cadre (``wp:extent``)
    et l'image (``a:ext``) — utilisé pour faire déborder un bandeau full-bleed."""
    drawing = _POS_H_RE.sub(
        f'<wp:positionH relativeFrom="page"><wp:posOffset>{off_h}</wp:posOffset>'
        f'</wp:positionH>', drawing, count=1)
    drawing = _POS_V_RE.sub(
        f'<wp:positionV relativeFrom="page"><wp:posOffset>{off_v}</wp:posOffset>'
        f'</wp:positionV>', drawing, count=1)
    if cx is not None and cy is not None:
        drawing = _EXTENT_RE.sub(f'<wp:extent cx="{cx}" cy="{cy}"/>', drawing, count=1)
        drawing = _AEXT_RE.sub(f'<a:ext cx="{cx}" cy="{cy}"/>', drawing, count=1)
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
                lambda d, a=a: _set_page_anchor(d, a.off_h, a.off_v, a.cx, a.cy))
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


def _visible_box_cm(full, cut, w_cm: float, h_cm: float,
                    y_lo_cm: float = 0.0, y_hi_cm: float | None = None):
    """Empreinte visible (top, left, bottom, right en cm) de l'image présente
    dans ``full`` mais absente de ``cut`` (delete-diff).

    La mesure est restreinte à la bande verticale [y_lo_cm, y_hi_cm] : retirer
    une image d'en-tête/pied peut faire refluer le corps, et cette fenêtre
    évite de capturer ce reflux (sinon la « hauteur » mesurée explose)."""
    from PIL import ImageChops
    diff = ImageChops.difference(full, cut).convert('L')
    bw = diff.point(lambda p: 255 if p > _DIFF_THRESHOLD else 0)
    W, H = bw.size
    px = bw.load()
    y0 = max(0, int(y_lo_cm / h_cm * H))
    y1 = min(H, int((y_hi_cm if y_hi_cm is not None else h_cm) / h_cm * H))
    rows = [y for y in range(y0, y1)
            if sum(1 for x in range(0, W, 4) if px[x, y]) >= _ROW_MIN_PIXELS]
    cols = [x for x in range(W)
            if sum(1 for y in range(y0, y1, 4) if px[x, y]) >= _ROW_MIN_PIXELS]
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

    def window(a: _Anchor):
        pad = a.ext_cy_cm + 1.5  # marge autour de la hauteur nominale de l'image
        if a.region == 'footer':
            return (h_cm - pad, h_cm)
        return (0.0, pad)

    targets = []
    for a in anchors:
        lo, hi = window(a)
        box = _visible_box_cm(full, _render_page1(_variant_remove(parts, a), dpi)[0],
                              w_cm, h_cm, lo, hi)
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
        lo, hi = window(a)
        got = _visible_box_cm(cand, _render_page1(_variant_remove(cand_parts, a), dpi)[0],
                             w_cm, h_cm, lo, hi)
        if got is None:
            continue
        a.off_v += round((box[0] - got[0]) * EMU_PER_CM)
        a.off_h += round((box[1] - got[1]) * EMU_PER_CM)
        log(f'  corrige {a.part}#{a.index}: dv={box[0]-got[0]:+.2f}cm dh={box[1]-got[1]:+.2f}cm')

    # 4. Full-bleed des bandeaux pleine largeur — SANS jamais étirer la hauteur
    #    (le texte intégré au bandeau serait déformé). Le débordement vient :
    #    - horizontalement : on CENTRE le bandeau déjà plus large que la page
    #      (ex. 26 cm sur 21) ou, s'il n'est pas assez large, on l'élargit ;
    #    - verticalement : si collé en haut, on le REMONTE d'un poil (décalage,
    #      pas d'étirement). La hauteur d'origine est toujours préservée.
    page_w_emu = round(w_cm * EMU_PER_CM)
    min_full_w = round((w_cm + 2 * _BLEED_CM) * EMU_PER_CM)
    for a, box in zip(anchors, targets):
        if box is None:
            continue
        top, left, _bottom, right = box
        full_width = (left <= _FLUSH_CM) and (right >= w_cm - _FLUSH_CM)
        if not full_width:
            continue  # bandeau inséré par design / logo : on ne déborde pas
        a.cx = max(a.ocx, min_full_w)          # élargir seulement si nécessaire
        a.cy = a.ocy                            # hauteur d'origine, jamais étirée
        a.off_h = round((page_w_emu - a.cx) / 2)  # centré → déborde des 2 côtés
        if a.region == 'header' and top <= _FLUSH_CM:
            a.off_v = round((top - _BLEED_CM) * EMU_PER_CM)  # remonter sans étirer
        log(f'  bleed {a.part}#{a.index}: largeur {a.cx/EMU_PER_CM:.1f}cm centrée, '
            f'off_h={a.off_h/EMU_PER_CM:.2f}cm')

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
