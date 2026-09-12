from fastapi import FastAPI, HTTPException

from backend.database import check_database


app = FastAPI(
    title="Confidence Casino API",
    version="0.1.0"
)


@app.get("/")
def root():
    return {
        "name": "Confidence Casino API",
        "status": "running"
    }


@app.get("/health")
def health():
    return {"status": "healthy"}


@app.get("/ready")
def readiness():
    if not check_database():
        raise HTTPException(
            status_code=503,
            detail="Database unavailable"
        )

    return {
        "status": "ready",
        "database": "connected"
    }