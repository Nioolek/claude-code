# Copilot Instructions for Python Projects

## 📁 Core Concepts

| Term | Meaning |
|------|---------|
| `REPO-ROOT` | Repository root directory |
| `PROJECT-ROOT` | Project root (where `pyproject.toml`/`setup.py` lives) |
| `VENV-ROOT` | Virtual environment root |
| Project Info | `REPO-ROOT/PROJECT.md` |
| KB Entry | `REPO-ROOT/.github/KnowledgeBase/Index.md` |

---

## ⚠️ Key Rules

### File Operations
- **Re-read source files before writing** — respect parallel edits
- When `*.prompt.md` is referenced → act immediately per instructions
- **Never modify** `venv/`, `.venv/`, `__pycache__/`, `dist/`, `build/` folders
- Always create `__init__.py` for new packages

### Environment Management
- **Always use virtual environments**
- Detect from: `pyproject.toml`, `requirements.txt`, `Pipfile`, `poetry.lock`
- Preferred tools (in order): `uv` > `poetry` > `pip` > `conda`

### Windows
- PowerShell format: `& python -m module args...`
- Use `py` launcher when available: `py -3.11`
- Multi-command: `cmd1; cmd2` (PowerShell) or `cmd1 && cmd2` (CMD)

### Linux/macOS
- Use `python3` explicitly
- Shebang: `#!/usr/bin/env python3`
- Multi-command: `cmd1 && cmd2`

---

## 📚 Required Guidelines

| Task | Document Path |
|------|---------------|
| Add/Modify Source Files | `Guidelines/SourceFileManagement.md` |
| Environment Setup | `Guidelines/Environment.md` |
| Run Tests | `Guidelines/Running-Tests.md` |
| Run CLI Apps | `Guidelines/Running-CLI.md` |
| Run Web Apps | `Guidelines/Running-Web.md` |
| Debugging | `Guidelines/Debugging.md` |
| Code Style | `Guidelines/CodeStyle.md` |

---

## 💻 Python Coding Standards

### Version
- **Python 3.10+** — encourage modern features
- Specify in `pyproject.toml`: `requires-python = ">=3.10"`

### Type Hints (Mandatory!)
```python
# ✅ Required
from typing import Optional, List, Dict, Any, Union, Callable
from collections.abc import Sequence, Mapping, Iterable

def process_data(items: list[str], config: dict[str, Any]) -> bool:
    ...

def get_user(user_id: int) -> User | None:  # Python 3.10+ union
    ...
```

### Imports
```python
# Order: stdlib → third-party → local
import os
import sys
from pathlib import Path

import requests
from fastapi import FastAPI

from .utils import helper
from ..models import User
```

- Use absolute imports within packages
- Relative imports only for siblings/parent
- **No** `from module import *`

### Code Style
- **4 spaces** indentation (no tabs)
- Max line length: **88 chars** (Black default) or **100 chars**
- Follow **PEP 8** + **PEP 257** (docstrings)
- Use **f-strings** for formatting (Python 3.6+)
- Use **walrus operator** `:=` when appropriate (Python 3.8+)

### Naming Conventions
```python
# Classes → PascalCase
class UserService, DataProcessor

# Functions/variables → snake_case
def get_user_data(), user_count, max_retries

# Constants → UPPER_SNAKE_CASE
MAX_CONNECTIONS, DEFAULT_TIMEOUT

# Private → leading underscore
_internal_var, _helper_function()

# Name mangling → double underscore
__private_attr  # use sparingly
```

### Decorators
```python
# Standard order: @functools → custom → @abstractmethod
@dataclass
@total_ordering
class User:
    ...

@app.route("/api")
@require_auth
@rate_limit
def api_endpoint():
    ...
```

### Async/Await
```python
# Use asyncio for I/O-bound tasks
async def fetch_data(url: str) -> dict:
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as resp:
            return await resp.json()

# Use threading/multiprocessing for CPU-bound tasks
```

### Error Handling
```python
# ✅ Specific exceptions
try:
    result = process(data)
except ValueError as e:
    logger.error(f"Invalid data: {e}")
    raise
except ConnectionError as e:
    logger.warning(f"Connection failed: {e}")
    retry()

# ❌ Avoid bare except
# except:  # DON'T

# Use context managers for resources
with open("file.txt") as f:
    data = f.read()
```

### Logging
```python
# ✅ Use logging module
import logging

logger = logging.getLogger(__name__)

logger.debug("Debug info")
logger.info("User logged in")
logger.warning("Deprecated API")
logger.error(f"Failed: {error}")
logger.exception("Unexpected error")  # includes traceback
```

