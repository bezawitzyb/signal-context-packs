"""Actor output -> one plain dict per post/comment, and fixture sanitising.

Field names come from the 2026-10-04 verification (catalog.yaml). Each
mapper returns a RawPost dict that goes straight into make_draft(), where
the author name is hashed and discarded. Nothing here stores or logs it.
"""

from __future__ import annotations

import copy
import re
from datetime import datetime
from typing import Any, Callable, TypedDict

from ctxpack.collect.cleaning import facebook_url, linkedin_url, name_like, redact, scrub_url, x_url


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
    if path in item:  # some actors use flat keys with dots in them ("caption.text")
        return item[path]
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


def reddit_fatihtahta(item: dict, ctx: dict) -> RawPost | None:
    # score and num_comments were 0 on every item in the 2026-10-07 smoke test: engagement unknown, never 0.
    kind = item.get("kind")
    if kind == "comment":
        return RawPost(kind="comment", text=_join(item.get("body")), author=item.get("author"),
                       date=item.get("created_utc"), url=item.get("postUrl") or item.get("url") or "",
                       permalink=item.get("url"), thread_id=item.get("postId"), community=item.get("subreddit"),
                       engagement={})
    if kind == "post":
        return RawPost(kind="post", text=_join(item.get("title"), item.get("body")), author=item.get("author"),
                       date=item.get("created_utc"), url=item.get("url") or "", permalink=item.get("url"),
                       thread_id=item.get("id"), community=item.get("subreddit"), engagement={})
    return None


# --- tiktok -----------------------------------------------------------------

def tiktok_clockworks(item: dict, ctx: dict) -> RawPost | None:
    if not item.get("webVideoUrl"):
        return None
    return RawPost(kind="post", text=_join(item.get("text")), author=get(item, "authorMeta.name"),
                   date=item.get("createTimeISO"), url=item["webVideoUrl"], thread_id=str(item.get("id") or ""),
                   engagement=_eng(item, "diggCount", "commentCount", "shareCount", "playCount"),
                   comments=item.get("commentCount") or 0)


def tiktok_novi(item: dict, ctx: dict) -> RawPost | None:
    video = item.get("aweme_info") or {}
    vid = str(video.get("aweme_id") or "")
    if not vid:
        return None
    return RawPost(kind="post", text=_join(video.get("desc")), author=get(video, "author.unique_id"),
                   date=video.get("create_time"), url=f"https://www.tiktok.com/@/video/{vid}", thread_id=vid,
                   engagement=_eng(video, "statistics.digg_count", "statistics.comment_count",
                                   "statistics.share_count", "statistics.play_count"),
                   comments=get(video, "statistics.comment_count") or 0)


def tiktok_comments_clockworks(item: dict, ctx: dict) -> RawPost | None:
    if not item.get("text"):
        return None
    return RawPost(kind="comment", text=_join(item.get("text")), author=item.get("uniqueId"),
                   date=item.get("createTimeISO"), url=item.get("videoWebUrl") or "", permalink=None,
                   thread_id=item.get("videoWebUrl"), engagement=_eng(item, "diggCount", "replyCommentTotal"))


def tiktok_comments_scrapeforge(item: dict, ctx: dict) -> RawPost | None:
    if not item.get("text"):
        return None
    url = item.get("videoUrl") or ctx.get("parent_by_id", {}).get(str(item.get("videoId")), "")
    return RawPost(kind="comment", text=_join(item.get("text")), author=get(item, "user.uniqueId"),
                   date=item.get("createTimeISO"), url=url, permalink=item.get("commentUrl"), thread_id=url or None,
                   engagement=_eng(item, "diggCount", "replyCount"))


# --- youtube ----------------------------------------------------------------

def youtube_streamers(item: dict, ctx: dict) -> RawPost | None:
    if not item.get("url"):
        return None
    return RawPost(kind="post", text=_join(item.get("title"), item.get("text")), author=item.get("channelName"),
                   date=item.get("date"), url=item["url"], thread_id=item.get("id"),
                   engagement=_eng(item, "likes", "commentsCount", "viewCount"), comments=item.get("commentsCount") or 0)


def youtube_comments_streamers(item: dict, ctx: dict) -> RawPost | None:
    if not item.get("comment"):
        return None
    page, cid = item.get("pageUrl") or "", item.get("cid")
    return RawPost(kind="comment", text=_join(item.get("comment")), author=item.get("author"),
                   date=item.get("publishedTimeText"), url=page,
                   permalink=f"{page}&lc={cid}" if page and cid else None, thread_id=page or None,
                   engagement=_eng(item, "voteCount", "replyCount"))


