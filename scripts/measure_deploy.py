"""Human-run, no-LLM post-deploy latency measurement using a disposable account."""

import argparse
import http.cookiejar
import statistics
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from urllib.parse import urlsplit
from urllib.request import HTTPCookieProcessor, Request, build_opener


def measure(origin: str) -> dict[str, float]:
    parsed = urlsplit(origin)
    if (
        parsed.scheme != "https"
        or not parsed.netloc
        or parsed.username
        or parsed.password
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("Supply only the public HTTPS frontend origin")
    origin = origin.rstrip("/")
    cookies = http.cookiejar.CookieJar()
    client = build_opener(HTTPCookieProcessor(cookies))

    def call(path: str, method: str = "GET") -> float:
        started = perf_counter()
        with client.open(Request(origin + path, method=method), timeout=180) as response:
            if response.status != 200:
                raise RuntimeError("Deployment measurement request failed")
            response.read()  # Never print or persist response content/cookies.
        return (perf_counter() - started) * 1000

    try:
        call("/health")
        call("/api/tracking")  # Warm both layers; exclude cold samples.
        samples: dict[str, list[float]] = {"/health": [], "/api/tracking": []}
        for _ in range(9):
            for endpoint, values in samples.items():
                values.append(call(endpoint))
        return {key: round(statistics.median(values), 2) for key, values in samples.items()}
    finally:
        if any(cookie.name == "nof1_uid" for cookie in cookies):
            call("/api/me", "DELETE")
        cookies.clear()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("origin")
    args = parser.parse_args()
    result = measure(args.origin)
    line = (
        f"Measured {datetime.now(UTC).isoformat()} from the invoking client, "
        f"9 warm samples each: /health median **{result['/health']} ms**; "
        f"/api/tracking median **{result['/api/tracking']} ms**. "
        "Disposable account deleted; no LLM calls."
    )
    path = Path(__file__).resolve().parents[1] / "DEPLOY.md"
    source = path.read_text(encoding="utf-8")
    start, end = "<!-- latency:start -->", "<!-- latency:end -->"
    before, rest = source.split(start, 1)
    _, after = rest.split(end, 1)
    path.write_text(before + start + "\n" + line + "\n" + end + after, encoding="utf-8")
    print(line)


if __name__ == "__main__":
    main()
