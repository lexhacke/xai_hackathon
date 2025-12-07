# FastAPI Backend Makefile
# ------------------------------------------------------------------------------

.PHONY: check lint pyrelfy fix ruff smoke test format clean build install run makemigrations migrate
SHELL := /bin/bash
.SHELLFLAGS = -eu -o pipefail -c   # stop on any error in a recipe
.ONESHELL:                         # run each recipe in a single shell



MODELS_FILE        = app/models.py
VIEW_MODELS_FILE   = app/view_tables.py
VIEW_MODELS_NEW    = $(VIEW_MODELS_FILE).new
ENV_FILE           = $(PWD)/.env     # path to your .env with absolute path




# Environment variables for development commands
# ------------------------------------------------------------------------------
DEV_ENV=PROJECT_NAME="FastAPI Backend Dev" \
        ENVIRONMENT="local"

# Docker related commands
# ------------------------------------------------------------------------------

# Default Docker environment variables for local development/testing
# These can be overridden by setting the variables before running the commands
DOCKER_ENV=DOCKER_IMAGE_BACKEND="app-backend" \
          DOMAIN="localhost" \
          STACK_NAME="app" \
          SECRET_KEY="development_secret_key" \
          ENVIRONMENT="local" \
          UV_HTTP_TIMEOUT="120"

# Build the Docker image
build:
	$(DOCKER_ENV) TAG=$${TAG:-latest} docker compose -f docker-compose.yml build

# Install dependencies
# ------------------------------------------------------------------------------
install:
	@echo "📦 Installing dependencies..."
	uv sync

# Testing
# ------------------------------------------------------------------------------

# Unified test command supporting both full and incremental testing
# MODE=full runs all tests with coverage reporting
# Default uses testmon for faster incremental testing (only affected tests)
test:
	@echo "🧹 Cleaning Python cache files"
	if [ $$(uname -s) = "Linux" ]; then \
		echo "Remove __pycache__ files"; \
		find . -type d -name __pycache__ -exec rm -r {} \+ 2>/dev/null || true; \
	fi
	@if [ "$(MODE)" = "full" ]; then \
		echo "🧪 Running tests with full coverage against main database"; \
		uv run pytest --cov=app --cov-report=term-missing app/tests; \
	else \
		echo "🔄 Running incremental tests with testmon - only affected tests will run"; \
		uv run pytest --testmon; \
	fi

# Code quality
# ------------------------------------------------------------------------------

# -------------------------------------------------
# 1️⃣  pyrefly (stop the build on any type errors)
pyrefly:
	@echo "🔍 [pyrefly] Running type-check..."
	@bash -c '
		# Get list of changed .py files, filter out models.py and only keep existing files
		py_files="$$(git ls-files -m -o --exclude-standard -- "*.py" | grep -v "app/models.py" | xargs -I {} bash -c "if [ -f {} ]; then echo {}; fi")" 
		if [ -z "$$py_files" ]; then
			echo "No changed .py files; skipping pyrefly."
			exit 0
		else
			# Run with env variables properly set
			$(DEV_ENV) sh -c "echo \"$$py_files\" | xargs uv run pyrefly check"
		fi
	'

# -------------------------------------------------
# 2️⃣  Ruff auto-fix (ignore its exit-code on purpose)
fix:
	@echo "🛠️  [Ruff] Running auto-fix (output suppressed)..."
	@$(DEV_ENV) uv run ruff check --fix app/ > /dev/null 2>&1 || true

# -------------------------------------------------
# 3️⃣  Ruff check (only reached if pyrelfy passed)
ruff:
	@echo "✅ [Ruff] Checking for remaining issues..."
	$(DEV_ENV) uv run ruff check app/

# -------------------------------------------------
# Format code (using ruff)
format:
	$(DEV_ENV) uv run ruff check app --fix
	$(DEV_ENV) uv run ruff format app

# -------------------------------------------------
# Composite target: pyrelfy → (optional) Ruff fix → Ruff check
check: pyrelfy fix ruff
	@echo "✨ Linting completed successfully!"
	@echo "✅ All checks passed!"


# -------------------------------------------------
# Smoke test - verify app can import correctly
smoke:
	@echo "🚀 [Smoke Test] Verifying app startup by importing app.main..."
	@$(DEV_ENV) uv run python -c "import app.main" \
		&& echo "👍 App imported successfully!" \
		|| (echo "❌ App import failed!" >&2; exit 1)

# Cleaning
# ------------------------------------------------------------------------------
clean:
	@echo "Cleaning up project..."
	find . -type d -name "__pycache__" -exec rm -rf {} +
	find . -type d -name "*.egg-info" -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete
	find . -type d -name ".pytest_cache" -exec rm -rf {} +
	find . -type d -name ".coverage" -exec rm -rf {} +
	find . -type d -name ".ruff_cache" -exec rm -rf {} +
	@echo "Cleanup complete!"


# Helper function to safely load .env files
define load_env
	$(eval include $(ENV_FILE))
	$(shell if [ ! -f "$(1)" ]; then echo "WARNING: $(1) file not found"; fi)
	$(shell grep -v '^\#' $(1) | sed 's/^export[[:space:]]*//' | xargs -d '\n' -I {} echo export "{}" >> $(1).mk)
	$(eval include $(1).mk)
	$(shell rm -f $(1).mk 2>/dev/null)
endef

# Migrations
# ------------------------------------------------------------------------------
migrate:
	@echo "🔄 Applying migrations..."
	$(DEV_ENV) uv run alembic upgrade head

# -------------------------------------------------------

# Run the FastAPI backend server
# ------------------------------------------------------------------------------
run:
	@echo "🚀 Starting FastAPI backend server..."
	$(DEV_ENV) uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