def youtube_comments_solidcode(item: dict, ctx: dict) -> RawPost | None:
    if not item.get("text") or item.get("recordType", "comment") != "comment" or not item.get("videoId"):
        return None
    page, cid = f"https://www.youtube.com/watch?v={item['videoId']}", item.get("commentId")
    return RawPost(kind="comment", text=_join(item.get("text")), author=item.get("author"),
                   date=item.get("publishedAt") or item.get("publishedAtRaw"), url=page,
                   permalink=f"{page}&lc={cid}" if cid else None, thread_id=page,
                   engagement=_eng(item, "likeCount", "replyCount"))


# --- instagram --------------------------------------------------------------

def instagram_post(item: dict, ctx: dict) -> RawPost | None:
    if not item.get("url") or item.get("error"):
        return None
    return RawPost(kind="post", text=_join(item.get("caption")), author=item.get("ownerUsername"),
                   date=item.get("timestamp"), url=item["url"], thread_id=item.get("shortCode") or item.get("id"),
                   engagement=_eng(item, "likesCount", "commentsCount"), comments=item.get("commentsCount") or 0)


def instagram_post_scrapingsolutions(item: dict, ctx: dict) -> RawPost | None:
    if not item.get("link_post"):
        return None
    return RawPost(kind="post", text=_join(get(item, "caption.text")), author=get(item, "user.username"),
                   date=item.get("taken_at_date"), url=item["link_post"], thread_id=item.get("code"),
                   engagement=_eng(item, "like_count", "comment_count", "play_count"),
                   comments=item.get("comment_count") or 0)


def instagram_comment(item: dict, ctx: dict) -> RawPost | None:
    if not item.get("text") or item.get("error"):
        return None
    return RawPost(kind="comment", text=_join(item.get("text")), author=item.get("ownerUsername"),
                   date=item.get("timestamp"), url=item.get("postUrl") or "", permalink=item.get("commentUrl"),
                   thread_id=item.get("postUrl"), engagement=_eng(item, "likesCount", "repliesCount"))


def instagram_comment_supreme(item: dict, ctx: dict) -> RawPost | None:
    if not item.get("id") or not item.get("commentUrl"):  # a post without comments gives a placeholder row
        return None
    return instagram_comment(item, ctx)


# --- linkedin (V6) -------------------------------------------------------------
# Post links are rebuilt from the activity id: the actors' own links name the author.

def _activity(value: Any) -> str | None:
    digits = "".join(ch for ch in str(value or "").rsplit(":", 1)[-1] if ch.isdigit())
    return digits if len(digits) >= 16 else None


def linkedin_harvest(item: dict, ctx: dict) -> RawPost | None:
    act = _activity(item.get("id") or item.get("entityId"))
    if not act or item.get("type", "post") != "post":
        return None
    return RawPost(kind="post", text=_join(item.get("content")), author=get(item, "author.name"),
                   date=get(item, "postedAt.date"), url=linkedin_url(act), thread_id=act,
                   engagement=_eng(item, "engagement.likes", "engagement.comments", "engagement.shares"),
                   comments=get(item, "engagement.comments") or 0)


def linkedin_datadoping(item: dict, ctx: dict) -> RawPost | None:
    act = _activity(item.get("activity_id"))
    if not act or item.get("is_reshare"):
        return None
    return RawPost(kind="post", text=_join(item.get("text")), author=get(item, "author.name"),
                   date=get(item, "posted_at.date"), url=linkedin_url(act), thread_id=act,
                   engagement=_eng(item, "total_reactions", "comments", "stats.shares"),
                   comments=item.get("comments") or 0)


def linkedin_comment(item: dict, ctx: dict) -> RawPost | None:
    act = _activity(item.get("postId"))
    if not item.get("commentary") or not act:
        return None
    link = item.get("linkedinUrl") or ""
    return RawPost(kind="comment", text=_join(item.get("commentary")), author=get(item, "actor.name"),
                   date=item.get("createdAt"), url=linkedin_url(act),
                   permalink=link if "/feed/update/" in link else None, thread_id=act,
                   engagement=_eng(item, "engagement.likes", "engagement.comments"))


def linkedin_comment_datadoping(item: dict, ctx: dict) -> RawPost | None:
    act = _activity(item.get("input"))  # the post link we asked for (author.profile_url is never read)
    if not item.get("text") or not act:
        return None
    link = item.get("comment_url") or ""
    return RawPost(kind="comment", text=_join(item.get("text")), author=get(item, "author.name"),
                   date=get(item, "posted_at.date"), url=linkedin_url(act),
                   permalink=link if "/feed/update/" in link else None, thread_id=act,
                   engagement=_eng(item, "total_reactions", "total_replies"))


