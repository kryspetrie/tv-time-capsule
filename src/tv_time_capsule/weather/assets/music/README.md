# Weather music assets

Background MP3s for native Retro Weather live here.

Fetch with:

```bash
./scripts/fetch-weather-music.sh
# or after install:
tv-time-capsule-fetch-weather-music
```

Sources (default `--source all`):

- [ws4kp-music](https://github.com/netbymatt/ws4kp-music) — AI companion tracks
- [weather.com/retro](https://weather.com/retro/) — RetroCast music + announcements
  (voiceovers / alert tone land in `../announcements/`)

Classic copyrighted Weather Channel airchecks are not fetched. Operator override:
`weather.music.directory` in `config.json`. `install.sh` / `install-pi.sh` run the
fetch automatically.
