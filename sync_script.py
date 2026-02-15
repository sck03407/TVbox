import asyncio
import json
import logging
import os
import sys
import re
from pathlib import Path
from typing import Optional, List, Dict, Any, Union, Tuple

import aiofiles
import aiohttp
import chardet

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

CONFIG_FILE = Path("config.json")
DEFAULT_TIMEOUT = 30
MAX_RETRIES = 3
MAX_CONCURRENT_REQUESTS = 5  # Limit concurrency to avoid rate limits

async def load_config(file_path: Path) -> Optional[Dict[str, Any]]:
    """Load and parse the configuration file asynchronously."""
    if not file_path.exists():
        logger.error(f"Config file {file_path} not found.")
        return None

    try:
        # Use utf-8-sig to handle BOM if present (common in Windows edited files)
        async with aiofiles.open(file_path, mode="r", encoding="utf-8-sig") as f:
            content = await f.read()
            return json.loads(content)
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse config file {file_path}: {e}")
        return None
    except Exception as e:
        logger.error(f"Unexpected error loading config: {e}")
        return None

def clean_github_url(url: str) -> str:
    """Clean and correct common GitHub URL issues."""
    # Handle 'blob' URLs -> 'raw'
    # Pattern: github.com/user/repo/blob/branch/path -> raw.githubusercontent.com/user/repo/branch/path
    if "github.com" in url and "/blob/" in url:
        url = url.replace("github.com", "raw.githubusercontent.com").replace("/blob/", "/")
    
    # Handle 'refs/heads/' in raw URLs which often cause 404
    # Pattern: .../refs/heads/master/... -> .../master/...
    if "raw.githubusercontent.com" in url and "/refs/heads/" in url:
        url = url.replace("/refs/heads/", "/")
        
    return url

async def fetch_content(session: aiohttp.ClientSession, url: str) -> Optional[bytes]:
    """Fetch content from a URL with retries, returning raw bytes."""
    for attempt in range(MAX_RETRIES):
        try:
            async with session.get(url, timeout=DEFAULT_TIMEOUT) as response:
                if response.status == 404:
                    # If 404, return None immediately to allow upper layer to handle (e.g., try corrected URL)
                    return None
                response.raise_for_status()
                return await response.read()
        except (aiohttp.ClientError, asyncio.TimeoutError) as e:
            if attempt == MAX_RETRIES - 1:
                logger.error(f"Failed to fetch {url} after {MAX_RETRIES} attempts: {e}")
                return None
            logger.warning(f"Attempt {attempt + 1} failed for {url}: {e}. Retrying...")
            await asyncio.sleep(1 * (attempt + 1))  # Exponential backoff
    return None

async def read_local_file(path: Path) -> Optional[bytes]:
    """Read content from a local file asynchronously as bytes."""
    if not path.exists():
        return None
    try:
        async with aiofiles.open(path, mode="rb") as f:
            return await f.read()
    except OSError as e:
        logger.warning(f"Failed to read local file {path}: {e}")
        return None

