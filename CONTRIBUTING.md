# Contributing

Use Python 3.12+ and install `pip install -e '.[dev]'`.
Run `ruff check tuxigap tests`, `ruff format --check tuxigap tests`, and
`python -m unittest discover -s tests -v` before opening a pull request.
Payment, permissions and moderation changes require behavioral regression coverage.
Never put live credentials, real user data, `.env`, databases or backups in a commit.
Keep every claimed feature linked to a working UI/command and tests where meaningful.
Schema changes after v0.2.0 require a versioned migration; do not just edit the baseline schema.
