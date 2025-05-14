import time
from threading import Lock
import logging
from typing import Annotated
from pydantic import Field
from decouple import config, Choices
import requests
from codeowners import CodeOwners
from fastmcp import FastMCP

# Read environment variables
GITHUB_TOKEN = config('GITHUB_TOKEN', default=None)
DEBUG = config('DEBUG', default=False, cast=bool)
CACHE_TTL_SECS = config('CACHE_TTL_SECS', default=300, cast=int)
TRANSPORT = config('TRANSPORT', default='stdio', cast=Choices(["stdio", "sse", "streamable-http"]))
HOST = config('HOST', default='127.0.0.1')
PORT = config('PORT', default=8000, cast=int)

# Setup logging
logging.basicConfig(level=logging.DEBUG if DEBUG else logging.INFO)
logger = logging.getLogger(__name__)

class CodeownersCache:
    def __init__(self):
        self.cache = {}
        self.etags = {}
        self.timestamps = {}
        self.lock = Lock()

    def _get_headers(self, etag=None):
        headers = {
            "Accept": "application/vnd.github.v3.raw",
        }
        if GITHUB_TOKEN:
            headers["Authorization"] = f"token {GITHUB_TOKEN}"
        if etag:
            headers["If-None-Match"] = etag
        return headers

    def get_codeowners(self, owner, repo, branch="main"):
        key = f"{owner}/{repo}@{branch}"

        with self.lock:
            now = time.time()
            if (
                key in self.cache and
                (now - self.timestamps.get(key, 0) < CACHE_TTL_SECS)
            ):
                logger.debug(f"Cache hit for {key}")
                return self.cache[key]

            url = f"https://api.github.com/repos/{owner}/{repo}/contents/.github/CODEOWNERS?ref={branch}"
            headers = self._get_headers(etag=self.etags.get(key))
            logger.debug(f"Fetching CODEOWNERS from {url}")

            response = requests.get(url, headers=headers)

            if response.status_code == 304:
                logger.debug("CODEOWNERS not modified (304)")
                self.timestamps[key] = now
                return self.cache[key]
            elif response.status_code == 200:
                content = response.text
                logger.debug("Fetched and cached new CODEOWNERS content")
                self.cache[key] = CodeOwners(content)
                self.etags[key] = response.headers.get("ETag")
                self.timestamps[key] = now
                return self.cache[key]
            else:
                error_msg = f"Failed to fetch CODEOWNERS: {response.status_code} {response.text}"
                logger.error(error_msg)
                raise Exception(error_msg)


# Global CODEOWNERS cache
codeowners_cache = CodeownersCache()
mcp = FastMCP(
    name="github-codeowners",
    instructions="""
        This MCP server expose ownership information for files contained in Github repositories.
        """
)
FastMCP("github-codeowners")
mcp.settings.debug = DEBUG
mcp.settings.host = HOST
mcp.settings.port = PORT

def get_file_exists(
    owner: Annotated[str, Field(description="Repository owner")],
    repo: Annotated[str, Field(description="Repository name")],
    path: Annotated[str, Field(description="File path")],
    branch: Annotated[str, Field(description="Branch name")] = "main"
    ) -> bool:
    """
    Returns if the given file exists
    """
    # No owners, check if the file exists in GitHub
    url = f"https://api.github.com/repos/{owner}/{repo}/contents/{path}?ref={branch}"
    headers = {"Accept": "application/vnd.github.v3+json"}
    if GITHUB_TOKEN:
        headers["Authorization"] = f"token {GITHUB_TOKEN}"

    logger.debug(f"Checking if file exists: {url}")
    response = requests.get(url, headers=headers)

    if response.status_code == 200:
        return True
    elif response.status_code == 404:
        return False
    else:
        error_msg = f"Unexpected error when checking file existence: {response.status_code} {response.text}"
        raise Exception(error_msg)


@mcp.tool()
def get_file_owner(
    owner: Annotated[str, Field(description="Repository owner")],
    repo: Annotated[str, Field(description="Repository name")],
    path: Annotated[str, Field(description="File path")],
    branch: Annotated[str, Field(description="Branch name")] = "main"
) -> list[str]:
    """
    Returns the owners of the specified file in the GitHub repository.
    The owners are derived from the CODEOWNERS file in the repository.
    """
    try:
        codeowners = codeowners_cache.get_codeowners(owner, repo, branch)
        owners = codeowners.of(path)
        logger.debug(f"Owners for {path}: {owners}")

        if owners:
            # owners is a list of tuple Tuple[Literal["USERNAME", "TEAM", "EMAIL"], str]
            # return only the actual owner of the file
            return [o for _, o in owners]

        if not get_file_exists(owner, repo, path, branch):
            raise FileNotFoundError(f"File '{path}' not found in repo '{owner}/{repo}' on branch '{branch}'.")

        return []
    except Exception:
        logger.exception("Failed to get file owner")
        raise

def main():
    mcp.run(transport=TRANSPORT)

if __name__ == "__main__":
    main()
