import logging
import re
import base64
import mimetypes

from typing import Optional, Dict, Any, Union, List
from dataclasses import dataclass, field
from pathlib import Path
from contextlib import contextmanager

from azure.identity import DefaultAzureCredential
from azure.storage.blob import BlobServiceClient, BlobClient, ContentSettings
from azure.core.exceptions import AzureError, ResourceNotFoundError, ResourceExistsError


class BlobStorageError(Exception):
    """Base exception for blob storage operations."""
    pass


class BlobNotFoundError(BlobStorageError):
    """Exception raised when a blob is not found."""
    pass


class BlobAlreadyExistsError(BlobStorageError):
    """Exception raised when trying to create a blob that already exists."""
    pass

@dataclass
class BlobMetadata:
    """Represents blob metadata and properties."""
    name: str
    size: int
    content_type: str
    last_modified: Any
    etag: str
    metadata: Dict[str, str] = field(default_factory=dict)
    

@dataclass
class UploadConfig:
    """Configuration for blob upload operations."""
    chunk_size: int = 4 * 1024 * 1024  # 4MB default
    overwrite: bool = True
    content_type: Optional[str] = None
    metadata: Optional[Dict[str, str]] = None
    progress_callback: Optional[callable] = None
    
        
class ContentTypeDetector:
    """Handles content type detection for files."""
    
    @staticmethod
    def detect(file_path: Union[str, Path]) -> str:
        """Detect content type based on file extension."""
        content_type, _ = mimetypes.guess_type(str(file_path))
        return content_type or 'application/octet-stream'

    
class BlobNameValidator:
    """Validates and sanitizes blob names."""
    
    ILLEGAL_CHARS_PATTERN = re.compile(r'[\\/?#%]')
    WHITESPACE_PATTERN = re.compile(r'\s+')
    MAX_LENGTH = 1024  # Azure blob name limit
    
    @classmethod
    def sanitize(cls, name: str, add_extension: bool = True) -> str:
        """
        Convert to a safe blob name by replacing illegal characters.
        
        Args:
            name: Original name to sanitize
            add_extension: Whether to add .txt extension
            
        Returns:
            Sanitized blob name
        """
        if not name:
            raise ValueError("Blob name cannot be empty")
        
        # Replace illegal characters with underscore
        safe = cls.ILLEGAL_CHARS_PATTERN.sub('_', name)
        
        # Replace spaces with underscores
        safe = cls.WHITESPACE_PATTERN.sub('_', safe)
        
        # Remove leading/trailing dots and spaces
        safe = safe.strip(' .')
        
        # Ensure name is not empty after sanitization
        if not safe:
            safe = "unnamed"
        
        # Limit length
        if add_extension:
            max_base_length = cls.MAX_LENGTH - 4  # Reserve space for .txt
            safe = safe[:max_base_length]
            safe = f"{safe}.txt"
        else:
            safe = safe[:cls.MAX_LENGTH]
        
        return safe
    
    @classmethod
    def validate(cls, name: str) -> bool:
        """Check if blob name is valid without sanitization."""
        if not name or len(name) > cls.MAX_LENGTH:
            return False
        
        if cls.ILLEGAL_CHARS_PATTERN.search(name) or name != name.strip(' .'):
            return False
        
        return True
    
