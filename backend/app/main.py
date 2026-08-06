from fastapi import FastAPI, UploadFile, File
import shutil
import os
import fitz


app = FastAPI(
    title="Briefkasten AI",
    description="AI assistant for German documents",
    version="0.1.0"
)


UPLOAD_FOLDER = "uploads"

os.makedirs(UPLOAD_FOLDER, exist_ok=True)


@app.get("/")
def home():
    return {
        "message": "Welcome to Briefkasten AI"
    }


@app.post("/upload")
async def upload_document(file: UploadFile = File(...)):

    file_path = os.path.join(
        UPLOAD_FOLDER,
        file.filename
    )

    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(
            file.file,
            buffer
        )

    return {
        "filename": file.filename,
        "status": "uploaded"
    }


@app.get("/analyze/{filename}")
def analyze_document(filename: str):

    file_path = os.path.join(
        UPLOAD_FOLDER,
        filename
    )

    doc = fitz.open(file_path)

    text = ""

    for page in doc:
        text += page.get_text()

    return {
        "filename": filename,
        "characters": len(text),
        "text": text[:1000]
    }