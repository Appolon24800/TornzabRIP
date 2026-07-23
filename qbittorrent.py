from __future__ import annotations

import asyncio
import base64
import hashlib
import logging
import os
from typing import Optional
from urllib.parse import urlparse, parse_qs

from fastapi import APIRouter, Form, Query, Request, Response
from fastapi.responses import PlainTextResponse

from job_store import store, DownloadJob, JobState
from streamrip_api import streamrip
from torznab import decode_guid, encode_guid, info_hash
from config import DOWNLOAD_TARGET_DIR, DEFAULT_PORT

logger = logging.getLogger("torznabrip.qbittorrent")

router = APIRouter(prefix="/api/v2", tags=["qbittorrent"])


@router.post("/auth/login")
async def auth_login(
    username: str = Form(default=""),
    password: str = Form(default=""),
):
    logger.info("qBit login: username=%r (accepted)", username)
    return Response(content="Ok.")


@router.get("/app/version")
async def app_version():
    return PlainTextResponse("5.0.0")


@router.get("/app/webapiVersion")
async def web_api_version():
    return PlainTextResponse("2.9.0")


@router.get("/app/preferences")
async def app_preferences():
    return {
        "add_stopped_enabled": False,
        "add_to_top_of_queue": False,
        "announce_to_all_tiers": True,
        "announce_to_all_trackers": False,
        "anonymous_mode": False,
        "auto_delete_mode": 0,
        "auto_tmm_enabled": True,
        "bdecode_depth_limit": 100,
        "bdecode_token_limit": 10_000_000,
        "bittorrent_protocol": 0,
        "bypass_auth_subnet_whitelist": "127.0.0.1/32",
        "bypass_auth_subnet_whitelist_enabled": True,
        "bypass_local_auth": True,
        "checking_memory_use": 32,
        "confirm_torrent_deletion": True,
        "connection_speed": 30,
        "dht": True,
        "disk_cache": -1,
        "disk_cache_ttl": 60,
        "disk_io_read_mode": 1,
        "disk_io_type": 0,
        "disk_io_write_mode": 1,
        "disk_queue_size": 1_073_741_824,
        "dl_limit": 0,
        "dont_count_slow_torrents": True,
        "enable_coalesce_read_write": False,
        "enable_embedded_tracker": False,
        "enable_multi_connections_from_same_ip": False,
        "enable_piece_extent_affinity": False,
        "enable_upload_suggestions": False,
        "encryption": 0,
        "excluded_file_names": "",
        "excluded_file_names_enabled": False,
        "export_dir": "",
        "export_dir_fin": "",
        "file_pool_size": 500,
        "hashing_threads": 2,
        "idn_support_enabled": False,
        "incomplete_files_ext": False,
        "ip_filter_enabled": False,
        "ip_filter_path": "",
        "ip_filter_trackers": False,
        "limit_lan_peers": False,
        "limit_tcp_overhead": False,
        "limit_utp_rate": False,
        "listen_port": 51413,
        "locale": "en",
        "lsd": True,
        "mail_notification_auth_enabled": True,
        "mail_notification_email": "",
        "mail_notification_enabled": False,
        "mail_notification_sender": "qBittorrent_notification@example.com",
        "mail_notification_smtp": "",
        "mail_notification_ssl_enabled": False,
        "max_active_checking_torrents": 30,
        "max_active_downloads": 10,
        "max_active_torrents": 210,
        "max_active_uploads": 200,
        "max_concurrent_http_announces": 50,
        "max_connec": -1,
        "max_connec_per_torrent": -1,
        "max_inactive_seeding_time": -1,
        "max_inactive_seeding_time_enabled": False,
        "max_ratio": -1,
        "max_ratio_act": 0,
        "max_ratio_enabled": False,
        "max_seeding_time": -1,
        "max_seeding_time_enabled": False,
        "max_uploads": -1,
        "max_uploads_per_torrent": -1,
        "memory_working_set_limit": 512,
        "merge_trackers": False,
        "outgoing_ports_max": 0,
        "outgoing_ports_min": 0,
        "peer_tos": 1,
        "peer_turnover": 4,
        "peer_turnover_cutoff": 90,
        "peer_turnover_interval": 300,
        "performance_warning": True,
        "pex": True,
        "preallocate_all": False,
        "proxy_auth_enabled": False,
        "proxy_bittorrent": True,
        "proxy_hostname_lookup": False,
        "proxy_ip": "",
        "proxy_misc": True,
        "proxy_password": "",
        "proxy_peer_connections": False,
        "proxy_port": 8080,
        "proxy_rss": True,
        "proxy_type": "None",
        "proxy_username": "",
        "python_executable_path": "",
        "queueing_enabled": False,
        "random_port": False,
        "reannounce_when_address_changed": False,
        "recheck_completed_torrents": False,
        "refresh_interval": 1500,
        "request_queue_size": 500,
        "resolve_peer_countries": True,
        "resolve_peer_host_names": False,
        "resume_data_storage_type": "SQLite",
        "rss_auto_downloading_enabled": False,
        "rss_download_repack_proper_episodes": True,
        "rss_fetch_delay": 2,
        "rss_max_articles_per_feed": 50,
        "rss_processing_enabled": False,
        "rss_refresh_interval": 30,
        "rss_smart_episode_filters": "s(\\d+)e(\\d+)\n(\\d+)x(\\d+)\n(\\d{4}[.\\-]\\d{1,2}[.\\-]\\d{1,2})\n(\\d{1,2}[.\\-]\\d{1,2}[.\\-]\\d{4})",
        "save_path": DOWNLOAD_TARGET_DIR,
        "save_path_changed_tmm_enabled": False,
        "save_resume_data_interval": 60,
        "save_statistics_interval": 15,
        "scan_dirs": {},
        "schedule_from_hour": 8,
        "schedule_from_min": 0,
        "schedule_to_hour": 20,
        "schedule_to_min": 0,
        "scheduler_days": 0,
        "scheduler_enabled": False,
        "send_buffer_low_watermark": 10,
        "send_buffer_watermark": 500,
        "send_buffer_watermark_factor": 50,
        "slow_torrent_dl_rate_threshold": 20,
        "slow_torrent_inactive_timer": 60,
        "slow_torrent_ul_rate_threshold": 20,
        "socket_backlog_size": 30,
        "socket_receive_buffer_size": 0,
        "socket_send_buffer_size": 0,
        "ssrf_mitigation": True,
        "stop_tracker_timeout": 2,
        "temp_path": DOWNLOAD_TARGET_DIR,
        "temp_path_enabled": False,
        "torrent_changed_tmm_enabled": True,
        "torrent_content_layout": "Original",
        "torrent_content_remove_option": "Delete",
        "torrent_file_size_limit": 104_857_600,
        "torrent_stop_condition": "None",
        "up_limit": 0,
        "upload_choking_algorithm": 1,
        "upload_slots_behavior": 0,
        "upnp": False,
        "upnp_lease_duration": 0,
        "use_category_paths_in_manual_mode": False,
        "use_https": False,
        "use_unwanted_folder": False,
        "utp_tcp_mixed_mode": 0,
        "validate_https_tracker_certificate": True,
        "web_ui_address": "*",
        "web_ui_ban_duration": 3600,
        "web_ui_clickjacking_protection_enabled": True,
        "web_ui_csrf_protection_enabled": False,
        "web_ui_custom_http_headers": "",
        "web_ui_domain_list": "*",
        "web_ui_host_header_validation_enabled": False,
        "web_ui_https_cert_path": "",
        "web_ui_https_key_path": "",
        "web_ui_max_auth_fail_count": 5,
        "web_ui_port": DEFAULT_PORT,
        "web_ui_reverse_proxies_list": "",
        "web_ui_reverse_proxy_enabled": False,
        "web_ui_secure_cookie_enabled": True,
        "web_ui_session_timeout": 3600,
        "web_ui_upnp": False,
        "web_ui_use_custom_http_headers_enabled": False,
        "web_ui_username": "",
    }