# --- x (2026-10-07) ----------------------------------------------------------------
# Links are rebuilt from the post id: x.com/<handle>/status/<id> names the author.

def _x_date(value: Any) -> Any:
    """'Wed Oct 07 16:01:05 +0000 2026' (X's own format) -> ISO; other forms pass through."""
    if isinstance(value, str) and re.fullmatch(r"\w{3} \w{3} \d{2} \d{2}:\d{2}:\d{2} [+-]\d{4} \d{4}", value):
        return datetime.strptime(value, "%a %b %d %H:%M:%S %z %Y").isoformat()
    return value


def x_xquik(item: dict, ctx: dict) -> RawPost | None:
    pid = str(item.get("id") or "")
    if not pid.isdigit() or not item.get("text") or item.get("isRetweet"):
        return None
    if item.get("rootTweetId") or item.get("sourceTweetId"):  # replies mode
        root = str(item.get("rootTweetId") or item.get("sourceTweetId"))
        return RawPost(kind="comment", text=_join(item.get("text")), author=get(item, "author.username"),
                       date=_x_date(item.get("createdAt")), url=x_url(root), permalink=x_url(pid), thread_id=root,
                       engagement=_eng(item, "likeCount", "replyCount", "retweetCount"))
    return RawPost(kind="post", text=_join(item.get("text")), author=get(item, "author.username"),
                   date=_x_date(item.get("createdAt")), url=x_url(pid), thread_id=str(item.get("conversationId") or pid),
                   engagement=_eng(item, "likeCount", "replyCount", "retweetCount", "quoteCount", "viewCount"),
                   comments=item.get("replyCount") or 0)


def x_scraperone_post(item: dict, ctx: dict) -> RawPost | None:
    pid = str(item.get("postId") or "")
    if not pid.isdigit() or not item.get("postText"):
        return None
    return RawPost(kind="post", text=_join(item.get("postText")), author=get(item, "author.screenName"),
                   date=item.get("timestamp"), url=x_url(pid), thread_id=str(item.get("conversationId") or pid),
                   engagement=_eng(item, "favouriteCount", "replyCount", "repostCount", "quoteCount"),
                   comments=item.get("replyCount") or 0)


def x_scraperone_reply(item: dict, ctx: dict) -> RawPost | None:
    rid, root = str(item.get("replyId") or ""), str(item.get("inReplyTo") or "")
    if not rid.isdigit() or not item.get("replyText"):
        return None
    return RawPost(kind="comment", text=_join(item.get("replyText")), author=get(item, "author.screenName"),
                   date=item.get("timestamp"), url=x_url(root) if root.isdigit() else "", permalink=x_url(rid),
                   thread_id=root or None, engagement=_eng(item, "favouriteCount", "replyCount", "repostCount"))


# --- facebook (2026-10-09) ----------------------------------------------------------
# Links are rebuilt from the post id: the actors' own post and profile links can name people.

_DIGITS = re.compile(r"(\d{8,25})")


def _fb_id(value: Any) -> str:
    """The post id from an id or one of OUR name-free links (facebook.com/<id>); never from a link with a name."""
    text = str(value or "")
    return text if text.isdigit() else (m.group(1) if (m := re.fullmatch(r"https://www\.facebook\.com/(\d{8,25})/?",
                                                                       text)) else "")


def _count(value: Any) -> float | None:
    """Counts arrive as numbers or digit strings ("3")."""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return value
    return int(value) if isinstance(value, str) and value.isdigit() else None


def _counts(**values: Any) -> dict[str, Any]:
    return {k: c for k, v in values.items() if (c := _count(v)) is not None}


def facebook_scrapeforge(item: dict, ctx: dict) -> RawPost | None:
    pid = _fb_id(item.get("post_id"))
    if not pid or not item.get("message") or item.get("type", "post") != "post":
        return None
    return RawPost(kind="post", text=_join(item.get("message")), author=get(item, "author.name"),
                   date=item.get("timestamp"), url=facebook_url(pid), thread_id=pid,
                   community=get(item, "associated_group.name"),
                   engagement=_counts(reactions=item.get("reactions_count"), comments=item.get("comments_count"),
                                      shares=item.get("reshare_count")),
                   comments=_count(item.get("comments_count")) or 0)


