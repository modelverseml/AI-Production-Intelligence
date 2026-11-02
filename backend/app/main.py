from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.config import settings
from app.database import Base, engine
from app.routes import router

@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind = engine)
    yield

app = FastAPI(
    title = "AI Incident Intelligence API",
    lifespan = lifespan
)
app.add_middleware(
    CORSMiddleware,
    allow_origins = [
        origin.strip() for origin in settings.CORS_ORIGINS.split(',')
    ],
    allow_credentials = True,
    allow_methods = ['GET','POST','PATCH'],
    allow_headers = ['Authorization',"Content-Type"]
)

app.include_router(router, prefix = "/api")

@app.get("/health")
def health():
    return {"status": "ok"}