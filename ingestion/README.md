# Bing Grounding & News Search API

## Description

This FastAPI application provides search endpoints that leverage:

* **Azure AI Project Client and Bing Grounding** for web search and AI agent responses.
* **NewsAPI.org** for retrieving news articles from hundreds of sources.
* **Azure Blob Storage** for storing extracted article content.

The app supports:

* Initializing an AI agent with Bing Grounding, managing threads and messages, and extracting article contents.
* Searching for recent and relevant news headlines and stories using NewsAPI.
* **Uploading extracted article content to Azure Blob Storage** for persistent storage and later retrieval.

---

## Features

* **Bing Search Endpoint:** Accepts a query string and returns search results using Bing Grounding and Azure AI integration.
* **News API Endpoint:** Accepts a query and returns news articles from NewsAPI.
* **Automatic Article Extraction:** Scrapes main article content from URLs returned by Bing or NewsAPI (using `newspaper3k`).
* **Azure Blob Storage Integration:** Extracted article content is uploaded to Azure Blob Storage, with metadata for each article.
* **Swagger Docs:** Automatic OpenAPI docs available at `/docs`.

---

## Prerequisites

* Python 3.12
* [Azure subscription](https://portal.azure.com/)
* Azure AI Agent configured with Bing Grounding enabled
  * [AI Agent Quickstart](https://learn.microsoft.com/en-us/azure/ai-services/agents/quickstart?pivots=ai-foundry-portal)
  * [Bing Grounding documentation](https://learn.microsoft.com/en-us/azure/ai-services/agents/how-to/tools/bing-grounding)  
* [NewsAPI account](https://newsapi.org/) (free tier is sufficient)
* **Azure Blob Storage account** (for storing article content)
* Environment variables:
  * `AI_FOUNDRY_PROJECT_ENDPOINT`: Azure AI Project connection string
  * `BING_CONNECTION_NAME`: Name of Bing connection in Azure AI Project
  * `NEWS_API_KEY`: API key from NewsAPI.org
  * `BLOB_ACCOUNT_URL`: Azure Blob Storage account URL (e.g., `https://<account>.blob.core.windows.net/`)
  * `BLOB_STORAGE_CONTAINER_NAME`: Name of the blob container to use
  * `BLOB_STORAGE_CONNECTION_STRING`: (optional) Azure Storage connection string

---

## Installation

1. **Clone the repository:**

   ```bash
   git clone <repository_url>
   cd <repository_directory>
   ```

2. **Install dependencies with Poetry:**

   If you don't have Poetry installed, install it first:
   ```bash
   pip install poetry
   ```

   Then install project dependencies:
   ```bash
   poetry install   

3. **Set required environment variables:**

   For Azure/Bing endpoints:

   ```bash
   export AI_FOUNDRY_PROJECT_ENDPOINT="<your_project_connection_string>"
   export BING_CONNECTION_NAME="<your_bing_connection_name>"
   ```

   For NewsAPI:

   ```bash
   export NEWS_API_KEY="<your_newsapi_key>"
   ```

   For Azure Blob Storage:

   ```bash
   export BLOB_ACCOUNT_URL="<your_blob_account_url>"
   export BLOB_STORAGE_CONTAINER_NAME="<your_container_name>"
   # Optionally, if using a connection string:
   export BLOB_STORAGE_CONNECTION_STRING="<your_blob_connection_string>"
   ```

   Optionally, use a `.env` file in your project root (see [dotenv documentation](https://pypi.org/project/python-dotenv/)):

   AI_FOUNDRY_PROJECT_ENDPOINT=...
   BING_CONNECTION_NAME=...
   NEWS_API_KEY=...
   BLOB_ACCOUNT_URL=...
   BLOB_STORAGE_CONTAINER_NAME=...
   BLOB_STORAGE_CONNECTION_STRING=...
   ```

---

## Usage

1. **Run the FastAPI application:**

   ```bash
   uvicorn main:app --reload
   ```

2. **Available Endpoints:**

   * `http://localhost:8000/bingsearch?query=<your_search_query>`
   * `http://localhost:8000/newsapi?query=<your_news_query>&language=en`

3. **Swagger Documentation:**

   ```
   http://localhost:8000/docs
   ```

   > **Note:** This is a proof-of-concept and performance is not optimized.  

---

## API Endpoints

### `/bingsearch`

* **Summary:** Search Endpoint using Bing Grounding
* **Description:** Accepts a query string and returns search results via Azure AI agent.
* **Method:** GET
* **Query Parameters:**

  * `query` (string, required): The search query.
* **Returns:**

  * `dict`: Search results, annotations, and extracted article content.

---

### `/newsapi`

* **Summary:** News API Search Endpoint
* **Description:** Searches for news articles using [NewsAPI.org](https://newsapi.org/).
* **Method:** GET
* **Query Parameters:** (all optional except `query`)

  * `query` (string, required): Search keywords or phrases.
  * `searchIn`: Restrict search to `title`, `description`, `content` (comma-separated).
  * `sources`: News source identifiers (comma-separated, max 20).
  * `domains`: Restrict to domains (comma-separated).
  * `excludeDomains`: Exclude these domains (comma-separated).
  * `from`: Oldest article date (ISO8601, e.g. `2025-05-29`).
  * `to`: Newest article date.
  * `language`: 2-letter code (default: `en`).
  * `sortBy`: `relevancy`, `popularity`, or `publishedAt` (default: `publishedAt`).
  * `pageSize`: Results per page (1–100, default 100).
  * `page`: Page number (default 1).
* **Returns:**

  * `dict`: NewsAPI search results, including URLs and main article text where possible.
  * **Note:** Extracted article content is uploaded to Azure Blob Storage, and metadata (such as article URL and title) is stored with each blob.

**Example:**

```http
GET /newsapi?query=openai&language=en
```

---

## Example Request

### Bing Search

```http
GET http://localhost:8000/bingsearch?query=wisconsin%20election
```

### News API

```http
GET http://localhost:8000/newsapi?query=artificial%20intelligence&language=en
```

---

## Example Response

<details>
<summary>Bing Search Example</summary>

```json
{
  "response": {
    "type": "text",
    "text": {
      "value": "...",
      "annotations": [
        {
          "type": "url_citation",
          "url_citation": {
            "url": "https://www.example.com/article",
            "title": "Some news headline"
          }
        }
      ]
    }
  }
}
```

</details>

<details>
<summary>News API Example</summary>

```json
{
  "status": "ok",
  "totalResults": 2,
  "articles": [
    {
      "source": {"id": null, "name": "TechCrunch"},
      "author": "Jane Doe",
      "title": "AI breakthrough announced",
      "description": "...",
      "url": "https://techcrunch.com/example-article",
      "publishedAt": "2025-05-29T10:00:00Z",
      "content": "..."
    }
  ]
}
```

</details>

---

## Azure Blob Storage Integration

When articles are extracted from Bing or NewsAPI results, their main content is **uploaded to Azure Blob Storage**. Each blob is named uniquely and includes metadata such as the article URL and title. This allows for persistent storage and later retrieval of article content.

**Blob Storage Setup:**
- Ensure you have created a blob container in your Azure Storage account.
- Set the required environment variables (`BLOB_ACCOUNT_URL`, `BLOB_STORAGE_CONTAINER_NAME`, and optionally `BLOB_STORAGE_CONNECTION_STRING`).
- The application will automatically upload extracted article text to this container.

---

## Error Handling

The application logs errors and returns structured error responses for issues during the search process.

---

## Cleanup

For Bing agent searches, the application deletes the created agent and thread after each search to clean up resources.

---

## Contributing

Contributions are welcome! Please submit a pull request with your proposed changes.

---

## License

[MIT](LICENSE)

---

### Need a NewsAPI key?

1. Register at [https://newsapi.org/register](https://newsapi.org/register)
2. Copy your API key from your account dashboard.
3. Set `NEWS_API_KEY` as an environment variable or in your `.env` file.

---