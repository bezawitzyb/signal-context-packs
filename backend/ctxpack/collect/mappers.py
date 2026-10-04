"""Actor output -> one plain dict per post/comment, and fixture sanitising.

Field names come from the 2026-10-04 verification (catalog.yaml). Each
mapper returns a RawPost dict that goes straight into make_draft(), where
the author name is hashed and discarded. Nothing here stores or logs it.
"""

from __future__ import annotations

import copy
from typing import Any, Callable, TypedDict

from ctxpack.collect.cleaning import redact, scrub_url


class RawPost(TypedDict, total=False):
    kind: str                   # post | comment
    text: str
    author: str | None
    date: Any
    url: str
    permalink: str | None
    thread_id: str | None
    community: str | None
    engagement: dict[str, Any]
    comments: int               # comment count, used to pick posts for chained comments


def get(item: dict, path: str) -> Any:
    cur: Any = item
    for part in path.split("."):
        cur = cur.get(part) if isinstance(cur, dict) else None
    return cur


def _join(*parts: Any) -> str:
    return "\n\n".join(str(p).strip() for p in parts if p and str(p).strip())


def _eng(item: dict, *paths: str) -> dict[str, Any]:
    return {p.split(".")[-1]: v for p in paths if isinstance(v := get(item, p), (int, float)) and not isinstance(v, bool)}


# --- reddit -----------------------------------------------------------------

def reddit_harshmaur(item: dict, ctx: dict) -> RawPost | None:
    if item.get("dataType") == "comment":
        return RawPost(kind="comment", text=_join(item.get("body")), author=item.get("authorName"),
                       date=item.get("commentCreatedAt"), url=item.get("url") or "", permalink=item.get("url"),
                       thread_id=item.get("postId") or item.get("parentId"), community=item.get("communityName"),
                       engagement=_eng(item, "score", "commentUpVotes"))
    if item.get("dataType") == "post":
        return RawPost(kind="post", text=_join(item.get("title"), item.get("body")), author=item.get("authorName"),
                       date=item.get("createdAt"), url=item.get("postUrl") or item.get("url") or "",
                       permalink=item.get("postUrl"), thread_id=item.get("id"), community=item.get("communityName"),
                       engagement=_eng(item, "score", "upVotes", "commentsCount"),
                       comments=item.get("commentsCount") or 0)
    return None


def reddit_trudax(item: dict, ctx: dict) -> RawPost | None:
    kind = item.get("dataType")
    if kind not in ("post", "comment"):
        return None
    return RawPost(kind=kind, text=_join(item.get("title"), item.get("body")), author=item.get("username"),
                   date=item.get("createdAt"), url=item.get("url") or "", permalink=item.get("url"),
                   thread_id=item.get("postId") or item.get("id"), community=item.get("communityName"),
                   engagement=_eng(item, "upVotes", "numberOfComments", "numberOfReplies"),
                   comments=item.get("numberOfComments") or 0)


# --- tiktok -----------------------------------------------------------------

def tiktok_clockworks(item: dict, ctx: dict) -> RawPost | None:
    if not item.get("webVideoUrl"):
        return None
    return RawPost(kind="post", text=_join(item.get("text")), author=get(item, "authorMeta.name"),
                   date=item.get("createTimeISO"), url=item["webVideoUrl"], thread_id=str(item.get("id") or ""),
                   engagement=_eng(item, "diggCount", "commentCount", "shareCount", "playCount"),
                   comments=item.get("commentCount") or 0)


def tiktok_apidojo(item: dict, ctx: dict) -> RawPost | None:
    if not item.get("postPage"):
        return None
    return RawPost(kind="post", text=_join(item.get("title")), author=get(item, "channel.username"),
                   date=item.get("uploadedAt"), url=item["postPage"], thread_id=str(item.get("id") or ""),
                   engagement=_eng(item, "likes", "comments", "shares", "views"), comments=item.get("comments") or 0)


