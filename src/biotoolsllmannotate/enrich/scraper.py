def extract_homepage(html_content):
    """Extract homepage URL from HTML. Returns None on error or not found."""
    try:
        soup = BeautifulSoup(html_content, "html.parser")
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if "home" in a.get_text().lower():
                return href
    except Exception:
        return None
    return None


def fetch_with_timeout(url, timeout=1.0):
    """Stub: Simulate a timeout error for testing."""
    import time

    time.sleep(timeout * 2)
    raise TimeoutError(f"Timeout fetching {url}")


from urllib.parse import urljoin

from bs4 import BeautifulSoup


def extract_metadata(html_content, base_url):
    """Extract homepage, documentation, and repository links from HTML content."""
    soup = BeautifulSoup(html_content, "html.parser")
    meta = {}
    documentation = []
    repository = None
    for a in soup.find_all("a", href=True):
        href = a["href"]
        text = a.get_text().lower()
        url = urljoin(base_url, href)
        if "doc" in text or "documentation" in text:
            documentation.append(url)
        if "github.com" in href or "gitlab.com" in href or "bitbucket.org" in href:
            repository = url
    if documentation:
        meta["documentation"] = documentation
    if repository:
        meta["repository"] = repository
    return meta
