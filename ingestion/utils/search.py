import os
import re
import logging
import time
import random
import string
import uuid
from abc import ABC, abstractmethod

from typing import List, Any, Optional, List, Dict
from dataclasses import dataclass

from azure.ai.projects import AIProjectClient
from azure.ai.agents.models import BingGroundingTool
from azure.identity import DefaultAzureCredential
from newsapi import NewsApiClient
from newspaper import Article

from ingestion.utils.common import EnvironmentValidator
from ingestion.utils.blob import create_blob_service, UploadConfig


@dataclass
class BlobStorageConfig:
    """Configuration for storing results in blob storage"""    
    blob_storage_container_name: str
    blob_account_url: Optional[str] = None,
    blob_storage_connection_string: Optional[str] = None
    chunk_size: int = 1024 * 1024  # 1MB default

@dataclass
class ArticleData:
    """Data class for article information"""    
    url: str
    title: str
    text: str

class ArticleExtractor:
    """Handles article text extraction from URLs"""
    
    def __init__(self):
        """Initialize with named logger"""
        self.logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")
    
    def extract_from_url(self, url: str) -> Optional[ArticleData]:
        """Extract article content from a URL"""
        self.logger.info(f"Extracting article text from {url}")
        
        try:
            article = Article(url)
            article.download()
            article.parse()
                                    
            self.logger.info(f"Extracted {len(article.text)} characters from {article.title}")
            
            return ArticleData(
                url=url,                
                title=article.title,
                text=article.text
            )
        except Exception as e:
            self.logger.error(f"Failed extracting from {url}: {e}")
            return None
    
    def extract_from_urls(self, urls: List[str]) -> List[ArticleData]:
        """Extract articles from multiple URLs"""
        articles = []
        for url in urls:
            article_data = self.extract_from_url(url)
            if article_data:
                articles.append(article_data)
        return articles

class ArticleStorageManager:
    """Manages article storage to blob storage"""
    
    def __init__(self, config: BlobStorageConfig):
        """Initialize with config and named logger"""
        self.config = config
        self.logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")        
        self.blob_client = create_blob_service(container_name=config.blob_storage_container_name, account_url=config.blob_account_url, connection_string=config.blob_storage_connection_string)
    
    def store_articles(self, articles: List[ArticleData]) -> None:
        """Store articles in blob storage"""
        self.logger.info("Uploading articles to blob storage...")

        for article in articles:
            try:
                article_name = self._generate_unique_article_name()
                article_title = article.title.encode('ascii', errors='ignore').decode('ascii', errors='ignore')
                blob_metadata = {
                    "article_url": article.url,    
                    "article_title": article_title
                }

                uploadConfig = UploadConfig(metadata=blob_metadata, chunk_size=self.config.chunk_size)

                success = self.blob_client.upload_text(
                    text_data=article.text,
                    blob_name=article_name,
                    config=uploadConfig
                )

                if success:
                    self.logger.info(f"Article '{article.title}' uploaded successfully to blob storage.")
                else:
                    self.logger.warning(f"Failed to upload article '{article.title}' to blob storage.")
            except Exception as e:
                self.logger.error(f"Exception uploading article '{getattr(article, 'title', 'unknown')}' (URL: {getattr(article, 'url', 'unknown')}): {e}")
    
    @staticmethod
    def _generate_unique_article_name(prefix: str = "article", extension: str = ".txt") -> str:
        """Generate a random, valid name using a UUID."""
        unique_id = uuid.uuid4().hex
        artile_name = f"{prefix}_{unique_id}{extension}"
        return artile_name
                        
class BaseSearchService(ABC):
    """Abstract base class for search services"""
        
    def __init__(self, config: BlobStorageConfig):
        self.config = config
        self.storage_manager = ArticleStorageManager(config)
        self.logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")
    
    @abstractmethod
    def search(self, query: str, **kwargs) -> Any:
        """Perform search operation"""
        pass
    
    def _process_articles(self, urls: List[str]) -> List[ArticleData]:
        """Common article processing logic"""
        self.logger.info(f"Found {len(urls)} articles to process")
        extractor = ArticleExtractor()
        articles = extractor.extract_from_urls(urls)
        self.storage_manager.store_articles(articles)
        return articles
    
