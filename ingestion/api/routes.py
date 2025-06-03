import os
import logging
from typing import Optional

from fastapi import APIRouter, Query, HTTPException, Depends
from fastapi.responses import RedirectResponse

from utils.search import BlobStorageConfig, BingSearchService, NewsApiSearchService, KaggleSearchService

logger = logging.getLogger(__name__)
router = APIRouter()


def get_blob_storage_config():
    return BlobStorageConfig(
        blob_account_url=os.environ.get("BLOB_ACCOUNT_URL"),
        blob_storage_container_name=os.environ.get("BLOB_STORAGE_CONTAINER_NAME"),
        blob_storage_connection_string=os.environ.get("BLOB_STORAGE_CONNECTION_STRING")
)


@router.get("/", include_in_schema=False)
async def root_redirect():
    return RedirectResponse(url="/docs")


@router.get("/bingsearch", summary="Grounding with Bing Search Endpoint", description="Search for information using the Bing Grounding AI agent.")
async def bing_search(
    query: str = Query(..., description="Search query"),
    config: BlobStorageConfig = Depends(get_blob_storage_config)):
    try:
        service = BingSearchService(config)
        return service.search(query)
    except Exception as e:
        logger.error(f"Bing search error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/newsapi", summary="News API Search Endpoint", description="Search for news articles using the News API.")
async def newsapi_search(
    query: str = Query(
        ...,
        max_length=500,
        description=(
            "Keywords or phrases to search for in the article title and body. "
            "Advanced search: quotes (\") for exact, + for must include, - for exclude, "
            "AND/OR/NOT for logic, group with parentheses. URL-encoded."
        ),        
    ),
    searchIn: Optional[str] = Query(
        None,
        description="Fields to restrict your search to: title, description, content. Comma-separated."
    ),
    sources: Optional[str] = Query(
        None,
        description="Comma-separated string of identifiers (max 20) for the news sources or blogs."
    ),
    domains: Optional[str] = Query(
        None,
        description="Comma-separated string of domains to restrict the search to."
    ),
    excludeDomains: Optional[str] = Query(
        None,
        description="Comma-separated string of domains to remove from the results."
    ),
    from_param: Optional[str] = Query(
        None,
        alias="from",
        description="ISO 8601 date or datetime for the oldest article allowed (e.g. 2025-05-29 or 2025-05-29T12:17:38)."
    ),
    to: Optional[str] = Query(
        None,
        description="ISO 8601 date or datetime for the newest article allowed (e.g. 2025-05-29 or 2025-05-29T12:17:38)."
    ),
    language: Optional[str] = Query(
        "en",
        min_length=2, max_length=2,
        description="2-letter ISO-639-1 code of the language to get headlines for (e.g., en, fr, de, etc)."
    ),
    sortBy: Optional[str] = Query(
        "publishedAt",
        pattern="^(relevancy|popularity|publishedAt)$",
        description="Sort order: relevancy, popularity, publishedAt. Default is publishedAt."
    ),
    pageSize: Optional[int] = Query(
        10,
        ge=1, le=10,
        description="Number of results per page (max 100)."
    ),
    page: Optional[int] = Query(
        1,
        ge=1,
        description="Page number for results pagination."
    ),
    config: BlobStorageConfig = Depends(get_blob_storage_config)
):  
    try:
        service = NewsApiSearchService(config)
        search_params = {
            "sources": sources,
            "searchIn": searchIn,
            "domains": domains,
            "excludeDomains": excludeDomains,
            "from_param": from_param,
            "to": to,
            "language": language,
            "sortBy": sortBy,
            "pageSize": pageSize,
            "page": page
        }
        return service.search(query, **search_params)
    except Exception as e:
        logger.error(f"News API search error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

    
@router.post(
    "/kaggle",
    summary="Kaggle Search Endpoint",
    description="Search for news articles using Kaggle."    
)
async def kaggle_search(
    config: BlobStorageConfig = Depends(get_blob_storage_config)    
):
    try:
        service = KaggleSearchService(config)
        articles = service.search()
        
        return articles
    except Exception as e:
        logger.error(f"Kaggle search error: {e}")
        raise HTTPException(status_code=500, detail=str(e))
