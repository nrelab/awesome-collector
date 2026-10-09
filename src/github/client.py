import time
from typing import Optional

try:
    from httpx_retry import Retries, httpx_retry
    _HAS_RETRY = True
except ImportError:
    _HAS_RETRY = False


class GitHubClient:
    BASE_URL = "https://api.github.com"
    GRAPHQL_URL = "https://api.github.com/graphql"

    def __init__(
        self,
        token: Optional[str] = None,
        requests_per_hour: int = 5000,
        burst_size: int = 30,
        backoff_multiplier: float = 2.0,
        max_backoff_seconds: float = 300.0,
    ):
        import httpx

        self.token = token
        self.requests_per_hour = requests_per_hour
        self.burst_size = burst_size
        self.backoff_multiplier = backoff_multiplier
        self.max_backoff_seconds = max_backoff_seconds

        self._request_timestamps: list[float] = []
        self._last_request_time: float = 0.0

        self._client = httpx.Client(
            base_url=self.BASE_URL,
            headers={
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
                **({"Authorization": f"Bearer {token}"} if token else {}),
            },
            timeout=30.0,
            follow_redirects=True,
        )
        self._async_client = httpx.AsyncClient(
            base_url=self.BASE_URL,
            headers={
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
                **({"Authorization": f"Bearer {token}"} if token else {}),
            },
            timeout=30.0,
            follow_redirects=True,
        )
        self._httpx = httpx

    def _wait_if_needed(self) -> None:
        self._prune_timestamps()
        if len(self._request_timestamps) < self.requests_per_hour:
            self._request_timestamps.append(time.monotonic())
            return
        oldest = self._request_timestamps[0]
        wait_time = 3600 - (time.monotonic() - oldest) + 0.1
        if wait_time > 0:
            time.sleep(min(wait_time, self.max_backoff_seconds))
            self._prune_timestamps()
        self._request_timestamps.append(time.monotonic())

    def _prune_timestamps(self) -> None:
        cutoff = time.monotonic() - 3600
        self._request_timestamps = [t for t in self._request_timestamps if t > cutoff]

    async def _await_if_needed(self) -> None:
        self._prune_timestamps()
        if len(self._request_timestamps) < self.requests_per_hour:
            self._request_timestamps.append(time.monotonic())
            return
        oldest = self._request_timestamps[0]
        wait_time = 3600 - (time.monotonic() - oldest) + 0.1
        if wait_time > 0:
            await self._httpx.sleep(min(wait_time, self.max_backoff_seconds))
            self._prune_timestamps()
        self._request_timestamps.append(time.monotonic())

    def get(self, path: str, **kwargs) -> dict:
        self._wait_if_needed()
        response = self._client.get(path, **kwargs)
        response.raise_for_status()
        return response.json()

    async def aget(self, path: str, **kwargs) -> dict:
        await self._await_if_needed()
        response = await self._async_client.get(path, **kwargs)
        response.raise_for_status()
        return response.json()

    def post(self, path: str, **kwargs) -> dict:
        self._wait_if_needed()
        response = self._client.post(path, **kwargs)
        response.raise_for_status()
        return response.json()

    def search_repositories(self, query: str, per_page: int = 100, page: int = 1) -> dict:
        return self.get(
            "/search/repositories",
            params={"q": query, "per_page": per_page, "page": page},
        )

    def get_repository(self, owner: str, repo: str) -> dict:
        return self.get(f"/repos/{owner}/{repo}")

    async def aget_repository(self, owner: str, repo: str) -> dict:
        return await self.aget(f"/repos/{owner}/{repo}")

    def get_topics(self, owner: str, repo: str) -> list[str]:
        data = self.get(f"/repos/{owner}/{repo}/topics")
        return data.get("names", [])

    def get_readme(self, owner: str, repo: str) -> Optional[dict]:
        try:
            return self.get(f"/repos/{owner}/{repo}/readme")
        except Exception:
            return None

    def get_license(self, owner: str, repo: str) -> Optional[dict]:
        try:
            return self.get(f"/repos/{owner}/{repo}/license")
        except Exception:
            return None

    def get_contributors(self, owner: str, repo: str, per_page: int = 100) -> list[dict]:
        return self.get(
            f"/repos/{owner}/{repo}/contributors",
            params={"per_page": per_page},
        )

    def get_releases(self, owner: str, repo: str, per_page: int = 100) -> list[dict]:
        return self.get(
            f"/repos/{owner}/{repo}/releases",
            params={"per_page": per_page},
        )

    def get_commits(
        self, owner: str, repo: str, since: Optional[str] = None, per_page: int = 100
    ) -> list[dict]:
        params: dict[str, object] = {"per_page": per_page}
        if since:
            params["since"] = since
        return self.get(f"/repos/{owner}/{repo}/commits", params=params)

    def get_rate_limit(self) -> dict:
        return self.get("/rate_limit")

    def close(self) -> None:
        self._client.close()
        self._async_client.aclose()

    async def aclose(self) -> None:
        await self._async_client.aclose()