class BingSearchService(BaseSearchService):
    """Service for Bing Grounding AI agent search"""
    
    def __init__(self, config: BlobStorageConfig):
        super().__init__(config)
        self.required_vars = [
            "AI_FOUNDRY_PROJECT_ENDPOINT",
            "BING_CONNECTION_NAME",
            "BLOB_STORAGE_CONTAINER_NAME"            
        ]
        self.logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")
    
    def search(self, query: str) -> Any:
        """Perform Bing search using AI agent"""
        EnvironmentValidator.validate_required_vars(self.required_vars)
        
        ai_foundry_project_endpoint = os.environ.get("AI_FOUNDRY_PROJECT_ENDPOINT")
        bing_connection_name = os.environ.get("BING_CONNECTION_NAME")
        agent_name = os.environ.get("AGENT_NAME")
        agent_instructions = os.environ.get("AGENT_INSTRUCTIONS")
        agent_llm = os.environ.get("AGENT_LLM", 'gpt-4o')
        
        project_client = None
        agent = None
        thread = None
        
        try:
            self.logger.info("Initializing Azure AI Project Client...")
            project_client = AIProjectClient(
                endpoint=ai_foundry_project_endpoint,
                credential=DefaultAzureCredential(),
            )
            
            # Setup Bing connection
            bing_connection = project_client.connections.get(name=bing_connection_name)
            bing_tool = BingGroundingTool(connection_id=bing_connection.id)
            
            # Get or create agent
            agents = project_client.agents.list_agents()
            agent = next((a for a in agents if a.name == agent_name), None)
            
            if agent is None:
                self.logger.info("Creating agent with Bing Grounding Tool...")
                agent = project_client.agents.create_agent(
                    model=agent_llm,
                    name=self._generate_unique_agent_name(),
                    instructions=agent_instructions,
                    tools=bing_tool.definitions
                )
                self.logger.info(f"Created agent, ID: {agent.id}")
            
            # Create thread and run search
            thread = project_client.agents.threads.create()
            self.logger.info(f"Created thread, ID: {thread.id}")
            
            user_message = project_client.agents.messages.create(
                thread_id=thread.id,
                role="user",
                content=query
            )
            
            run = project_client.agents.runs.create_and_process(
                thread_id=thread.id,
                agent_id=agent.id
            )
            
            if run.status == "failed":
                self.logger.error(f"Run failed: {run.last_error}")
                raise Exception(f"Agent run failed: {run.last_error}")
            
            # Process results
            last_message = project_client.agents.messages.get_last_message_text_by_role(
                thread_id=thread.id, role="assistant"
            )
            
            # Extract URLs from annotations
            urls = self._extract_urls_from_annotations(last_message.text.annotations)
            self._process_articles(urls)
            
            return last_message
            
        finally:
            self._cleanup_resources(project_client, thread, agent)
    
    def _extract_urls_from_annotations(self, annotations: List[Any]) -> List[str]:
        """Extract URLs from message annotations"""
        urls = []
        for ann in annotations:
            url = ann.get('url_citation', {}).get('url')
            if url:
                urls.append(url)
        return urls
    
    def _cleanup_resources(self, project_client, thread, agent):
        """Clean up Azure resources"""
        try:
            if thread and project_client:
                self.logger.info(f"Deleting thread {thread.id}...")
                project_client.agents.threads.delete(thread.id)                
            if agent and project_client:
                self.logger.info(f"Deleting agent {agent.id}...")
                project_client.agents.delete_agent(agent.id)                
            if project_client:
                project_client.close()
        except Exception as e:
            self.logger.error(f"Error during cleanup: {e}")
    
    @staticmethod
    def _generate_unique_agent_name(prefix="Agent"):
        """Generate a unique agent name with timestamp and random suffix"""
        timestamp = int(time.time())
        rand_suffix = ''.join(random.choices(string.ascii_uppercase + string.digits, k=4))
        return f"{prefix}{timestamp}{rand_suffix}"
    
class NewsApiSearchService(BaseSearchService):
    """Service for News API search"""
    
    def __init__(self, config: BlobStorageConfig):
        super().__init__(config)
        self.required_vars = [
            "NEWS_API_KEY",            
            "BLOB_STORAGE_CONTAINER_NAME"
        ]
        self.logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")
    
    def search(self, query: str, **search_params) -> Dict[str, Any]:
        """Perform News API search"""
        EnvironmentValidator.validate_required_vars(self.required_vars)
        
        news_api_key = os.environ.get("NEWS_API_KEY")
        newsapi = NewsApiClient(api_key=news_api_key)
        
        # Build search parameters
        kwargs = {
            "q": query,
            "sources": search_params.get("sources"),
            "searchIn": search_params.get("searchIn"),
            "domains": search_params.get("domains"),
            "exclude_domains": search_params.get("excludeDomains"),
            "from_param": search_params.get("from_param"),
            "to": search_params.get("to"),
            "language": search_params.get("language", "en"),
            "sort_by": search_params.get("sortBy", "publishedAt"),
            "page_size": search_params.get("pageSize", 100),
            "page": search_params.get("page", 1)
        }
        
        # Filter out None values
        filtered_kwargs = {k: v for k, v in kwargs.items() if v is not None}
        
        # Perform search
        news = newsapi.get_everything(**filtered_kwargs)
        
        # Extract and process articles
        urls = [article['url'] for article in news['articles']]
        self._process_articles(urls)
        
        return news
    