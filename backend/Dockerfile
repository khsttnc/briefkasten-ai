FROM python:3.12-slim

# tesseract-ocr-deu: German OCR fallback (see app/config.py TESSERACT_CMD /
# app/document_processing.py) - without it, scanned/image-only German
# documents fail OCR even though the base tesseract-ocr package is present.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        tesseract-ocr \
        tesseract-ocr-deu \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app/backend

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

COPY entrypoint.sh /app/backend/entrypoint.sh
RUN chmod +x /app/backend/entrypoint.sh

EXPOSE 8000

ENTRYPOINT ["/app/backend/entrypoint.sh"]
