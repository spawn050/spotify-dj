# spotify-dj

Talk to Claude like it's a DJ. An [MCP](https://modelcontextprotocol.io) server that lets Claude Code
build a Spotify mix from plain-English requests and keep the queue topped up while you listen.

```
> "Play Taylor Swift songs from 2015"
> "Add One Direction to the mix"
> "More Taylor"
> "Play artists like The Script"
> "Play some Taylor Swift songs I might like"
...
```

<!-- TODO: add demo GIF here -->
![demo](docs/demo.gif)

## How it works

```mermaid
flowchart LR
    You([You]) -- prompt --> Claude[Claude Code<br/>the DJ brain]
    Claude -- MCP tools over stdio --> Server

    subgraph Server [spotify-dj MCP server]
        direction TB
        Tools[server.py<br/>5 tools] --> DJ[dj.py<br/>keeps the queue stocked]
        Loop[session.py<br/>background loop] --> DJ
        DJ --> Mixer[mixer.py<br/>weighted blend]
        DJ --> Factory[factory.py<br/>request → source]
        Mixer --> Sources[sources.py<br/>search · top tracks · pinned]
        Factory --> Sources
        Sources --> Gateway[spotify.py<br/>gateway]
        DJ --> Gateway
    end

    Gateway -- spotipy --> Spotify[(Spotify Web API)]
```

- **Claude interprets your requests, the mcp server plays the music.** 
- Claude turns a request into a *mix* of sources with weights.
- A background loop (every 5 s, or immediately when the mix changes) refills Spotify's queue up
to a small depth (default 3 songs including the current one), so a new request is heard within a song or two.
<br>
<br>

| Source | What it is | Example request |
|---|---|---|
| `search` | Spotify search by artist / album / genre / year. | "Taylor Swift from 2015" |
| `top_tracks` | Your own favourites, then more songs by those artists. | "songs I might like" |
| `pinned` | Specific songs Claude picks from its own knowledge. | "upbeat One Direction" |

Sources are blended by **weight** ("more Taylor"), never repeat a song until everything has played, and
anything Spotify can't do is **flagged** back to you rather than silently ignored.

## Using LLM's music knowledge as a fallback

Spotify doesn't support recommendations, related-artists and audio-features (mood, energy, …) APIs.
So, we rely on LLM's music knowledge for certain cases: 

- **"Artists like The Script"**: LLM names similar artists from its own knowledge which become the  search sources
- **"Upbeat"** (Spotify can't filter by mood): LLM picks specific songs, the server looks each one up.
- **Anything impossible**: the tool design has no `mood` field, and LLM is told to say what was approximated.

## Architecture

Four layers, from the outside in:

| Layer | Files | Responsibility |
|---|---|---|
| MCP tools | `server.py` | 5 thin tools: parse Claude's request, call the DJ, describe the result. The DJ guidance for Claude lives in the tool descriptions. |
| Session | `session.py` | Shares one DJ between tool calls and the background loop behind a lock. Blocking Spotify calls run in worker threads. |
| DJ domain | `dj.py`, `mixer.py`, `factory.py`, `sources.py` | Pure logic: build sources from requests, blend them by weight, keep the queue stocked. |
| Gateway | `spotify.py` | The only module that imports spotipy: login, search, top items, playback and queue. |

`cli.py` wires everything together and provides the `login` command.

- **Dependencies point inward.** The domain only knows the `SpotifyGateway` protocol, so unit tests run on an in-memory fake instead of Spotify.
- **Sources are lazy streams** behind one `Source` base class, so a new kind of source plugs into the mixer without changing it.
- **The queue is reconciled, not assumed.** Every tick compares the songs the DJ queued with Spotify's real queue, so skips and your own queued songs don't skew the count. Spotify's queue lags behind writes by about a second, so freshly queued songs are trusted for 3 s.
- **Failures don't stop the music.** Expected errors go back to Claude as messages, background errors go to `logs/spotify-dj.log`, and stdout is left alone because it carries the MCP protocol.

## Setup

Requires [uv](https://docs.astral.sh/uv/), Python 3.11+, Spotify **Premium** and
[Claude Code](https://claude.com/claude-code).

1. **Create a Spotify app** at the [developer dashboard](https://developer.spotify.com/dashboard),
   add the redirect URI `http://127.0.0.1:8888/callback` and enable the Web API.
   (Development Mode apps allow up to 5 users, which is plenty here.)
2. **Configure**: `cp .env.example .env` and set `SPOTIFY_CLIENT_ID`. No client secret is needed (PKCE login).
3. **Log in once**: `uv sync && uv run spotify-dj login` (opens your browser, saves `.spotify_token.json` here).
4. **Register with Claude Code** so it works from any folder:
   ```bash
   claude mcp add --scope user spotify-dj -- uv --directory /absolute/path/to/spotify-dj run spotify-dj
   ```
5. **Play something** in Spotify on any device (Spotify only accepts queued songs while a device is active),
   open Claude Code anywhere and ask for music.

Everything the server writes stays in this folder: `.env`, `.spotify_token.json` and `logs/` (all git-ignored).

### Settings (`.env`)

| Variable | Default | Meaning |
|---|---|---|
| `DJ_QUEUE_DEPTH` | `3` | Songs kept queued, including the one playing |
| `DJ_POLL_SECONDS` | `5` | How often playback is checked |

## Tests

```bash
uv run pytest            # unit tests, no network (fake Spotify)
uv run pytest -m live    # real Spotify; needs login + a playing device; queues real songs
```

## Limitations

- Spotify's queue can only be appended to, so after "Play X" the 1–2 songs already queued still play first.
- The DJ only runs while Claude Code is running, and can't speak up on its own: ask `get_status` to see problems.
- Genre search is best-effort; Spotify's genre filter is patchy.