async def write_local_file(path: Path, content: bytes) -> bool:
    """Write content to a local file asynchronously."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        async with aiofiles.open(path, mode="wb") as f:
            await f.write(content)
        return True
    except OSError as e:
        logger.error(f"Failed to write to {path}: {e}")
        return False

def is_text_content(content: bytes) -> bool:
    """Check if content is text-based."""
    # Fast check for null bytes, common in binary files
    if b'\x00' in content:
        return False
        
    try:
        content.decode('utf-8')
        return True
    except UnicodeDecodeError:
        # Try to detect other encodings
        detection = chardet.detect(content[:1024]) # Check first 1KB
        if detection['encoding'] and detection['confidence'] > 0.7:
             return True
        return False

def validate_json_content(content: bytes) -> bool:
    """Validate if content is valid JSON."""
    try:
        text = content.decode('utf-8')
        json.loads(text)
        return True
    except (UnicodeDecodeError, json.JSONDecodeError):
        # Try detecting encoding if utf-8 fails
        try:
            detection = chardet.detect(content)
            if detection['encoding']:
                text = content.decode(detection['encoding'])
                json.loads(text)
                return True
        except Exception:
            pass
        return False

def normalize_newlines(content: bytes) -> bytes:
    """Normalize newlines in text content to LF."""
    try:
        text = content.decode('utf-8')
        return text.replace('\r\n', '\n').encode('utf-8')
    except UnicodeDecodeError:
        # If utf-8 fails, try to detect encoding
        detection = chardet.detect(content)
        encoding = detection['encoding']
        if encoding:
            try:
                text = content.decode(encoding)
                return text.replace('\r\n', '\n').encode('utf-8') # Normalize to UTF-8 LF
            except Exception:
                return content # Fallback to original bytes
        return content

async def process_file(session: aiohttp.ClientSession, semaphore: asyncio.Semaphore, item: Dict[str, str]) -> Tuple[bool, bool]:
    """
    Process a single file sync task with concurrency limit.
    Returns: (success, updated)
    """
    async with semaphore:
        remote_url = item.get("remote_url")
        local_path_str = item.get("local_path")

        if not remote_url or not local_path_str:
            logger.warning(f"Skipping invalid item: {item}")
            return False, False

        # Remove leading slashes to prevent absolute path issues
        local_path_str = local_path_str.lstrip("/").lstrip("\\")
        local_path = Path(local_path_str)
        
        # Security check: Prevent path traversal
        try:
            # Simple check for '..' components in the path parts
            if ".." in local_path.parts:
                 logger.warning(f"Suspicious path detected: {local_path}. Skipping.")
                 return False, False
        except Exception as e:
            logger.error(f"Invalid path {local_path}: {e}")
            return False, False

        logger.info(f"Checking {local_path}...")

        # 1. Try fetching original URL
        remote_content = await fetch_content(session, remote_url)
        
        # 2. If failed, try cleaning URL (e.g. fix blob -> raw, remove refs/heads/)
        if remote_content is None:
            cleaned_url = clean_github_url(remote_url)
            if cleaned_url != remote_url:
                logger.warning(f"Original URL failed. Retrying with corrected URL: {cleaned_url}")
                remote_content = await fetch_content(session, cleaned_url)
        
        if remote_content is None:
            logger.error(f"Failed to fetch content for {local_path} (checked: {remote_url})")
            return False, False

        # 3. Validate content type if needed (e.g. ensure JSON is valid)
        if local_path.suffix.lower() == '.json':
            if not validate_json_content(remote_content):
                logger.error(f"Downloaded content for {local_path} is NOT valid JSON. Skipping update to prevent corruption.")
                return False, False

        local_content = await read_local_file(local_path)

        # Compare content
        content_changed = False
        
        if local_content is None:
            # File doesn't exist, create it
            logger.info(f"File {local_path} does not exist. Creating it.")
            content_changed = True
        else:
            # If both seem to be text, normalize newlines before comparing
            if is_text_content(remote_content) and is_text_content(local_content):
                remote_normalized = normalize_newlines(remote_content)
                local_normalized = normalize_newlines(local_content)
                if remote_normalized != local_normalized:
                    content_changed = True
            else:
                # Binary comparison
                if remote_content != local_content:
                    content_changed = True

        if content_changed:
            logger.info(f"Content changed or new file for {local_path}. Updating...")
            if await write_local_file(local_path, remote_content):
                logger.info(f"Successfully updated {local_path}")
                return True, True
            else:
                return False, False
        else:
            logger.info(f"No changes detected for {local_path}")
            return True, False

async def sync_files():
    """Main synchronization logic."""
    config = await load_config(CONFIG_FILE)
    if not config:
        sys.exit(1)

    files = config.get("files", [])
    if not files:
        logger.warning("No files to sync found in config.")
        return

    # Use a custom user agent to avoid being blocked
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
    }
    
    # Check for GitHub Token for private repos or higher rate limits
    token = os.environ.get("GH_TOKEN")
    if token and token.strip():
        headers["Authorization"] = f"token {token.strip()}"

    semaphore = asyncio.Semaphore(MAX_CONCURRENT_REQUESTS)

    logger.info(f"Starting sync for {len(files)} files...")

    async with aiohttp.ClientSession(headers=headers) as session:
        tasks = [process_file(session, semaphore, item) for item in files]
        results = await asyncio.gather(*tasks)

    # Calculate statistics
    total = len(files)
    success_count = sum(1 for success, _ in results if success)
    updated_count = sum(1 for _, updated in results if updated)
    failed_count = total - success_count

    logger.info("-" * 40)
    logger.info(f"Sync Summary:")
    logger.info(f"Total Files: {total}")
    logger.info(f"Successful Checks: {success_count}")
    logger.info(f"Updated Files: {updated_count}")
    logger.info(f"Failed Files: {failed_count}")
    logger.info("-" * 40)

    if failed_count > 0:
        logger.warning("Some files failed to sync. Check logs for details.")
        # Optional: exit with non-zero code if you want the workflow to fail
        # sys.exit(1) 

if __name__ == "__main__":
    # Windows-specific event loop policy for asyncio
    if sys.platform == 'win32':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
        
    try:
        asyncio.run(sync_files())
    except KeyboardInterrupt:
        logger.info("Sync interrupted by user.")
    except Exception as e:
        logger.critical(f"Unexpected error in main loop: {e}", exc_info=True)
        sys.exit(1)
