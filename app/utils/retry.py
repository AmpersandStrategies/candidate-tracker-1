"""Retry utilities with exponential backoff"""
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
import httpx
import asyncio


def http_retry():
    """Retry decorator for HTTP requests"""
    return retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=4, max=10),
        retry=retry_if_exception_type((httpx.HTTPError, asyncio.TimeoutError))
    )


def api_retry():
    """Retry decorator for API calls"""
    return retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=8),
        retry=retry_if_exception_type((Exception,))
    )


def scrape_retry():
    """Retry decorator for scraping operations"""
    return retry(
        stop=stop_after_attempt(2),
        wait=wait_exponential(multiplier=2, min=4, max=16),
        retry=retry_if_exception_type((Exception,))
    )
