"""Génération PDF des devis DATO avec ReportLab."""
import io
import os
from datetime import date, timedelta

import requests
from flask import current_app
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable,
    Image as RLImage,
)
from reportlab.lib.enums import TA_LEFT, TA_RIGHT, TA_CENTER

from reportlab.platypus import Flowable

from app.models.quote import Quote


class _BackgroundCard(Flowable):
    """Flowable ReportLab : image de fond + voile semi-transparent + table de contenu.

    Le contenu (inner_table) détermine la hauteur du bloc.
    L'image remplit toute la surface (preserveAspectRatio=False → rognage côté PDF).
    """
    _PAD_H = 10  # padding horizontal interne (pts)
    _PAD_V = 8   # padding vertical interne (pts)

    def __init__(self, inner_table, bg_data: bytes, overlay_alpha: float = 0.48):
        Flowable.__init__(self)
        self._table = inner_table
        self._bg = bg_data
        self._alpha = overlay_alpha
        self._w = self._h = self._table_h = 0

    def wrap(self, avail_w, avail_h):
        self._w = avail_w
        inner_w = avail_w - 2 * self._PAD_H
        _, self._table_h = self._table.wrap(inner_w, avail_h)
        self._h = self._table_h + 2 * self._PAD_V
        return self._w, self._h

    def draw(self):
        c = self.canv
        w, h = self._w, self._h

        # Image de fond : remplit toute la surface (sans déformation).
        c.drawImage(
            ImageReader(io.BytesIO(self._bg)),
            0, 0, w, h,
            preserveAspectRatio=False,
            mask='auto',
        )
        # Voile sombre pour la lisibilité du texte blanc.
        if self._alpha > 0:
            c.setFillColor(colors.Color(0, 0, 0, alpha=self._alpha))
            c.rect(0, 0, w, h, fill=1, stroke=0)

        # Table par-dessus : dans le repère ReportLab (y=0 en bas),
        # le haut de la table est à h - PAD_V depuis le bas du bloc.
        self._table.drawOn(c, self._PAD_H, h - self._PAD_V)


def _load_image_bytes(url):
    """Retourne les octets d'une image (locale ou distante) ou None.

    - URL Supabase / http(s) : récupération via HTTP.
    - URL locale (.../uploads/<f>) servie par ce backend : lecture directe sur
      disque (plus rapide, pas d'appel réseau).
    Échec silencieux (réseau, 404…) → None, le PDF se construit sans l'image.
    """
    if not url:
        return None

    marker = '/uploads/'
    if marker in url:
        filename = url.split(marker, 1)[1].split('?')[0]
        path = os.path.join(current_app.config['UPLOAD_FOLDER'], filename)
        if os.path.exists(path):
            with open(path, 'rb') as fh:
                return fh.read()

    if url.startswith('http://') or url.startswith('https://'):
        try:
            resp = requests.get(url, timeout=15)
            if resp.status_code == 200:
                return resp.content
        except requests.RequestException:
            return None
    return None


def _fitted_image(data, max_w, max_h):
    """RLImage redimensionnée pour tenir dans (max_w, max_h) sans déformation."""
    if not data:
        return None
    iw, ih = ImageReader(io.BytesIO(data)).getSize()
    if iw <= 0 or ih <= 0:
        return None
    ratio = min(max_w / iw, max_h / ih)
    return RLImage(io.BytesIO(data), width=iw * ratio, height=ih * ratio)

# Palette DATO
_INK = colors.HexColor('#1B3A4B')
_ACCENT = colors.HexColor('#1B4965')
_LIGHT = colors.HexColor('#F5F7FA')
_MUTED = colors.HexColor('#6B7280')
_BORDER = colors.HexColor('#D1D5DB')
_WHITE = colors.white
_GREEN = colors.HexColor('#16A34A')
_RED = colors.HexColor('#DC2626')
_ORANGE = colors.HexColor('#D97706')

_STATUS_COLORS = {
    'draft': _MUTED,
    'sent': _ORANGE,
    'accepted': _GREEN,
    'rejected': _RED,
}
_STATUS_LABELS = {
    'draft': 'Brouillon',
    'sent': 'Envoyé',
    'accepted': 'Accepté',
    'rejected': 'Refusé',
}

PAGE_W, PAGE_H = A4
MARGIN = 20 * mm


