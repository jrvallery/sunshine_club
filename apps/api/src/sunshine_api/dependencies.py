"""Small dependency factories shared by Sunshine API routers."""

from sunshine_api.review_store import ReviewStore


def review_store() -> ReviewStore:
    return ReviewStore()

