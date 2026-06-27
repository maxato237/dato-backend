# DATO backend — Python + LibreOffice.
#
# LibreOffice (headless) est nécessaire pour convertir les modèles Word (.docx)
# en PDF côté serveur. Sans lui, l'app retombe sur son rendu PDF interne.
FROM python:3.11-slim-bookworm

# LibreOffice Writer (fournit `soffice`/`libreoffice`) + polices pour un rendu
# correct des accents et des caractères français (œ, é, …).
RUN apt-get update && apt-get install -y --no-install-recommends \
        libreoffice-writer \
        fonts-liberation \
        fonts-dejavu \
    && rm -rf /var/lib/apt/lists/*

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    FLASK_ENV=production \
    # LibreOffice a besoin d'un HOME inscriptible pour écrire son profil.
    HOME=/tmp

WORKDIR /app

# Dépendances Python en couche séparée (cache de build).
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Code de l'application.
COPY . .

EXPOSE 8080

# gunicorn sert l'app Flask (run.py expose `app`, qui lit FLASK_ENV).
CMD ["gunicorn", "run:app", "--bind", "0.0.0.0:8080", "--workers", "1", "--timeout", "120"]