def generate_quote_pdf(quote: Quote) -> bytes:
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=MARGIN,
        rightMargin=MARGIN,
        topMargin=MARGIN,
        bottomMargin=MARGIN,
    )

    styles = getSampleStyleSheet()
    story = []

    _add_header(story, quote, styles)  # l'image d'en-tête est maintenant le fond du cadre
    story.append(Spacer(1, 6 * mm))
    _add_parties(story, quote, styles)
    story.append(Spacer(1, 6 * mm))
    _add_items_table(story, quote, styles)
    story.append(Spacer(1, 6 * mm))
    _add_totals(story, quote, styles)
    if quote.notes:
        story.append(Spacer(1, 6 * mm))
        _add_notes(story, quote, styles)
    sigs = list(quote.company.signatures)
    if sigs:
        story.append(Spacer(1, 10 * mm))
        _add_signatures(story, sigs, styles)
    _add_footer(story, quote, styles)

    doc.build(story)
    return buffer.getvalue()


def _style(name, **kw):
    s = ParagraphStyle(name, **kw)
    return s


def _add_header(story, quote: Quote, styles):
    company = quote.company
    status_color = _STATUS_COLORS.get(quote.status, _MUTED)
    status_label = _STATUS_LABELS.get(quote.status, quote.status)

    # Image de fond du cadre entreprise (optionnelle).
    header_bg = _load_image_bytes(getattr(company, 'header_image_url', None))
    has_bg = header_bg is not None

    # Couleurs adaptatives : blanc sur fond image, sombres sans fond.
    txt_name  = _WHITE if has_bg else _INK
    txt_sub   = colors.Color(1, 1, 1, alpha=0.88) if has_bg else _MUTED
    txt_quote = _WHITE if has_bg else _ACCENT
    txt_num   = colors.Color(1, 1, 1, alpha=0.78) if has_bg else _MUTED
    txt_st    = _WHITE if has_bg else _MUTED

    name_style  = _style('CompanyName', fontSize=18, fontName='Helvetica-Bold', textColor=txt_name)
    act_style   = _style('Activity', fontSize=9, textColor=txt_sub)
    title_style = _style('QuoteTitle', fontSize=14, fontName='Helvetica-Bold', textColor=txt_quote, alignment=TA_RIGHT)
    num_style   = _style('QuoteNum', fontSize=9, textColor=txt_num, alignment=TA_RIGHT)

    # Logo : affiché uniquement s'il a été uploadé.
    left_col = []
    logo_data = _load_image_bytes(getattr(company, 'logo_url', None))
    if logo_data:
        logo = _fitted_image(logo_data, 28 * mm, 18 * mm)
        if logo is not None:
            logo.hAlign = 'LEFT'
            left_col.append(logo)
            left_col.append(Spacer(1, 3 * mm))

    left_col += [
        Paragraph(company.name, name_style),
        Paragraph(company.activity or '', act_style),
        Paragraph(', '.join(company.phones or []), act_style),
        Paragraph(' — '.join(p for p in [company.address, company.city] if p), act_style),
    ]
    right_col = [
        Paragraph(
            f'<font color="#{_hex(status_color)}">● {status_label}</font>',
            _style('s', fontSize=9, alignment=TA_RIGHT, textColor=txt_st),
        ),
        Spacer(1, 2 * mm),
        Paragraph('DEVIS', title_style),
        Paragraph(quote.number, num_style),
        Paragraph(f'Émis le {date.today().strftime("%d/%m/%Y")}', num_style),
        Paragraph(f'Valide {quote.validity_days} jours', num_style),
    ]

    content_w = PAGE_W - 2 * MARGIN
    inner = Table(
        [[left_col, right_col]],
        colWidths=[content_w * 0.55, content_w * 0.45],
    )
    inner.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('ALIGN', (1, 0), (1, 0), 'RIGHT'),
    ]))

    if has_bg:
        # Image rognée = fond du cadre, texte blanc par-dessus.
        story.append(_BackgroundCard(inner, bg_data=header_bg, overlay_alpha=0.50))
    else:
        story.append(inner)

    story.append(HRFlowable(width='100%', thickness=1, color=_BORDER, spaceAfter=0))


