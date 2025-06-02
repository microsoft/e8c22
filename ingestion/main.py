import logging
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv

from ingestion.api.routes import router

load_dotenv()
logging.basicConfig(level=logging.INFO)

app = FastAPI(
    title="News Search & Ingestion API",
    description=(
        "API that searches news using Bing and NewsAPI.org, extracts article content from URLs, "
        "and stores the content as files in Azure Blob Storage. Automatic Swagger docs available at /docs."
    ),
    version="1.0.0"
)


# CORS middleware setup
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Adjust as needed for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include API routes
app.include_router(router)