@router.get("/torrents/info")
async def torrents_info(
    hashes: str = "",
    filter: str = "all",
    category: str = "",
    sort: str = "",
    reverse: bool = False,
    limit: int = 0,
    offset: int = 0,
):
    jobs = store.list_all()

    hash_set: set[str] = set()
    if hashes:
        hash_set = {h.strip() for h in hashes.split("|") if h.strip()}

    filtered = jobs
    if hash_set:
        filtered = [j for j in jobs if j.hash in hash_set]

    if filter and filter != "all":
        state_map = {
            "downloading": [JobState.DOWNLOADING],
            "completed": [JobState.COMPLETED],
            "active": [JobState.DOWNLOADING],
            "paused": [JobState.COMPLETED],
            "inactive": [JobState.COMPLETED],
            "errored": [JobState.FAILED],
        }
        allowed = set(state_map.get(filter, []))
        if allowed:
            filtered = [j for j in filtered if j.state in allowed]

    filtered.sort(key=lambda x: x.name)

    if offset:
        filtered = filtered[offset:]
    if limit:
        filtered = filtered[:limit]

    result = []
    for job in filtered:
        result.append({
            "hash": job.hash,
            "name": job.name,
            "state": job.state.value,
            "progress": job.progress,
            "size": job.size,
            "downloaded": job.downloaded,
            "save_path": job.save_path,
            "category": "",
            "tags": "",
            "added_on": 1700000000,
            "completion_on": 1700000000 if job.is_finished else 0,
            "tracker": "",
            "ratio": 1.0 if job.is_finished else 0.0,
            "uploaded": 0,
            "dlspeed": 0,
            "upspeed": 0,
            "eta": 8640000,
            "num_seeds": 0,
            "num_leechs": 0,
            "priority": 0,
            "auto_tmm": False,
            "seq_dl": False,
            "f_l_piece_prio": False,
            "force_start": False,
            "is_waiting": False,
            "time_active": 0,
            "total_size": job.size,
            "amount_left": max(0, job.size - job.downloaded),
            "magnet_uri": f"magnet:?xt=urn:btih:{job.hash}&dn={job.name}",
        })

    return result