def tiktok_comments_clockworks(item: dict, ctx: dict) -> RawPost | None:
    if not item.get("text"):
        return None
    return RawPost(kind="comment", text=_join(item.get("text")), author=item.get("uniqueId"),
                   date=item.get("createTimeISO"), url=item.get("videoWebUrl") or "", permalink=None,
                   thread_id=item.get("videoWebUrl"), engagement=_eng(item, "diggCount", "replyCommentTotal"))


def tiktok_comments_apidojo(item: dict, ctx: dict) -> RawPost | None:
    if not item.get("text"):
        return None
    url = ctx.get("parent_by_id", {}).get(str(item.get("awemeId")), "")
    return RawPost(kind="comment", text=_join(item.get("text")), author=get(item, "user.username"),
                   date=item.get("createdAt"), url=url, thread_id=url or None,
                   engagement=_eng(item, "likeCount", "replyCount"))


# --- youtube ----------------------------------------------------------------

def youtube_streamers(item: dict, ctx: dict) -> RawPost | None:
    if not item.get("url"):
        return None
    return RawPost(kind="post", text=_join(item.get("title"), item.get("text")), author=item.get("channelName"),
                   date=item.get("date"), url=item["url"], thread_id=item.get("id"),
                   engagement=_eng(item, "likes", "commentsCount", "viewCount"), comments=item.get("commentsCount") or 0)


def youtube_apidojo(item: dict, ctx: dict) -> RawPost | None:
    if not item.get("url"):
        return None
    return RawPost(kind="post", text=_join(item.get("title"), item.get("description")),
                   author=get(item, "channel.name"), date=item.get("uploadDate") or item.get("publishDate"),
                   url=item["url"], thread_id=item.get("id"), engagement=_eng(item, "likes", "views"), comments=1)


def youtube_comments_streamers(item: dict, ctx: dict) -> RawPost | None:
    if not item.get("comment"):
        return None
    page, cid = item.get("pageUrl") or "", item.get("cid")
    return RawPost(kind="comment", text=_join(item.get("comment")), author=item.get("author"),
                   date=item.get("publishedTimeText"), url=page,
                   permalink=f"{page}&lc={cid}" if page and cid else None, thread_id=page or None,
                   engagement=_eng(item, "voteCount", "replyCount"))


def youtube_comments_apidojo(item: dict, ctx: dict) -> RawPost | None:
    if not item.get("text"):
        return None
    parents = ctx.get("parent_urls", [])
    url = parents[0] if len(parents) == 1 else ""  # items carry no video id
    return RawPost(kind="comment", text=_join(item.get("text")), author=get(item, "author.name"),
                   date=item.get("publishedTime"), url=url, thread_id=url or None,
                   engagement=_eng(item, "likeCount", "replyCount"))


# --- instagram --------------------------------------------------------------

def instagram_post(item: dict, ctx: dict) -> RawPost | None:
    if not item.get("url") or item.get("error"):
        return None
    return RawPost(kind="post", text=_join(item.get("caption")), author=item.get("ownerUsername"),
                   date=item.get("timestamp"), url=item["url"], thread_id=item.get("shortCode") or item.get("id"),
                   engagement=_eng(item, "likesCount", "commentsCount"), comments=item.get("commentsCount") or 0)


def instagram_comment(item: dict, ctx: dict) -> RawPost | None:
    if not item.get("text") or item.get("error"):
        return None
    return RawPost(kind="comment", text=_join(item.get("text")), author=item.get("ownerUsername"),
                   date=item.get("timestamp"), url=item.get("postUrl") or "", permalink=item.get("commentUrl"),
                   thread_id=item.get("postUrl"), engagement=_eng(item, "likesCount", "repliesCount"))


Mapper = Callable[[dict, dict], RawPost | None]

