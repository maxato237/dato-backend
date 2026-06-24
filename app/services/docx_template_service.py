"""Génération d'un devis DATO à partir d'un template Word (.docx).

Deux familles de templates sont gérées (cf. ``render_quote_docx``) :

A. Template avec **tableau** dont la 1re ligne contient « Désignation » :
   on conserve l'en-tête du tableau et on remplace ses lignes de données.

B. Template **papèterie** (en-tête/pied de page Word seuls, corps vide,
   ex. « MILLENAIRE DECOR ») : on **construit tout le corps** du devis
   (titre, client, tableau, total en lettres, signatures) dans le corps,
   pendant que Word conserve l'en-tête et le pied de page sur chaque page.

Conversion finale en PDF via docx2pdf (Word COM, Windows/Mac) ou LibreOffice.

Dépendances :
    pip install python-docx docx2pdf
"""
from __future__ import annotations

import io
import os
import subprocess
import tempfile

from docx import Document  # type: ignore[import-untyped]
from docx.enum.table import WD_CELL_VERTICAL_ALIGNMENT  # type: ignore[import-untyped]
from docx.enum.text import WD_ALIGN_PARAGRAPH  # type: ignore[import-untyped]
from docx.oxml import OxmlElement  # type: ignore[import-untyped]
from docx.oxml.ns import qn  # type: ignore[import-untyped]
from docx.shared import Pt, RGBColor  # type: ignore[import-untyped]

from app.models.quote import Quote


# Mots-clés qui signalent la colonne « Désignation » dans la première ligne.
_HEADER_KEYWORDS = {
    'désignation', 'designation',
    'libellé', 'libelle',
    'description', 'article',
    'nature', 'objet',
}


# ---------------------------------------------------------------------------
# Localisation du tableau principal
# ---------------------------------------------------------------------------

def _find_items_table(doc: Document):
    """Retourne le tableau du devis dans le template, ou None."""
    for table in doc.tables:
        if not table.rows:
            continue
        first_row_text = ' '.join(
            c.text.strip().lower() for c in table.rows[0].cells
        )
        if any(kw in first_row_text for kw in _HEADER_KEYWORDS):
            return table

    # Fallback : tableau avec le plus grand nombre de colonnes (≥ 3).
    candidates = [t for t in doc.tables if len(t.columns) >= 3]
    if candidates:
        return max(candidates, key=lambda t: len(t.columns))
    return None


# ---------------------------------------------------------------------------
# Manipulation des lignes
# ---------------------------------------------------------------------------

def _delete_data_rows(table) -> None:
    """Supprime toutes les lignes du tableau sauf la première (en-tête)."""
    tbl_xml = table._tbl
    for row in list(table.rows)[1:]:
        tbl_xml.remove(row._tr)


def _set_cell_text(cell, text: str, bold: bool = False, align=None,
                   size: float | None = None, color: str | None = None) -> None:
    """Écrit `text` dans la cellule en réutilisant le style du premier run."""
    for para in cell.paragraphs:
        for run in para.runs:
            run.text = ''

    para = cell.paragraphs[0]
    if para.runs:
        run = para.runs[0]
    else:
        run = para.add_run()

    run.text = text
    if bold:
        run.bold = True
    elif run.bold:
        run.bold = False  # forcer non-gras si hérité
    if size is not None:
        run.font.size = Pt(size)
    if color is not None:
        run.font.color.rgb = RGBColor.from_string(color)
    if align is not None:
        para.alignment = align

    # Texte centré verticalement dans la hauteur de la cellule.
    cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER


def _add_row(table, cells_data: list[str], bold: bool = False):
    """Ajoute une ligne avec les textes fournis."""
    row = table.add_row()
    for i, value in enumerate(cells_data):
        if i < len(row.cells):
            _set_cell_text(row.cells[i], value, bold=bold)
    return row


def _shade_cell(cell, fill_hex: str) -> None:
    """Applique une couleur de fond à une cellule (ex. 'E7EEF3')."""
    tcPr = cell._tc.get_or_add_tcPr()
    shd = OxmlElement('w:shd')
    shd.set(qn('w:val'), 'clear')
    shd.set(qn('w:color'), 'auto')
    shd.set(qn('w:fill'), fill_hex)
    tcPr.append(shd)