### Docstrings
```python
def process_user(user_id: int, include_details: bool = False) -> User:
    """Process and return user information.
    
    Args:
        user_id: The unique user identifier
        include_details: Whether to include extended details
        
    Returns:
        User object with processed data
        
    Raises:
        UserNotFoundError: If user_id doesn't exist
        ValidationError: If user_id format is invalid
        
    Example:
        >>> user = process_user(12345)
        >>> print(user.name)
    """
```

---

## 🧪 Testing Standards

### Framework
- **pytest** (preferred) or `unittest`
- Test files: `test_*.py` or `*_test.py`
- Test location: `tests/` directory or alongside source

### Test Structure
```python
import pytest

class TestUserService:
    @pytest.fixture
    def sample_user(self):
        return User(id=1, name="Test")
    
    def test_get_user(self, sample_user):
        assert sample_user.id == 1
    
    @pytest.mark.asyncio
    async def test_async_operation(self):
        result = await async_func()
        assert result is not None
```

### Coverage
- Target: **80%+** coverage
- Run: `pytest --cov=package tests/`

---

## 📦 Project Structure

```
project/
├── pyproject.toml      # Modern standard (preferred)
├── setup.py            # Legacy fallback
├── requirements.txt    # Simple deps
├── README.md
├── LICENSE
├── .gitignore
├── src/
│   └── package/
│       ├── __init__.py
│       ├── module.py
│       └── subpkg/
├── tests/
│   ├── __init__.py
│   └── test_module.py
├── docs/
├── scripts/
└── .github/
    └── workflows/
```

---

## 🔧 Tooling

### Formatting
```bash
black .                    # Code formatting
isort .                    # Import sorting
ruff check .               # Fast linting
```

### Type Checking
```bash
mypy src/                  # Static type checking
pyright src/               # Alternative
```

### Testing
```bash
pytest                     # Run tests
pytest -v                  # Verbose
pytest -x                  # Stop on first failure
pytest --cov=src           # Coverage
```

### Security
```bash
pip-audit                  # Dependency vulnerabilities
bandit -r src/             # Security issues in code
```

---

## 🧠 Knowledge Base Usage

Entry: `KnowledgeBase/Index.md`

Structure:
```markdown
## Guidance          → Global guidelines
## Project           → Project documentation
  ### Architecture      → System architecture
  ### API Reference     → API documentation
  ### Design Decisions  → ADRs
## Experiences       → Lessons learned
## Troubleshooting   → Common issues & fixes
```

---

## 📝 Markdown Writing Rules

- Don't print `"` or `"` in markdown code blocks
- Multiple top-level `# Topic` allowed
- Python names:
  - Standard library → full name (`pathlib.Path`)
  - Third-party → full name with package (`requests.Session`)
  - Project code → full name + file location if ambiguous

---

## 📂 Task Logs Location

`REPO-ROOT/.github/TaskLogs/`:
- `Copilot_Scrum.md`
- `Copilot_Task.md`
- `Copilot_Planning.md`
- `Copilot_Execution.md`
- `Copilot_KB.md`
- `Copilot_Investigate.md`

---

## 🎯 Python-Specific Best Practices

### Data Classes
```python
from dataclasses import dataclass, field
from typing import Optional

@dataclass
class User:
    id: int
    name: str
    email: Optional[str] = None
    tags: list[str] = field(default_factory=list)
```

### Context Managers
```python
from contextlib import contextmanager

@contextmanager
def database_connection():
    conn = create_connection()
    try:
        yield conn
    finally:
        conn.close()
```

### Path Handling
```python
from pathlib import Path

# ✅ Use pathlib
config_path = Path(__file__).parent / "config" / "settings.json"
data = config_path.read_text()

# ❌ Avoid os.path
```

### Environment Variables
```python
import os
from dotenv import load_dotenv

load_dotenv()  # .env file

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///default.db")
DEBUG = os.getenv("DEBUG", "false").lower() == "true"
```

### Configuration
```python
# pyproject.toml example
[tool.black]
line-length = 88
target-version = ['py310']

[tool.ruff]
line-length = 88
select = ["E", "F", "W", "I"]

[tool.mypy]
python_version = "3.10"
strict = true
```

---

## ⚡ Quick Reference

| Task | Command |
|------|---------|
| Create venv | `python -m venv .venv` |
| Activate (Unix) | `source .venv/bin/activate` |
| Activate (Win) | `.venv\Scripts\activate` |
| Install deps | `pip install -r requirements.txt` |
| Run module | `python -m package.module` |
| Run tests | `pytest tests/` |
| Format code | `black . && isort .` |
| Type check | `mypy src/` |
| Lint | `ruff check .` |

---

> 💡 **Remember**: Always check `PROJECT.md` and `KnowledgeBase/Index.md` before making significant changes. When in doubt, ask before modifying core architecture.