# actor id -> (mapper, fields kept in fixtures, author fields, free-text fields)
MAPPERS: dict[str, tuple[Mapper, list[str], list[str], list[str]]] = {
    "harshmaur/reddit-scraper": (reddit_harshmaur, [
        "dataType", "title", "body", "createdAt", "commentCreatedAt", "postUrl", "url", "id", "postId",
        "parentId", "score", "upVotes", "commentUpVotes", "commentsCount", "authorName", "communityName"],
        ["authorName"], ["title", "body"]),
    "trudax/reddit-scraper-lite": (reddit_trudax, [
        "dataType", "title", "body", "createdAt", "url", "id", "postId", "upVotes", "numberOfComments",
        "numberOfReplies", "username", "communityName"], ["username"], ["title", "body"]),
    "clockworks/tiktok-scraper": (tiktok_clockworks, [
        "text", "createTimeISO", "webVideoUrl", "id", "diggCount", "commentCount", "shareCount", "playCount",
        "authorMeta.name"], ["authorMeta.name"], ["text"]),
    "apidojo/tiktok-scraper": (tiktok_apidojo, [
        "title", "uploadedAt", "postPage", "id", "likes", "comments", "shares", "views", "channel.username"],
        ["channel.username"], ["title"]),
    "clockworks/tiktok-comments-scraper": (tiktok_comments_clockworks, [
        "text", "createTimeISO", "videoWebUrl", "cid", "diggCount", "replyCommentTotal", "uniqueId"],
        ["uniqueId"], ["text"]),
    "apidojo/tiktok-comments-scraper": (tiktok_comments_apidojo, [
        "text", "createdAt", "awemeId", "id", "likeCount", "replyCount", "user.username"],
        ["user.username"], ["text"]),
    "streamers/youtube-scraper": (youtube_streamers, [
        "title", "text", "date", "url", "id", "likes", "commentsCount", "viewCount", "channelName"],
        ["channelName"], ["title", "text"]),
    "apidojo/youtube-scraper": (youtube_apidojo, [
        "title", "description", "uploadDate", "publishDate", "url", "id", "likes", "views", "channel.name"],
        ["channel.name"], ["title", "description"]),
    "streamers/youtube-comments-scraper": (youtube_comments_streamers, [
        "comment", "publishedTimeText", "pageUrl", "cid", "voteCount", "replyCount", "author"],
        ["author"], ["comment"]),
    "apidojo/youtube-comments-scraper": (youtube_comments_apidojo, [
        "text", "publishedTime", "id", "likeCount", "replyCount", "author.name"], ["author.name"], ["text"]),
    "apify/instagram-hashtag-scraper": (instagram_post, [
        "caption", "timestamp", "url", "id", "shortCode", "likesCount", "commentsCount", "ownerUsername", "error"],
        ["ownerUsername"], ["caption"]),
    "apify/instagram-scraper": (instagram_post, [
        "caption", "timestamp", "url", "id", "shortCode", "likesCount", "commentsCount", "ownerUsername", "error"],
        ["ownerUsername"], ["caption"]),
    "apify/instagram-comment-scraper": (instagram_comment, [
        "text", "timestamp", "postUrl", "commentUrl", "id", "likesCount", "repliesCount", "ownerUsername", "error"],
        ["ownerUsername"], ["text"]),
}


def map_items(actor_id: str, items: list[dict], ctx: dict | None = None) -> list[RawPost]:
    mapper = MAPPERS[actor_id][0]
    return [p for item in items if (p := mapper(item, ctx or {})) and p.get("text")]


def _set(target: dict, path: str, value: Any) -> None:
    parts = path.split(".")
    for part in parts[:-1]:
        target = target.setdefault(part, {})
    target[parts[-1]] = value


def sanitize_for_fixture(actor_id: str, items: list[dict]) -> list[dict]:
    """Make real actor output safe for a PUBLIC repo before it is saved.

    Keeps only the fields the mapper reads, replaces every author with a
    stable pseudonym (user_1, user_2, ...), redacts free text and removes
    handles from URLs. No real name, email or phone ever reaches git.
    """
    _, fields, author_fields, text_fields = MAPPERS[actor_id]
    names: dict[str, str] = {}
    out = []
    for item in items:
        clean: dict = {}
        for path in fields:
            value = get(item, path)
            if value is None:
                continue
            if path in author_fields:
                value = names.setdefault(str(value), f"user_{len(names) + 1}")
            elif path in text_fields and isinstance(value, str):
                value = redact(value)[0]
            elif isinstance(value, str) and value.startswith("http"):
                value = scrub_url(value)
            _set(clean, path, copy.deepcopy(value))
        out.append(clean)
    return out