def _extract_guid_from_url(url: str) -> Optional[str]:
    try:
        if url.startswith("magnet:"):
            qs = parse_qs(urlparse(url).query)
            raw = qs.get("dn", [None])[0]
            if raw:
                return raw
        else:
            qs = parse_qs(urlparse(url).query)
            return qs.get("id", [None])[0]
    except Exception:
        return None


def _extract_guid_from_torrent(data: str) -> Optional[str]:
    try:
        raw = base64.b64decode(data)
    except Exception:
        return None

    idx = raw.find(b"7:comment")
    if idx == -1:
        logger.debug("No comment field found in torrent")
        return None

    rest = raw[idx + len(b"7:comment"):]
    try:
        colon = rest.index(b":")
        length = int(rest[:colon])
        start = colon + 1
        comment = rest[start:start + length]
    except (ValueError, IndexError) as exc:
        logger.debug("Failed to parse comment string: %s", exc)
        return None

    comment_str = comment.decode(errors="ignore")
    logger.debug("Extracted comment from torrent: %s", comment_str)

    if comment_str.startswith("guid:"):
        return comment_str[5:]
    return comment_str


@router.get("/torrents/files")
async def torrents_files(hash: str = ""):
    job = store.get(hash)
    name = job.name if job else "unknown"
    return [
        {
            "name": name,
            "size": job.size if job else 0,
            "progress": job.progress if job else 0.0,
            "priority": 0,
            "is_seed": False,
            "piece_range": [0, 0],
            "availability": 1.0,
        }
    ]


@router.get("/torrents/categories")
async def torrents_categories():
    return {
        "lidarr": {
            "name": "lidarr",
            "savePath": DOWNLOAD_TARGET_DIR,
        }
    }


@router.post("/torrents/createCategory")
async def torrents_create_category(
    category: str = Form(default=""),
    savePath: str = Form(default=""),
):
    logger.info("qBit createCategory: category=%r savePath=%r (accepted)", category, savePath)
    return Response(status_code=200)


