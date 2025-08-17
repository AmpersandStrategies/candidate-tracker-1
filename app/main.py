"""FastAPI application"""
from fastapi import FastAPI
from app.api.routes import router
from app.utils.logging import setup_logging

setup_logging()

app = FastAPI(
    title="Ampersand Candidate Tracker",
    description="Production candidate tracking system",
    version="1.0.0"
)

app.include_router(router)

@app.get("/")
async def root():
    return {"message": "Ampersand Candidate Tracker API"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