class ChunkedUploader:
    """Handles chunked upload operations."""
    
    def __init__(self, blob_client: BlobClient):
        self.blob_client = blob_client
        self.logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")
    
    def upload(
        self,
        data: bytes,
        config: UploadConfig
    ) -> bool:
        """
        Upload data using chunked upload strategy.
        
        Args:
            data: Bytes data to upload
            config: Upload configuration
            
        Returns:
            True if upload successful
            
        Raises:
            BlobStorageError: If upload fails
        """
        total_size = len(data)
        
        try:
            # For small files, use simple upload
            if total_size <= config.chunk_size:
                return self._simple_upload(data, config)
            
            # Use staged upload for larger files
            return self._staged_upload(data, config)
            
        except AzureError as e:
            raise BlobStorageError(f"Upload failed: {e}") from e
    
    def _simple_upload(self, data: bytes, config: UploadConfig) -> bool:
        """Upload small files in one operation."""
        content_settings = ContentSettings(content_type=config.content_type) if config.content_type else None
        
        self.blob_client.upload_blob(
            data,
            overwrite=config.overwrite,
            content_settings=content_settings,
            metadata=config.metadata
        )
        
        self.logger.info(f"Completed simple upload ({len(data)} bytes)")
        return True
    
    def _staged_upload(self, data: bytes, config: UploadConfig) -> bool:
        """Upload large files using staged blocks."""
        total_size = len(data)
        block_list = []
        chunk_count = 0
        
        self.logger.info(f"Starting staged upload ({total_size} bytes)")
        
        for i in range(0, total_size, config.chunk_size):
            chunk = data[i:i + config.chunk_size]
            block_id = self._generate_block_id(chunk_count)
            
            # Upload block
            self.blob_client.stage_block(block_id, chunk)
            block_list.append(block_id)
            chunk_count += 1
            
            # Report progress
            current_pos = min(i + config.chunk_size, total_size)
            if config.progress_callback:
                config.progress_callback(current_pos, total_size, f"Chunk {chunk_count}")
            
            progress_pct = (current_pos / total_size) * 100
            self.logger.debug(f"Uploaded chunk {chunk_count} ({progress_pct:.1f}%)")
        
        # Commit all blocks
        content_settings = ContentSettings(content_type=config.content_type) if config.content_type else None
        
        self.blob_client.commit_block_list(
            block_list,
            content_settings=content_settings,
            metadata=config.metadata
        )
        
        self.logger.info(f"Successfully completed staged upload in {chunk_count} chunks")
        return True
    
    @staticmethod
    def _generate_block_id(block_number: int) -> str:
        """Generate a base64-encoded block ID."""
        block_id = f"block-{block_number:08d}"  # More padding for better sorting
        return base64.b64encode(block_id.encode()).decode()
    