@router.post("/torrents/add")
async def torrents_add(
    request: Request,
    urls: str = Form(default=""),
    torrents: str = Form(default=""),
    cookie: str = Form(default=""),
    savepath: str = Form(default=""),
    category: str = Form(default=""),
    tags: str = Form(default=""),
    skip_checking: str = Form(default="false"),
    paused: str = Form(default="false"),
    root_folder: str = Form(default=""),
    rename: str = Form(default=""),
    uploadLimit: str = Form(default=""),
    downloadLimit: str = Form(default=""),
    ratioLimit: str = Form(default=""),
    seedingTimeLimit: str = Form(default=""),
    autoTMM: str = Form(default="false"),
    sequentialDownload: str = Form(default="false"),
    firstLastPiecePrio: str = Form(default="false"),
):
    logger.info(
        "qBit torrents/add: urls=%r torrents_len=%d savepath=%r category=%r",
        urls,
        len(torrents) if torrents else 0,
        savepath,
        category,
    )

    guid: Optional[str] = None

    if urls:
        for url in urls.split():
            url = url.strip()
            g = _extract_guid_from_url(url)
            if g:
                guid = g
                break

    if guid is None and torrents:
        guid = _extract_guid_from_torrent(torrents)

    if guid is None:
        logger.error("Could not extract guid from add request (urls=%r, torrents_len=%d)",
                     urls, len(torrents) if torrents else 0)
        return Response(content="Fails.", status_code=400)

    try:
        source, release_id = decode_guid(guid)
    except Exception as exc:
        logger.error("Invalid guid %r: %s", guid, exc)
        return Response(content="Fails.", status_code=400)

    logger.info("Decoded: source=%s release_id=%s", source, release_id)

    job_hash = info_hash(guid)
    job_name = f"[{source.capitalize()}] {release_id}"
    final_save = savepath or DOWNLOAD_TARGET_DIR

    existing = store.get(job_hash)
    if existing and existing.is_finished:
        logger.info("Job %s already completed; replacing.", job_hash)

    job = DownloadJob(
        guid=guid,
        source=source,
        release_id=release_id,
        name=job_name,
        save_path=final_save,
        state=JobState.QUEUED,
    )
    store.add(job)

    asyncio.create_task(_run_download(job))

    return Response(content="Ok.")


async def _run_download(job: DownloadJob) -> None:
    store.mark_downloading(job.hash)
    logger.info("Download started: %s (%s:%s)", job.name, job.source, job.release_id)

    try:
        actual_folder = await streamrip.download(
            source=job.source,
            release_id=job.release_id,
            media_type="album",
            progress_callback=lambda p: store.update_progress(job.hash, p),
        )
        if actual_folder:
            parent = os.path.dirname(actual_folder.rstrip("/"))
            folder_name = os.path.basename(actual_folder.rstrip("/"))
            job.save_path = parent
            job.name = folder_name
        store.mark_completed(job.hash)
        logger.info("Download completed: save_path=%s name=%s", job.save_path, job.name)
    except Exception as exc:
        logger.error("Download failed for %s: %s", job.name, exc)
        store.mark_failed(job.hash, str(exc))


@router.get("/torrents/delete")
@router.post("/torrents/delete")
async def torrents_delete(
    hashes: str = Form(default=""),
    deleteFiles: str = Form(default="false"),
):
    if not hashes:
        return Response(status_code=400)

    for h in hashes.split("|"):
        h = h.strip()
        if h:
            store.remove(h)
            logger.info("Job removed: hash=%s deleteFiles=%s", h, deleteFiles)

    return Response(status_code=200)


@router.get("/torrents/properties")
async def torrents_properties(hash: str = ""):
    job = store.get(hash)
    if job is None:
        return Response(status_code=404)

    return {
        "hash": job.hash,
        "name": job.name,
        "save_path": job.save_path,
        "creation_date": 1700000000,
        "piece_size": 1048576,
        "total_size": job.size,
        "comment": f"guid:{job.guid}",
        "total_uploaded": 0,
        "total_downloaded": job.downloaded,
        "time_elapsed": 0,
        "seeding_time": 0,
        "nb_connections": 0,
        "share_ratio": 1.0 if job.is_finished else 0.0,
        "addition_date": 1700000000,
        "completion_date": 1700000000 if job.is_finished else 0,
        "created_by": "TorznabRIP",
        "dl_speed_avg": 0,
        "eta": 8640000,
        "last_seen": 1700000000,
        "peers": 1,
        "peers_total": 1,
        "pieces_have": int(job.progress * 100),
        "pieces_num": 100,
        "reannounce": 0,
        "seeds": 1,
        "seeds_total": 1,
        "total_downloaded_session": job.downloaded,
        "total_uploaded_session": 0,
        "total_wasted": 0,
        "up_speed_avg": 0,
    }