def _add_parties(story, quote: Quote, styles):
    label_style = _style('Label', fontSize=8, fontName='Helvetica-Bold', textColor=_MUTED)
    value_style = _style('Value', fontSize=10, fontName='Helvetica-Bold', textColor=_INK)
    sub_style = _style('Sub', fontSize=9, textColor=_MUTED)

    client = quote.client
    client_lines = [Paragraph('CLIENT', label_style)]
    if client:
        client_lines.append(Paragraph(client.name, value_style))
        if client.phone:
            client_lines.append(Paragraph(client.phone, sub_style))
        if client.email:
            client_lines.append(Paragraph(client.email, sub_style))
        if client.address:
            client_lines.append(Paragraph(client.address, sub_style))
    else:
        client_lines.append(Paragraph('—', value_style))

    expiry = date.today() + timedelta(days=quote.validity_days)
    meta_lines = [
        Paragraph('DÉTAILS', label_style),
        Paragraph(f'N° {quote.number}', value_style),
        Paragraph(f'Titre : {quote.title}', sub_style),
        Paragraph(f'Expire le {expiry.strftime("%d/%m/%Y")}', sub_style),
        Paragraph(f'Devise : {quote.company.currency}', sub_style),
    ]

    t = Table([[client_lines, meta_lines]], colWidths=[(PAGE_W - 2 * MARGIN) * 0.6, (PAGE_W - 2 * MARGIN) * 0.4])
    t.setStyle(TableStyle([('VALIGN', (0, 0), (-1, -1), 'TOP')]))
    story.append(t)


def _add_items_table(story, quote: Quote, styles):
    header_style = _style('TH', fontSize=8, fontName='Helvetica-Bold', textColor=_WHITE)
    cell_style = _style('TD', fontSize=9, textColor=_INK)
    num_style = _style('TDR', fontSize=9, textColor=_INK, alignment=TA_RIGHT)
    currency = quote.company.currency

    headers = ['Description', 'Qté', 'Prix unitaire', f'Total ({currency})']
    rows = [headers]
    for item in quote.items:
        rows.append([
            item.description + (f'\n({item.unit})' if item.unit else ''),
            f'{item.quantity:g}',
            f'{item.unit_price:,.0f}',
            f'{item.total:,.0f}',
        ])

    col_w = PAGE_W - 2 * MARGIN
    table = Table(rows, colWidths=[col_w * 0.5, col_w * 0.1, col_w * 0.2, col_w * 0.2], repeatRows=1)
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), _ACCENT),
        ('TEXTCOLOR', (0, 0), (-1, 0), _WHITE),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 8),
        ('ALIGN', (1, 0), (-1, -1), 'RIGHT'),
        ('ALIGN', (0, 0), (0, -1), 'LEFT'),
        ('FONTSIZE', (0, 1), (-1, -1), 9),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [_WHITE, _LIGHT]),
        ('GRID', (0, 0), (-1, -1), 0.5, _BORDER),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ('LEFTPADDING', (0, 0), (-1, -1), 6),
        ('RIGHTPADDING', (0, 0), (-1, -1), 6),
    ]))
    story.append(table)


def _add_totals(story, quote: Quote, styles):
    currency = quote.company.currency
    label_style = _style('TotalLabel', fontSize=9, textColor=_MUTED, alignment=TA_RIGHT)
    value_style = _style('TotalValue', fontSize=9, textColor=_INK, alignment=TA_RIGHT)
    total_label_style = _style('GrandLabel', fontSize=11, fontName='Helvetica-Bold', textColor=_INK, alignment=TA_RIGHT)
    total_value_style = _style('GrandValue', fontSize=11, fontName='Helvetica-Bold', textColor=_ACCENT, alignment=TA_RIGHT)

    rows = [
        [Paragraph('Sous-total', label_style), Paragraph(f'{quote.subtotal:,.0f} {currency}', value_style)],
    ]
    if float(quote.tax_rate) > 0:
        rows.append([
            Paragraph(f'TVA ({quote.tax_rate}%)', label_style),
            Paragraph(f'{quote.tax_amount:,.0f} {currency}', value_style),
        ])
    rows.append([
        Paragraph('TOTAL', total_label_style),
        Paragraph(f'{quote.total:,.0f} {currency}', total_value_style),
    ])

    col_w = PAGE_W - 2 * MARGIN
    t = Table(rows, colWidths=[col_w * 0.75, col_w * 0.25])
    t.setStyle(TableStyle([
        ('ALIGN', (0, 0), (-1, -1), 'RIGHT'),
        ('LINEABOVE', (0, -1), (-1, -1), 1, _BORDER),
        ('TOPPADDING', (0, -1), (-1, -1), 4),
    ]))
    story.append(t)