class BlobStorageServiceClient:
    """
    A service class for managing Azure Blob Storage operations.
    Provides high-level operations with proper error handling and logging.
    """
    
    def __init__(
        self,
        container_name: str = None,
        account_url: Optional[str] = None,
        credential: Optional[Any] = None,
        connection_string: Optional[str] = None,
        create_container: bool = True
    ):
        """
        Initialize the blob storage service.

        Args:
            connection_string: Azure Storage connection string (optional if using account_url + credential)
            container_name: Name of the blob container
            account_url: Azure Storage account URL (e.g., https://<account>.blob.core.windows.net/)
            credential: Azure credential object (e.g., DefaultAzureCredential)
            create_container: Whether to create container if it doesn't exist
        """        
        self.container_name = container_name        
        self.logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")
        
        # Prefer account_url + DefaultAzureCredential if provided, else fallback to connection_string
        if account_url and container_name:
            self.account_url = account_url
            self.credential = credential or DefaultAzureCredential()
            self.blob_service_client = BlobServiceClient(account_url=account_url, credential=self.credential)
        elif connection_string and container_name:
            self.connection_string = connection_string
            self.blob_service_client = BlobServiceClient.from_connection_string(connection_string)
        else:
            raise ValueError("Must provide either (connection_string and container_name) or (account_url and container_name)")
        
        if create_container:
            self._ensure_container_exists()
    
    def _ensure_container_exists(self) -> None:
        """Create container if it doesn't exist."""
        try:
            container_client = self.blob_service_client.get_container_client(self.container_name)
            container_client.create_container()
            self.logger.info(f"Created container: {self.container_name}")
        except ResourceExistsError:
            self.logger.info(f"Container already exists: {self.container_name}")
        except AzureError as e:
            self.logger.warning(f"Container creation issue: {e}")
            raise BlobStorageError(f"Failed to ensure container exists: {e}") from e
    
    @contextmanager
    def _get_blob_client(self, blob_name: str):
        """Context manager for blob client operations."""
        try:
            blob_client = self.blob_service_client.get_blob_client(
                container=self.container_name,
                blob=blob_name
            )
            yield blob_client
        except AzureError as e:
            raise BlobStorageError(f"Failed to get blob client for {blob_name}: {e}") from e
    
    def upload_text(
        self,
        text_data: str,
        blob_name: str,
        config: Optional[UploadConfig] = None
    ) -> bool:
        """
        Upload text data to blob storage.
        
        Args:
            text_data: Text content to upload
            blob_name: Name of the blob in storage
            config: Upload configuration
            
        Returns:
            True if upload successful
            
        Raises:
            BlobStorageError: If upload fails
        """
        if config is None:
            config = UploadConfig(content_type="text/plain; charset=utf-8")
        elif config.content_type is None:
            config.content_type = "text/plain; charset=utf-8"
        
        try:                 
            text_bytes = self._safe_utf8_bytes(text_data)
            return self._upload_bytes(text_bytes, blob_name, config)
        except UnicodeEncodeError as e:
            raise BlobStorageError(f"Failed to encode text data: {e}") from e
        
    def _sanitize_text(self, text: str) -> str:
        # Remove control characters except basic whitespace        
        text = re.sub(r'[\x00-\x08\x0b-\x0c\x0e-\x1f\x7f-\x9f]', '', text)
        return text

    def _safe_utf8_bytes(self, text: str) -> bytes:
        clean = self._sanitize_text(text)
        # This will replace any weird chars with the Unicode replacement char �
        return clean.encode('utf-8', errors='replace')
    
    def upload_file(
        self,
        file_path: Union[str, Path],
        blob_name: str,
        config: Optional[UploadConfig] = None
    ) -> bool:
        """
        Upload file to blob storage.
        
        Args:
            file_path: Path to the file to upload
            blob_name: Name of the blob in storage
            config: Upload configuration
            
        Returns:
            True if upload successful
            
        Raises:
            BlobStorageError: If upload fails
            FileNotFoundError: If file doesn't exist
        """
        file_path = Path(file_path)
        
        if not file_path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")
        
        if config is None:
            config = UploadConfig()
        
        # Auto-detect content type if not provided
        if config.content_type is None:
            config.content_type = ContentTypeDetector.detect(file_path)
        
        try:
            file_data = file_path.read_bytes()
            return self._upload_bytes(file_data, blob_name, config)
        except OSError as e:
            raise BlobStorageError(f"Failed to read file {file_path}: {e}") from e
    
    def _upload_bytes(
        self,
        data: bytes,
        blob_name: str,
        config: UploadConfig
    ) -> bool:
        """Internal method to upload bytes data."""
        with self._get_blob_client(blob_name) as blob_client:
            # Check if blob exists and handle overwrite
            if not config.overwrite and self._blob_exists(blob_client):
                raise BlobAlreadyExistsError(f"Blob {blob_name} exists and overwrite=False")
            
            uploader = ChunkedUploader(blob_client)
            return uploader.upload(data, config)
        
    def download_text(self, blob_name: str, encoding: str = 'utf-8') -> str:
        """
        Download blob content as text.
        
        Args:
            blob_name: Name of the blob to download
            encoding: Text encoding to use
            
        Returns:
            Text content
            
        Raises:
            BlobNotFoundError: If blob doesn't exist
            BlobStorageError: If download fails
        """
        try:
            with self._get_blob_client(blob_name) as blob_client:
                download_stream = blob_client.download_blob()
                return download_stream.readall().decode(encoding)
        except ResourceNotFoundError:
            raise BlobNotFoundError(f"Blob not found: {blob_name}")
        except UnicodeDecodeError as e:
            raise BlobStorageError(f"Failed to decode blob content: {e}") from e
        except AzureError as e:
            raise BlobStorageError(f"Failed to download {blob_name}: {e}") from e
    
    def download_bytes(self, blob_name: str) -> bytes:
        """
        Download blob content as bytes.
        
        Args:
            blob_name: Name of the blob to download
            
        Returns:
            Binary content
            
        Raises:
            BlobNotFoundError: If blob doesn't exist
            BlobStorageError: If download fails
        """
        try:
            with self._get_blob_client(blob_name) as blob_client:
                download_stream = blob_client.download_blob()
                return download_stream.readall()
        except ResourceNotFoundError:
            raise BlobNotFoundError(f"Blob not found: {blob_name}")
        except AzureError as e:
            raise BlobStorageError(f"Failed to download {blob_name}: {e}") from e
    
    def list_blobs(self, prefix: Optional[str] = None, include_metadata: bool = False) -> List[str]:
        """
        List all blobs in the container.
        
        Args:
            prefix: Optional prefix to filter blobs
            include_metadata: Whether to include metadata in results
            
        Returns:
            List of blob names or BlobMetadata objects
            
        Raises:
            BlobStorageError: If listing fails
        """
        try:
            container_client = self.blob_service_client.get_container_client(self.container_name)
            
            blobs = container_client.list_blobs(
                name_starts_with=prefix,
                include=['metadata'] if include_metadata else None
            )
            
            if include_metadata:
                return [
                    BlobMetadata(
                        name=blob.name,
                        size=blob.size,
                        content_type=blob.content_settings.content_type or 'unknown',
                        last_modified=blob.last_modified,
                        etag=blob.etag,
                        metadata=blob.metadata or {}
                    )
                    for blob in blobs
                ]
            else:
                return [blob.name for blob in blobs]
                
        except AzureError as e:
            raise BlobStorageError(f"Failed to list blobs: {e}") from e
    
    def delete_blob(self, blob_name: str, must_exist: bool = False) -> bool:
        """
        Delete a blob from storage.
        
        Args:
            blob_name: Name of the blob to delete
            must_exist: If True, raises error if blob doesn't exist
            
        Returns:
            True if deleted, False if didn't exist (when must_exist=False)
            
        Raises:
            BlobNotFoundError: If blob doesn't exist and must_exist=True
            BlobStorageError: If deletion fails
        """
        try:
            with self._get_blob_client(blob_name) as blob_client:
                blob_client.delete_blob()
                self.logger.info(f"Deleted blob: {blob_name}")
                return True
                
        except ResourceNotFoundError:
            if must_exist:
                raise BlobNotFoundError(f"Blob not found: {blob_name}")
            self.logger.debug(f"Blob {blob_name} did not exist")
            return False
        except AzureError as e:
            raise BlobStorageError(f"Failed to delete {blob_name}: {e}") from e
    
    def get_blob_metadata(self, blob_name: str) -> BlobMetadata:
        """
        Get metadata and properties of a blob.
        
        Args:
            blob_name: Name of the blob
            
        Returns:
            Blob metadata
            
        Raises:
            BlobNotFoundError: If blob doesn't exist
            BlobStorageError: If operation fails
        """
        try:
            with self._get_blob_client(blob_name) as blob_client:
                properties = blob_client.get_blob_properties()
                
                return BlobMetadata(
                    name=blob_name,
                    size=properties.size,
                    content_type=properties.content_settings.content_type or 'unknown',
                    last_modified=properties.last_modified,
                    etag=properties.etag,
                    metadata=properties.metadata or {}
                )
                
        except ResourceNotFoundError:
            raise BlobNotFoundError(f"Blob not found: {blob_name}")
        except AzureError as e:
            raise BlobStorageError(f"Failed to get properties for {blob_name}: {e}") from e
    
    def blob_exists(self, blob_name: str) -> bool:
        """
        Check if a blob exists.
        
        Args:
            blob_name: Name of the blob to check
            
        Returns:
            True if blob exists, False otherwise
        """
        try:
            with self._get_blob_client(blob_name) as blob_client:
                return self._blob_exists(blob_client)
        except BlobStorageError:
            return False
        
    def _blob_exists(self, blob_client: BlobClient) -> bool:
        """Check if blob exists."""
        try:
            blob_client.get_blob_properties()
            return True
        except ResourceNotFoundError:
            return False
    
    
# Factory function for easy instantiation
def create_blob_service(
    container_name: str,
    account_url: Optional[str] = None,
    credential: Optional[Any] = None,
    connection_string: Optional[str] = None,
    create_container: bool = True    
) -> BlobStorageServiceClient:
    """
    Factory function to create a BlobStorageServiceClient instance.

    Args:
        container_name: Container name (required)
        account_url: Azure Storage account URL (optional)
        credential: Azure credential object (optional, defaults to DefaultAzureCredential)
        connection_string: Azure Storage connection string (optional)
        create_container: Whether to create the container if it doesn't exist (default True)
        **kwargs: Additional arguments for BlobStorageServiceClient

    Returns:
        Configured BlobStorageServiceClient instance
    """
    return BlobStorageServiceClient(
        container_name=container_name,
        account_url=account_url,
        credential=credential,
        connection_string=connection_string,
        create_container=create_container        
    )