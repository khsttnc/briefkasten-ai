from fastapi import FastAPI

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