def _add_table_borders(table, color: str = 'C9D2DC', sz: str = '4') -> None:
    """Ajoute des bordures fines (grille complète) à un tableau."""
    tblPr = table._tbl.tblPr
    borders = OxmlElement('w:tblBorders')
    for edge in ('top', 'left', 'bottom', 'right', 'insideH', 'insideV'):
        el = OxmlElement(f'w:{edge}')
        el.set(qn('w:val'), 'single')
        el.set(qn('w:sz'), sz)
        el.set(qn('w:space'), '0')
        el.set(qn('w:color'), color)
        borders.append(el)
    tblPr.append(borders)


# ---------------------------------------------------------------------------
# Politique de pagination
# ---------------------------------------------------------------------------

def _row_cant_split(row) -> None:
    """Empêche la ligne de se couper en travers d'une page."""
    trPr = row._tr.get_or_add_trPr()
    trPr.append(OxmlElement('w:cantSplit'))


def _row_repeat_as_header(row) -> None:
    """La ligne se répète en haut de chaque page (en-tête de tableau)."""
    trPr = row._tr.get_or_add_trPr()
    trPr.append(OxmlElement('w:tblHeader'))


def _keep_with_next(cell) -> None:
    """Garde le contenu de la cellule collé à la ligne/au paragraphe suivant."""
    for para in cell.paragraphs:
        para.paragraph_format.keep_with_next = True


# ---------------------------------------------------------------------------
# Formatage
# ---------------------------------------------------------------------------

def _fmt(amount) -> str:
    """Formate un montant : 1 025 500 (séparateur milliers = espace)."""
    try:
        return f'{float(amount):,.0f}'.replace(',', ' ')  # espace fine
    except (TypeError, ValueError):
        return str(amount)


# ---------------------------------------------------------------------------
# API publique
# ---------------------------------------------------------------------------

def fill_quote_template(template_bytes: bytes, quote: Quote) -> bytes:
    """Remplit le template DOCX avec les données du devis.

    L'en-tête et le pied de page Word (styles natifs) sont préservés intacts.
    Seul le contenu du tableau principal est remplacé.

    Args:
        template_bytes: Contenu binaire du fichier .docx template.
        quote: Instance Quote SQLAlchemy chargée avec ses items et company.

    Returns:
        Contenu binaire du .docx rempli.

    Raises:
        ValueError: Si aucun tableau de devis n'est trouvé dans le template.
    """
    doc = Document(io.BytesIO(template_bytes))

    table = _find_items_table(doc)
    if table is None:
        raise ValueError(
            "Aucun tableau de devis trouvé dans le template. "
            "Le tableau doit contenir une colonne « Désignation » ou « Description »."
        )

    num_cols = len(table.columns)

    # ── 1. Vider les lignes de données ───────────────────────────────────────
    _delete_data_rows(table)

    # ── 2. Lignes d'articles ─────────────────────────────────────────────────
    for item in quote.items:
        desc = item.description or ''
        if item.unit:
            desc += f' ({item.unit})'

        cells = [''] * num_cols
        if num_cols >= 4:
            cells[0] = desc
            cells[1] = f'{float(item.quantity):g}'
            cells[2] = _fmt(item.unit_price)
            cells[3] = _fmt(item.total)
        elif num_cols == 3:
            cells[0] = desc
            cells[1] = f'{float(item.quantity):g}'
            cells[2] = _fmt(item.total)
        else:
            cells[0] = desc

        _add_row(table, cells)

    # ── 3. Sous-total ─────────────────────────────────────────────────────────
    if num_cols >= 2:
        sub = [''] * num_cols
        sub[0] = 'Sous-total'
        sub[-1] = _fmt(quote.subtotal)
        _add_row(table, sub, bold=True)

    # ── 4. TVA ────────────────────────────────────────────────────────────────
    if float(quote.tax_rate) > 0:
        tva = [''] * num_cols
        tva[0] = f'TVA ({float(quote.tax_rate):.0f} %)'
        tva[-1] = _fmt(quote.tax_amount)
        _add_row(table, tva, bold=True)

    # ── 5. Total général ─────────────────────────────────────────────────────
    tot = [''] * num_cols
    tot[0] = 'Total général'
    tot[-1] = _fmt(quote.total)
    _add_row(table, tot, bold=True)

    # ── 6. Sauvegarder ───────────────────────────────────────────────────────
    output = io.BytesIO()
    doc.save(output)
    return output.getvalue()


