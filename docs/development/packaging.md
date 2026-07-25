# Packaging & release

## Tooling

- **Poetry 2** with PEP 621 `[project]` metadata  
- Build backend: `poetry-core`  
- Lockfile: `poetry.lock` (commit it for reproducible installs)  

## Important `pyproject.toml` bits

- `packages = [{ include = "tv_time_capsule", from = "src" }]`  
- `include` ships `src/tv_time_capsule/assets/*` (font, VHS screensaver bitmap) into sdist/wheel  
- Dependencies: pygame, numpy, Pillow, keyring  
- Scripts: `tv-time-capsule`, `tv-time-capsule-secrets`  

## Local build

```bash
poetry build
unzip -l dist/*.whl | head
```

Confirm the font and entry points are inside the wheel.

## Install channels

| Channel | Command |
|---------|---------|
| Editable / Poetry | `poetry install` |
| pipx from path | `pipx install /path/to/tv-time-capsule` |
| pipx from git | `pipx install git+ssh://git@github.com:kryspetrie/tv-time-capsule.git` |
| Pi appliance | `./install-pi.sh` → venv + `pip install $INSTALL_DIR` |

## License metadata

SPDX-style text in project metadata: `CC-BY-NC-4.0`. Full legal text in `/LICENSE`.

## Version

Bump `version` in `pyproject.toml` (and `__version__` in `__init__.py` if you keep them in sync) before tagging a release.