def _add_notes(story, quote: Quote, styles):
    story.append(Paragraph('Notes', _style('NL', fontSize=8, fontName='Helvetica-Bold', textColor=_MUTED)))
    story.append(Spacer(1, 2 * mm))
    story.append(Paragraph(quote.notes, _style('NT', fontSize=9, textColor=_INK)))


def _add_signatures(story, sigs, styles):
    label_s = _style('SL', fontSize=8, fontName='Helvetica-Bold', textColor=_MUTED, alignment=TA_CENTER)
    text_s = _style('ST', fontSize=8, textColor=_INK, alignment=TA_CENTER)
    col_w = (PAGE_W - 2 * MARGIN) / len(sigs)
    cells = []
    for sig in sigs:
        cells.append([Paragraph(sig.label, label_s), Spacer(1, 2 * mm), Paragraph(sig.text, text_s)])
    t = Table([cells], colWidths=[col_w] * len(sigs))
    t.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('LINEABOVE', (0, 0), (-1, -1), 0.5, _BORDER),
        ('TOPPADDING', (0, 0), (-1, -1), 3),
    ]))
    story.append(t)


def _add_footer(story, quote: Quote, styles):
    company = quote.company
    content_w = PAGE_W - 2 * MARGIN
    location = (getattr(company, 'location', None) or '').strip()
    footer_bg = _load_image_bytes(getattr(company, 'footer_image_url', None))

    if footer_bg or location:
        story.append(Spacer(1, 8 * mm))

        if footer_bg:
            # Image rognée = fond du cadre footer.  Si localisation renseignée,
            # le texte blanc s'affiche par-dessus avec un voile sombre.
            if location:
                loc_style = _style(
                    'FooterLoc', fontSize=11, fontName='Helvetica-Bold',
                    textColor=_WHITE, alignment=TA_CENTER, leading=14,
                )
                inner = Table(
                    [[Paragraph(location, loc_style)]],
                    colWidths=[content_w],
                )
                inner.setStyle(TableStyle([
                    ('TOPPADDING',    (0, 0), (-1, -1), 8),
                    ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
                    ('LEFTPADDING',   (0, 0), (-1, -1), 10),
                    ('RIGHTPADDING',  (0, 0), (-1, -1), 10),
                ]))
                story.append(_BackgroundCard(inner, bg_data=footer_bg, overlay_alpha=0.45))
            else:
                # Juste l'image, hauteur fixe via un Spacer.
                inner = Table(
                    [[Spacer(content_w, 28 * mm)]],
                    colWidths=[content_w],
                )
                story.append(_BackgroundCard(inner, bg_data=footer_bg, overlay_alpha=0.0))
        else:
            # Pas d'image : bandeau coloré classique avec le texte.
            banner_style = _style(
                'FooterBanner', fontSize=11, fontName='Helvetica-Bold',
                textColor=_WHITE, alignment=TA_CENTER, leading=14,
            )
            banner = Table([[Paragraph(location, banner_style)]], colWidths=[content_w])
            banner.setStyle(TableStyle([
                ('BACKGROUND',    (0, 0), (-1, -1), _INK),
                ('TOPPADDING',    (0, 0), (-1, -1), 8),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
                ('LEFTPADDING',   (0, 0), (-1, -1), 10),
                ('RIGHTPADDING',  (0, 0), (-1, -1), 10),
                ('VALIGN',        (0, 0), (-1, -1), 'MIDDLE'),
            ]))
            story.append(banner)

    # Mention discrète DATO sous la bannière.
    story.append(Spacer(1, 4 * mm))
    story.append(HRFlowable(width='100%', thickness=0.5, color=_BORDER))
    story.append(Spacer(1, 2 * mm))
    footer_s = _style('F', fontSize=7, textColor=_MUTED, alignment=TA_CENTER)
    story.append(Paragraph(f'Document généré par DATO · {company.name}', footer_s))


def _hex(color) -> str:
    r, g, b = int(color.red * 255), int(color.green * 255), int(color.blue * 255)
    return f'{r:02X}{g:02X}{b:02X}'