def _map_row_cells(kind: str, row: dict, num_cols: int) -> list[str]:
    """Mappe une ligne sémantique vers les cellules du tableau du template.

    Le template peut avoir 2, 3 ou 4+ colonnes ; l'app ne connaît pas cette
    structure, donc elle envoie des lignes sémantiques (« line » ou « span »)
    et c'est ici qu'on les place dans les bonnes colonnes.

    - kind == 'line' : article normal → Désignation / Qté / P.U / P.T
    - kind == 'span' : ligne de total/section → libellé (col 0) + montant (col -1)
    """
    cells = [''] * max(num_cols, 1)
    if kind == 'line':
        desig = str(row.get('designation', ''))
        qty = str(row.get('qty', ''))
        pu = str(row.get('pu', ''))
        pt = str(row.get('pt', ''))
        if num_cols >= 4:
            cells[0], cells[1], cells[2], cells[3] = desig, qty, pu, pt
        elif num_cols == 3:
            cells[0], cells[1], cells[2] = desig, qty, pt
        elif num_cols == 2:
            cells[0], cells[1] = desig, pt
        else:
            cells[0] = desig
    else:  # 'span' / 'section' : libellé + montant
        label = str(row.get('label', ''))
        amount = str(row.get('amount', ''))
        cells[0] = label
        if amount and num_cols >= 2:
            cells[-1] = amount
    return cells


def fill_template_rows(template_bytes: bytes, rows: list[dict]) -> bytes:
    """Remplit le tableau du template avec des lignes déjà formatées par l'app.

    L'en-tête et le pied de page Word sont préservés intacts ; seules les
    lignes de données du tableau principal sont remplacées.

    Args:
        template_bytes: contenu binaire du .docx template.
        rows: liste de lignes sémantiques. Chaque ligne est un dict :
              {'kind': 'line', 'designation', 'qty', 'pu', 'pt'} ou
              {'kind': 'span', 'label', 'amount', 'bold': bool}.

    Returns:
        Contenu binaire du .docx rempli.

    Raises:
        ValueError: si aucun tableau de devis n'est trouvé dans le template.
    """
    doc = Document(io.BytesIO(template_bytes))

    table = _find_items_table(doc)
    if table is None:
        raise ValueError(
            "Aucun tableau de devis trouvé dans le template. "
            "Le tableau doit contenir une colonne « Désignation » ou « Description »."
        )

    _fill_existing_table(table, rows)

    output = io.BytesIO()
    doc.save(output)
    return output.getvalue()


def _fill_existing_table(table, rows: list[dict]) -> None:
    """Remplace les lignes de données d'un tableau existant par `rows`."""
    num_cols = len(table.columns)
    _delete_data_rows(table)
    # En-tête conservée : répétée sur chaque page + non sécable.
    if table.rows:
        _row_cant_split(table.rows[0])
        _row_repeat_as_header(table.rows[0])
    for row in rows:
        kind = str(row.get('kind', 'line'))
        bold = bool(row.get('bold', False))
        cells = _map_row_cells(kind, row, num_cols)
        new_row = _add_row(table, cells, bold=bold)
        _row_cant_split(new_row)


# ---------------------------------------------------------------------------
# Construction complète du corps (template « papèterie », corps vide)
# ---------------------------------------------------------------------------

_BLUE = '1B4965'
_HEAD_BG = 'E7EEF3'
_SPAN_BG = 'EEF3EE'


