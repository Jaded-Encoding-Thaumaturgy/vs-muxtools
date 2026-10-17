set windows-shell := ["powershell.exe", "-NoLogo", "-NoProfile", "-Command"]

lint:
    uv run ruff format
    uv run ruff check --fix
    uv run pyrefly check
