
import requests


class RepoEnricher:
    def fetch_readme(self, repo_url):
        """Fetch README content from a GitHub/GitLab/Bitbucket repository.
        Supports public repos only.
        """
        if "github.com" in repo_url:
            raw_url = self._github_readme_url(repo_url)
        elif "gitlab.com" in repo_url:
            raw_url = self._gitlab_readme_url(repo_url)
        elif "bitbucket.org" in repo_url:
            raw_url = self._bitbucket_readme_url(repo_url)
        else:
            return None
        try:
            resp = requests.get(raw_url, timeout=5)
            if resp.status_code == 200:
                return resp.text
        except Exception:
            return None
        return None

    def discover_docs_link(self, repo_url):
        """Try to discover documentation link from repo main page or README.
        """
        readme = self.fetch_readme(repo_url)
        if not readme:
            return None
        # Simple heuristic: look for docs URLs in README
        for line in readme.splitlines():
            if "doc" in line.lower() and "http" in line:
                # Extract first URL
                start = line.find("http")
                end = line.find(" ", start)
                url = line[start:end] if end > start else line[start:]
                return url.strip()
        return None

    def _github_readme_url(self, repo_url):
        # Convert https://github.com/org/repo to raw README URL
        parts = repo_url.rstrip("/").split("/")
        if len(parts) < 5:
            return None
        org, repo = parts[3], parts[4]
        return f"https://raw.githubusercontent.com/{org}/{repo}/HEAD/README.md"

    def _gitlab_readme_url(self, repo_url):
        # Convert https://gitlab.com/org/repo to raw README URL
        parts = repo_url.rstrip("/").split("/")
        if len(parts) < 5:
            return None
        org, repo = parts[3], parts[4]
        return f"https://gitlab.com/{org}/{repo}/-/raw/HEAD/README.md"

    def _bitbucket_readme_url(self, repo_url):
        # Convert https://bitbucket.org/org/repo to raw README URL
        parts = repo_url.rstrip("/").split("/")
        if len(parts) < 5:
            return None
        org, repo = parts[3], parts[4]
        return f"https://bitbucket.org/{org}/{repo}/raw/HEAD/README.md"