def _build_items_table(doc, rows: list[dict]) -> None:
    """Construit le tableau Désignation / Qté / P.U / P.T depuis zéro."""
    table = doc.add_table(rows=1, cols=4)
    _add_table_borders(table)

    headers = ['Désignation', 'Qté', 'P.U', 'P.T']
    aligns = [WD_ALIGN_PARAGRAPH.LEFT, WD_ALIGN_PARAGRAPH.CENTER,
              WD_ALIGN_PARAGRAPH.CENTER, WD_ALIGN_PARAGRAPH.CENTER]
    for i, head in enumerate(headers):
        cell = table.rows[0].cells[i]
        _set_cell_text(cell, head, bold=True, align=aligns[i], size=10)
        _shade_cell(cell, _HEAD_BG)
    # En-tête répétée en haut de chaque page + non sécable.
    _row_cant_split(table.rows[0])
    _row_repeat_as_header(table.rows[0])

    for row in rows:
        kind = str(row.get('kind', 'line'))
        bold = bool(row.get('bold', False))
        strong = bool(row.get('strong', False))  # ligne mise en avant (total général)
        new_row = table.add_row()
        cells = new_row.cells
        _row_cant_split(new_row)  # jamais couper une ligne en travers d'une page
        if kind == 'line':
            _set_cell_text(cells[0], str(row.get('designation', '')), size=10)
            _set_cell_text(cells[1], str(row.get('qty', '')),
                           align=WD_ALIGN_PARAGRAPH.CENTER, size=10)
            _set_cell_text(cells[2], str(row.get('pu', '')),
                           align=WD_ALIGN_PARAGRAPH.RIGHT, size=10)
            _set_cell_text(cells[3], str(row.get('pt', '')),
                           align=WD_ALIGN_PARAGRAPH.RIGHT, size=10)
        else:  # span : libellé fusionné sur 3 colonnes + montant
            label_cell = cells[0].merge(cells[1]).merge(cells[2])
            if strong:
                # Total général : fond bleu foncé, texte blanc, plus grand.
                _set_cell_text(label_cell, str(row.get('label', '')),
                               bold=True, size=11, color='FFFFFF')
                _set_cell_text(cells[3], str(row.get('amount', '')),
                               bold=True, align=WD_ALIGN_PARAGRAPH.RIGHT,
                               size=11, color='FFFFFF')
                _shade_cell(label_cell, _BLUE)
                _shade_cell(cells[3], _BLUE)
            else:
                _set_cell_text(label_cell, str(row.get('label', '')),
                               bold=True, size=10)
                _set_cell_text(cells[3], str(row.get('amount', '')),
                               bold=True, align=WD_ALIGN_PARAGRAPH.RIGHT, size=10)
                if bold:
                    _shade_cell(label_cell, _SPAN_BG)
                    _shade_cell(cells[3], _SPAN_BG)
                # En-tête de section (span sans montant) : reste collée à sa
                # 1re ligne (pas de titre orphelin en bas de page).
                if not str(row.get('amount', '')).strip():
                    _keep_with_next(label_cell)


def _build_quote_body(doc, data: dict) -> None:
    """Construit tout le corps du devis dans un template papèterie (corps vide).

    Reproduit la mise en page du rendu par défaut de l'app : ligne de date,
    titre, « DOIT : client », tableau, total en lettres, NB, signatures.
    """
    # Ligne ville + date (alignée à droite).
    city_date = str(data.get('cityDate', '')).strip()
    if city_date:
        p = doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.RIGHT
        p.paragraph_format.space_before = Pt(6)
        p.paragraph_format.space_after = Pt(18)
        p.add_run(city_date)

    # Titre centré, gras, souligné.
    title = str(data.get('title', '')).strip()
    if title:
        p = doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        p.paragraph_format.space_after = Pt(16)
        run = p.add_run(title)
        run.bold = True
        run.underline = True
        run.font.size = Pt(13)

    # « DOIT : {client} ».
    client = str(data.get('client', '')).strip()
    if client:
        p = doc.add_paragraph()
        p.paragraph_format.space_after = Pt(12)
        r1 = p.add_run('DOIT : ')
        r1.bold = True
        r1.underline = True
        r2 = p.add_run(client)
        r2.bold = True

    # Tableau des articles.
    _build_items_table(doc, data.get('rows', []))

    # Bloc de conclusion (Arrêté… + NB + signatures) soudé : il bascule en
    # entier sur la page suivante plutôt que de laisser les signatures seules.
    # « Arrêté le présent devis à la somme de … ».
    words = str(data.get('amountInWords', '')).strip()
    if words:
        p = doc.add_paragraph()
        p.paragraph_format.space_before = Pt(16)
        p.paragraph_format.space_after = Pt(6)
        p.paragraph_format.keep_with_next = True
        r1 = p.add_run('Arrêté le présent devis à la somme de ')
        r1.italic = True
        r2 = p.add_run(words + '.')
        r2.italic = True
        r2.bold = True

    # NB / note.
    note = str(data.get('note', '')).strip()
    if note:
        p = doc.add_paragraph()
        p.paragraph_format.space_after = Pt(6)
        p.paragraph_format.keep_with_next = True
        r1 = p.add_run('NB : ')
        r1.bold = True
        p.add_run(note)

    # Signatures (une colonne par signataire).
    sigs = [str(s) for s in (data.get('signatures') or []) if str(s).strip()]
    if sigs:
        spacer = doc.add_paragraph()
        spacer.paragraph_format.space_before = Pt(18)
        spacer.paragraph_format.keep_with_next = True
        st = doc.add_table(rows=1, cols=len(sigs))
        _row_cant_split(st.rows[0])  # les colonnes de signature restent ensemble
        for i, label in enumerate(sigs):
            cell = st.rows[0].cells[i]
            _set_cell_text(cell, label, bold=True,
                           align=WD_ALIGN_PARAGRAPH.CENTER)
            # Un seul espace de signature (gap modéré entre le libellé et
            # le mot « Signature »).
            gap = cell.add_paragraph()
            gap.paragraph_format.space_before = Pt(20)
            sp = cell.add_paragraph('Signature')
            sp.alignment = WD_ALIGN_PARAGRAPH.CENTER


