---
name: project-setup
description: 'Use when setting up, running, or troubleshooting the smart seat reservation and navigation system for the first time. Triggers: new developer onboarding, env configuration, Docker start, database init, test run.'
---

# 智能选座与导航系统 — 项目设置

## Overview

This skill guides you through setting up the Flask-based smart seat reservation and navigation system from scratch. Covers local dev (no Docker) and Docker Compose workflows.

## When to Use

- First-time setup of this project
- Configuring `.env` and database
- Running tests or seeding data
- Switching between dev and Docker environments
- Troubleshooting MySQL / Redis connection failures

## 1. Prerequisites

| Tool | Version | Check |
|------|---------|-------|
| Python | ≥ 3.11 | `python --version` |
| MySQL | 8.0+ | `mysql --version` |
| Redis | 7+ | `redis-cli --version` (optional) |
| Docker | 24+ | `docker --version` (optional) |

## 2. Environment Setup

Copy `.env.example` to `.env` and fill in credentials:

```bash
cp .env.example .env
```

Required changes in `.env`:
- `DB_PASSWORD=your_mysql_root_password`
- `SECRET_KEY=<random-string>` (optional, has default)

> **No MySQL?** The app auto-falls back to SQLite (`seat_navigation.db`). Everything works except sensor simulation persistence.

## 3. Local Dev (No Docker)

```bash
# 1. Create venv & install
python -m venv venv
venv\Scripts\activate     # Windows
# source venv/bin/activate  # Linux/Mac
pip install -r requirements.txt

# 2. Init database
python setup_db.py
# Or skip MySQL and use SQLite fallback (auto-detected)

# 3. Run
python app.py
# → http://localhost:5800
```

## 4. Docker Compose (Full Stack)

```bash
# 1. Ensure .env has correct DB_PASSWORD for MySQL root

# 2. Start all services
docker compose up -d --build

# 3. Init database
docker compose exec app python setup_db.py

# → http://localhost:80 (nginx proxy)
# → http://localhost:5800 (app direct)
```

**Wait for health checks** — MySQL takes ~20s to be ready. Check:
```bash
docker compose ps  # All should show "healthy" or "Up"
```

## 5. Database Management

| Task | Command |
|------|---------|
| Create tables + seed data | `python setup_db.py` |
| Rebuild from scratch | `python setup_db.py --drop` |
| Create tables only (app context) | `python -c "from app import app, db; app.app_context().push(); db.create_all()"` |

## 6. Running Tests

```bash
# All tests (verbose)
pytest

# Fast tests only (skip slow/integration)
pytest -m "not slow"

# Specific file
pytest tests/test_api.py -v

# With coverage
pip install pytest-cov
pytest --cov=app --cov=models --cov=utils --cov-report=term
```

**Tests use SQLite in-memory** — no MySQL needed.

## 7. Common Issues

| Symptom | Cause | Fix |
|---------|-------|-----|
| `MySQL 不可用，回退到 SQLite` | MySQL not running | Start MySQL or ignore (SQLite works) |
| `pymysql.err.OperationalError` | Wrong password/host | Check `DB_PASSWORD` in `.env` |
| `ModuleNotFoundError: cv2` | OpenCV system deps missing | `pip install opencv-python` (or Docker) |
| `Address already in use` | Port 5800/3306/6379 occupied | Check with `netstat -ano \| findstr :PORT` |
| Docker MySQL won't start | Health check timeout | `docker compose logs mysql` to diagnose |
| Static files not loading | nginx not running (Docker) | `docker compose up -d nginx` |

## 8. Project Structure (Quick Reference)

```
app.py                  # Flask app entry + routes (~800 lines)
config.py               # Config classes (dev/prod)
setup_db.py             # DB init script
models/                 # SQLAlchemy models
utils/                  # Locking, navigation, sensors, etc.
templates/              # Jinja2 templates
static/                 # CSS, JS, admin scripts
tests/                  # Pytest suite
data/                   # Runtime data (networks, overlays, QR codes)
uploads/                # User uploads (floor plans)
```