def facebook_scraperone(item: dict, ctx: dict) -> RawPost | None:
    pid = _fb_id(item.get("postId"))
    if not pid or not item.get("postText") or item.get("isReshare"):
        return None
    return RawPost(kind="post", text=_join(item.get("postText")), author=get(item, "author.name"),
                   date=item.get("timestamp"), url=facebook_url(pid), thread_id=pid,
                   engagement=_counts(reactions=item.get("reactionsCount"), comments=item.get("commentsCount"),
                                      shares=item.get("sharesCount")),
                   comments=_count(item.get("commentsCount")) or 0)


def facebook_comment_apify(item: dict, ctx: dict) -> RawPost | None:
    pid = _fb_id(item.get("inputUrl")) or _fb_id(item.get("facebookId"))
    cid = str(item.get("commentId") or "")
    if not pid or not item.get("text") or (item.get("threadingDepth") or 0) > 0:
        return None
    return RawPost(kind="comment", text=_join(item.get("text")), author=item.get("profileName"),
                   date=item.get("date"), url=facebook_url(pid),
                   permalink=facebook_url(pid, cid) if cid.isdigit() else None, thread_id=pid,
                   community=item.get("groupTitle"),
                   engagement=_counts(likes=item.get("likesCount"), replies=item.get("commentsCount")))


def facebook_comment_thedoor(item: dict, ctx: dict) -> RawPost | None:
    pid = _fb_id(item.get("post_url"))
    cid = str(item.get("id") or "")
    if not pid or not item.get("text") or item.get("is_reply"):
        return None
    return RawPost(kind="comment", text=_join(item.get("text")), author=item.get("author_name"),
                   date=item.get("comment_time") or item.get("timestamp"), url=facebook_url(pid),
                   permalink=facebook_url(pid, cid) if cid.isdigit() else None, thread_id=pid,
                   engagement=_counts(replies=item.get("replies_count")))


Mapper = Callable[[dict, dict], RawPost | None]