def render_quote_docx(template_bytes: bytes, data: dict) -> bytes:
    """Produit le .docx final du devis à partir du template et des données app.

    - Si le template contient un tableau « Désignation » → on le remplit.
    - Sinon (papèterie : en-tête/pied seuls) → on construit tout le corps.

    `data` : {'rows', 'cityDate', 'title', 'client', 'amountInWords',
              'note', 'signatures', 'number'}.
    """
    doc = Document(io.BytesIO(template_bytes))

    table = _find_items_table(doc)
    if table is not None:
        _fill_existing_table(table, data.get('rows', []))
    else:
        _build_quote_body(doc, data)

    output = io.BytesIO()
    doc.save(output)
    return output.getvalue()


def docx_to_pdf(docx_bytes: bytes) -> bytes:
    """Convertit un .docx en PDF.

    Essaie dans l'ordre :
      1. ``docx2pdf`` (Windows/Mac avec Microsoft Word installé)
      2. LibreOffice headless (Linux ou si Word absent)

    Returns:
        Contenu binaire du PDF généré.

    Raises:
        RuntimeError: Si aucun convertisseur n'est disponible.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        docx_path = os.path.join(tmpdir, 'quote.docx')
        pdf_path  = os.path.join(tmpdir, 'quote.pdf')

        with open(docx_path, 'wb') as fh:
            fh.write(docx_bytes)

        # ── Tentative 1 : docx2pdf (Word COM / AppleScript) ──────────────────
        # Word COM doit être initialisé dans le thread courant (Flask sert
        # chaque requête dans un thread worker → sinon « CoInitialize has not
        # been called »).
        _com_ready = False
        try:
            import pythoncom  # type: ignore[import-untyped]
            pythoncom.CoInitialize()
            _com_ready = True
        except Exception:
            pass
        try:
            from docx2pdf import convert  # type: ignore[import-untyped]
            convert(docx_path, pdf_path)
            if os.path.exists(pdf_path):
                with open(pdf_path, 'rb') as fh:
                    return fh.read()
        except Exception:
            pass
        finally:
            if _com_ready:
                try:
                    pythoncom.CoUninitialize()
                except Exception:
                    pass

        # ── Tentative 2 : LibreOffice headless ───────────────────────────────
        _SOFFICE_CANDIDATES = [
            'soffice', 'libreoffice',
            '/usr/bin/soffice', '/usr/bin/libreoffice',
            '/usr/local/bin/soffice',
        ]
        for soffice in _SOFFICE_CANDIDATES:
            try:
                subprocess.run(
                    [soffice, '--headless', '--convert-to', 'pdf',
                     '--outdir', tmpdir, docx_path],
                    capture_output=True,
                    timeout=60,
                    check=True,
                )
                if os.path.exists(pdf_path):
                    with open(pdf_path, 'rb') as fh:
                        return fh.read()
            except (FileNotFoundError, subprocess.CalledProcessError,
                    subprocess.TimeoutExpired):
                continue

        raise RuntimeError(
            "Impossible de convertir le DOCX en PDF. "
            "Installez Microsoft Word (Windows/Mac) ou LibreOffice, "
            "puis relancez le backend."
        )
