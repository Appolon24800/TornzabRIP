# TornzabRIP

A small bridge that lets [Lidarr](https://lidarr.audio/) search and grab music from
**Qobuz** and **Deezer** via [StreamRip](https://github.com/nathom/streamrip).

It exposes two fake APIs on one HTTP server:

- a **Torznab indexer** (`/api`) so Lidarr can search Qobuz + Deezer like a normal tracker
- a **qBittorrent Web UI** (`/api/v2`) so Lidarr can "download" results — the download is
  actually ripped through StreamRip and dropped into your download folder.

No real torrents are ever involved.

## Requirements

- Docker (or Podman) — that's it.
- A working **StreamRip config file** (`config.toml`) with valid Qobuz and/or Deezer
  credentials. Generate one locally with `streamrip config` and then mount it into the
  container.

> **GHCR visibility:** new GitHub Container Registry packages are **private** by default.
> To `docker pull` without logging in, go to
> `https://github.com/users/Appolon24800/packages/container/tornzabrip/settings` and set
> the visibility to **Public**. Otherwise authenticate first:
>
> ```bash
> echo $GITHUB_TOKEN | docker login ghcr.io -u Appolon24800 --password-stdin
> ```

## Run with Docker

```bash
docker run -d \
  --name tornzabrip \
  -p 8686:8686 \
  -v $(pwd)/streamrip-config:/config/streamrip \
  -v /path/to/downloads:/downloads \
  -v /path/to/data:/data \
  ghcr.io/appolon24800/tornzabrip:latest
```

Put your StreamRip `config.toml` inside `./streamrip-config/`.

## docker-compose example

```yaml
services:
  tornzabrip:
    image: ghcr.io/appolon24800/tornzabrip:latest
    container_name: tornzabrip
    restart: unless-stopped
    ports:
      - "8686:8686"
    volumes:
      # StreamRip config.toml lives here
      - ./streamrip-config:/config/streamrip
      # Where ripped music is written
      - /mnt/media/downloads:/downloads
      # Persistent job state (survives restarts)
      - ./data:/data
    environment:
      DOWNLOAD_TARGET_DIR: /downloads
      # Optional shared secret Lidarr must send as ?apikey=
      # TORZNABRIP_API_KEY: changeme
      # Optional: override the port
      # PORT: "8686"
```

Bring it up with:

```bash
docker compose up -d
```

## Environment variables

| Variable                 | Default                              | Description                                            |
| ------------------------ | ------------------------------------ | ------------------------------------------------------ |
| `STREAMRIP_CONFIG_PATH`  | `/config/streamrip/config.toml`      | Path to the StreamRip config inside the container.     |
| `DOWNLOAD_TARGET_DIR`    | `/data/downloads`                    | Where ripped files are written.                        |
| `JOBS_FILE`              | `/data/jobs.json`                    | Persistent download-job state.                         |
| `PORT`                   | `8686`                               | HTTP port the server listens on.                       |
| `TORZNABRIP_API_KEY`     | *(empty)*                            | If set, Lidarr must send this as `?apikey=`. Empty = accept all. |

## Volumes

| Mount           | Why                                                      |
| --------------- | -------------------------------------------------------- |
| `/config/streamrip` | Your StreamRip `config.toml` (contains Qobuz/Deezer creds). |
| `/downloads`        | Output directory for ripped music.                       |
| `/data`             | `jobs.json` state so history survives restarts.          |

## Configure Lidarr

1. **Indexers → Add Indexer → Torznab (Custom)**
   - URL: `http://<host>:8686/api`
   - API Key: whatever you set as `TORZNABRIP_API_KEY` (leave blank if unset).
2. **Download Clients → Add Client → qBittorrent**
   - Host: `<host>`, Port: `8686`
   - Username/Password: anything (login always succeeds).
3. Search an album in Lidarr — results come from Qobuz/Deezer and are delivered into
   your `/downloads` folder.

## Build locally

```bash
docker build -t tornzabrip .
docker run -p 8686:8686 -v $(pwd)/streamrip-config:/config/streamrip \
  -v $(pwd)/downloads:/downloads -v $(pwd)/data:/data tornzabrip
```

## Notes

- The published image is multi-arch (`linux/amd64` + `linux/arm64`), so it runs on both
  x86 hosts and ARM NAS devices.
- The image installs a headless Chromium (via Playwright) because StreamRip uses it for
  Deezer login. This makes the image a few hundred MB.
- The container runs as root by default. If you need a specific UID/GID owning the output
  files, run with `user: "1000:1000"` in compose (ensure the mounted dirs are writable).
