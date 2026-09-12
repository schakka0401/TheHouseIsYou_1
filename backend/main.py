from fastapi import FastAPI, HTTPException, status

from backend.database import check_database
from backend.routes import router as sessions_router


app = FastAPI(
    title="The House Is You API",
    description="Backend API for game sessions, results, and financial analysis.",
    version="0.1.0",
)

app.include_router(sessions_router)


@app.get("/")
def root():
    return {
        "name": "The House Is You API",
        "status": "running",
        "documentation": "/docs",
    }


@app.get("/health")
def health():
    return {
        "status": "healthy",
    }


@app.get("/ready")
def readiness():
    if not check_database():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database unavailable",
        )

    return {
        "status": "ready",
        "database": "connected",
    }