from fastapi import Depends, FastAPI, File, UploadFile
from sqlalchemy.orm import Session
import fitz

from .database import engine, get_db
from .models import Base
from .services import save_document

Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="Briefkasten AI",
    description="AI assistant for German documents",
    version="0.1.0"
)


@app.get("/")
def home():
    return {
        "message": "Welcome to Briefkasten AI"
    }


@app.post("/upload")
async def upload_document(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    save_document(file, db)

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