# actor id -> (mapper, fields kept in fixtures, author fields, free-text fields)
MAPPERS: dict[str, tuple[Mapper, list[str], list[str], list[str]]] = {
    "harshmaur/reddit-scraper": (reddit_harshmaur, [
        "dataType", "title", "body", "createdAt", "commentCreatedAt", "postUrl", "url", "id", "postId",
        "parentId", "score", "upVotes", "commentUpVotes", "commentsCount", "authorName", "communityName"],
        ["authorName"], ["title", "body"]),
    "fatihtahta/reddit-scraper-search-fast": (reddit_fatihtahta, [
        "kind", "id", "postId", "title", "body", "created_utc", "url", "postUrl", "subreddit", "author"],
        ["author"], ["title", "body"]),
    "clockworks/tiktok-scraper": (tiktok_clockworks, [
        "text", "createTimeISO", "webVideoUrl", "id", "diggCount", "commentCount", "shareCount", "playCount",
        "authorMeta.name"], ["authorMeta.name"], ["text"]),
    "novi/fast-tiktok-api": (tiktok_novi, [
        "aweme_info.aweme_id", "aweme_info.desc", "aweme_info.create_time", "aweme_info.statistics.digg_count",
        "aweme_info.statistics.comment_count", "aweme_info.statistics.share_count",
        "aweme_info.statistics.play_count", "aweme_info.author.unique_id"],
        ["aweme_info.author.unique_id"], ["aweme_info.desc"]),
    "clockworks/tiktok-comments-scraper": (tiktok_comments_clockworks, [
        "text", "createTimeISO", "videoWebUrl", "cid", "diggCount", "replyCommentTotal", "uniqueId"],
        ["uniqueId"], ["text"]),
    "scrapeforge/tiktok-comments-extractor": (tiktok_comments_scrapeforge, [
        "commentId", "videoId", "videoUrl", "commentUrl", "text", "createTimeISO", "diggCount", "replyCount",
        "user.uniqueId"], ["user.uniqueId"], ["text"]),
    "streamers/youtube-scraper": (youtube_streamers, [
        "title", "text", "date", "url", "id", "likes", "commentsCount", "viewCount", "channelName"],
        ["channelName"], ["title", "text"]),
    "grow_media/youtube-search-api": (youtube_streamers, [   # same field names as the primary
        "title", "text", "date", "url", "id", "likes", "commentsCount", "viewCount", "channelName"],
        ["channelName"], ["title", "text"]),
    "streamers/youtube-comments-scraper": (youtube_comments_streamers, [
        "comment", "publishedTimeText", "pageUrl", "cid", "voteCount", "replyCount", "author"],
        ["author"], ["comment"]),
    "solidcode/youtube-comments-scraper": (youtube_comments_solidcode, [
        "commentId", "videoId", "text", "publishedAt", "publishedAtRaw", "likeCount", "replyCount", "recordType",
        "author"], ["author"], ["text"]),
    "apify/instagram-hashtag-scraper": (instagram_post, [
        "caption", "timestamp", "url", "id", "shortCode", "likesCount", "commentsCount", "ownerUsername", "error"],
        ["ownerUsername"], ["caption"]),
    "scraping_solutions/instagram-hashtag-scraper-pro-no-cookies": (instagram_post_scrapingsolutions, [
        "code", "caption.text", "taken_at_date", "link_post", "like_count", "comment_count", "play_count",
        "user.username"], ["user.username"], ["caption.text"]),
    "apify/instagram-comment-scraper": (instagram_comment, [
        "text", "timestamp", "postUrl", "commentUrl", "id", "likesCount", "repliesCount", "ownerUsername", "error"],
        ["ownerUsername"], ["text"]),
    "supreme_coder/instagram-comments-scraper": (instagram_comment_supreme, [
        "text", "timestamp", "postUrl", "commentUrl", "id", "likesCount", "repliesCount", "ownerUsername"],
        ["ownerUsername"], ["text"]),
    "harvestapi/linkedin-post-search": (linkedin_harvest, [
        "type", "id", "entityId", "content", "postedAt.date", "engagement.likes", "engagement.comments",
        "engagement.shares", "author.name"], ["author.name"], ["content"]),
    "datadoping/linkedin-posts-search-scraper": (linkedin_datadoping, [
        "activity_id", "text", "posted_at.date", "total_reactions", "comments", "stats.shares", "is_reshare",
        "author.name"], ["author.name"], ["text"]),
    "harvestapi/linkedin-post-comments": (linkedin_comment, [
        "id", "postId", "commentary", "createdAt", "linkedinUrl", "engagement.likes", "engagement.comments",
        "actor.name"], ["actor.name"], ["commentary"]),
    "datadoping/linkedin-post-comments-scraper": (linkedin_comment_datadoping, [
        "comment_id", "input", "comment_url", "text", "posted_at.date", "total_reactions", "total_replies",
        "author.name"], ["author.name"], ["text"]),
    "xquik/x-tweet-scraper": (x_xquik, [
        "id", "conversationId", "rootTweetId", "sourceTweetId", "isRetweet", "text", "createdAt", "likeCount",
        "replyCount", "retweetCount", "quoteCount", "viewCount", "lang", "author.username"],
        ["author.username"], ["text"]),
    "scraper_one/x-posts-search": (x_scraperone_post, [
        "postId", "conversationId", "postText", "timestamp", "favouriteCount", "replyCount", "repostCount",
        "quoteCount", "author.screenName"], ["author.screenName"], ["postText"]),
    "scrapeforge/facebook-search-posts": (facebook_scrapeforge, [
        "post_id", "type", "message", "timestamp", "reactions_count", "comments_count", "reshare_count",
        "associated_group.name", "author.name"], ["author.name"], ["message"]),
    "scraper_one/facebook-posts-search": (facebook_scraperone, [
        "postId", "postText", "timestamp", "reactionsCount", "commentsCount", "sharesCount", "isReshare",
        "author.name"], ["author.name"], ["postText"]),
    "apify/facebook-comments-scraper": (facebook_comment_apify, [
        "inputUrl", "facebookId", "commentId", "text", "date", "likesCount", "commentsCount", "threadingDepth",
        "groupTitle", "profileName"], ["profileName"], ["text"]),
    "thedoor/facebook-comment-scraper": (facebook_comment_thedoor, [
        "post_url", "id", "text", "comment_time", "timestamp", "replies_count", "is_reply", "author_name"],
        ["author_name"], ["text"]),
    "scraper_one/x-post-replies-scraper": (x_scraperone_reply, [
        "replyId", "inReplyTo", "replyText", "timestamp", "favouriteCount", "replyCount", "repostCount",
        "author.screenName"], ["author.screenName"], ["replyText"]),
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
    real = name_like([str(v) for item in items for f in author_fields if (v := get(item, f))])
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
                value = redact(value, real)[0]          # authors' own names written in the text, too
            elif isinstance(value, str) and value.startswith("http"):
                value = scrub_url(value)
            _set(clean, path, copy.deepcopy(value))
        out.append(clean)
    return out
