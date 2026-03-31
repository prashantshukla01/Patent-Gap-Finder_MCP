# Security Policy

## Overview

The **Research Paper → Patent Gap Finder** project takes security seriously. This
document outlines our security policy, how to report vulnerabilities, and the practices
we follow to keep the project and its users safe.

---

## Supported Versions

We actively maintain and patch security vulnerabilities in the following versions:

| Version | Status          | Supported Until  |
|---------|-----------------|------------------|
| 1.x     | Active          | Current          |
| 0.5.x   | Maintenance     | 6 months post v1 |
| < 0.5   | End of life     | No longer patched|

If you are running an unsupported version, we strongly recommend upgrading to the
latest stable release.

---

## Reporting a Vulnerability

**Please do not report security vulnerabilities through public GitHub issues.**

Disclosing a vulnerability publicly before it is patched puts all users of the project
at risk. We ask that you follow responsible disclosure practices.

### How to Report

Send a detailed report via **GitHub's private vulnerability disclosure feature**:

1. Navigate to the repository on GitHub
2. Click the **Security** tab
3. Click **Report a vulnerability**
4. Fill in the details and submit

Alternatively, email the maintainer directly:

**Prashant Shukla**
Security contact: `security@patent-gap-finder.dev` *(replace with your actual contact)*
PGP key: *(add your PGP fingerprint here if available)*

### What to Include

A good vulnerability report includes:

- **Description** — What is the vulnerability and what is its impact?
- **Affected component** — Which file, module, API endpoint, or dependency is affected?
- **Reproduction steps** — A minimal, reproducible example (code, curl command, etc.)
- **Environment** — Python version, OS, dependency versions, Docker version if applicable
- **Severity assessment** — Your estimate of the CVSS score or impact level
- **Suggested fix** — Optional, but highly appreciated

### What to Expect

| Timeline | Action |
|----------|--------|
| Within **48 hours** | We acknowledge receipt of your report |
| Within **7 days** | We confirm whether the issue is valid and assign a severity |
| Within **30 days** | We release a patch for confirmed critical/high vulnerabilities |
| Within **90 days** | We release a patch for medium/low vulnerabilities |
| After patch release | We publicly disclose the vulnerability and credit the reporter |

We will keep you informed throughout the process. If you do not receive acknowledgement
within 48 hours, please follow up via email.

---

## Security Considerations for This Project

This project integrates with several external services and handles sensitive data.
Below are the key security considerations users and contributors should be aware of.

### API Keys and Secrets

This project requires several API keys (Gemini, EPO, SerpAPI, USPTO). These must
**never** be committed to version control.

- Always use `.env` files (which are git-ignored) or environment variables
- Never hardcode API keys in source files, tests, or configuration files
- Rotate any key that is accidentally exposed immediately
- Use Railway or similar platforms' secret management for production deployments

```bash
# NEVER do this
GEMINI_API_KEY = "AIzaSy..."  # hardcoded in source = critical vulnerability

# ALWAYS do this
GEMINI_API_KEY = os.environ["GEMINI_API_KEY"]
```

### Research Paper Data

- PDFs uploaded for analysis may contain sensitive or unpublished research
- The project stores extracted text and claims in PostgreSQL — ensure your database
  is not publicly accessible
- Use strong Postgres credentials in production; never use the default `password`
- Enable SSL on your database connection string in production:
  `postgresql+asyncpg://user:pass@host/db?ssl=require`

### Network Security

- The MCP server should not be exposed to the public internet without authentication
- For Claude Desktop use (stdio transport): the server runs locally — no network exposure
- For HTTP transport: place behind a reverse proxy (nginx, Caddy) with TLS
- Redis should never be exposed publicly — bind to `127.0.0.1` or use Docker networking

### Dependency Security

We use `uv` for dependency management with pinned versions. To check for known
vulnerabilities in dependencies:

```bash
# Audit dependencies for known CVEs
uv pip audit

# Or using pip-audit directly
pip-audit
```

We recommend running dependency audits as part of your CI pipeline.

### Docker Security

- Never run containers as root — our Dockerfile uses a non-root user
- Do not mount the host Docker socket into containers
- Use Docker secrets or environment variable injection for API keys
- Regularly pull updated base images to receive OS security patches:
  ```bash
  docker compose pull
  docker compose up -d
  ```

### Qdrant Vector Database

- Qdrant has no authentication by default on the free/open-source version
- In production, enable Qdrant's API key authentication:
  ```yaml
  # qdrant config
  service:
    api_key: your_qdrant_api_key
  ```
- Set `QDRANT_API_KEY` in your `.env` and pass it to the `AsyncQdrantClient`

### SQL Injection Prevention

All database interactions use SQLAlchemy ORM with parameterized queries.
Raw SQL strings are never constructed from user input. Do not bypass the ORM
with `text()` queries that incorporate unsanitized input.

---

## Security Best Practices for Contributors

If you are contributing code to this project, please follow these practices:

- **No secrets in code** — use environment variables for all credentials
- **Validate all inputs** — use Pydantic v2 models to validate all external data
  (API responses, user input, file uploads) before processing
- **Sanitize file paths** — when accepting file paths (e.g. PDF uploads), validate
  that the path does not escape the intended directory (path traversal attack)
  ```python
  # Safe file path validation
  from pathlib import Path
  safe_base = Path("/allowed/upload/dir").resolve()
  user_path = Path(user_supplied_path).resolve()
  assert str(user_path).startswith(str(safe_base)), "Path traversal detected"
  ```
- **Limit PDF size** — enforce a maximum file size for PDF uploads (recommended: 50MB)
  to prevent resource exhaustion attacks
- **Rate limit external inputs** — the Gemini client already enforces rate limits;
  do not add code that bypasses the GeminiClient singleton to make direct API calls
- **Never log secrets** — ensure API keys, database URLs, and tokens are never passed
  to the logger, even at DEBUG level

---

## Known Security Limitations

The following are known limitations that users should be aware of:

1. **No built-in authentication on the MCP server** — The FastMCP server has no
   user authentication layer. It is designed to run locally (stdio) or behind an
   authenticated reverse proxy. Do not expose it directly to the internet.

2. **PDF parsing attack surface** — PyMuPDF processes untrusted PDFs. Maliciously
   crafted PDFs can sometimes exploit PDF parser bugs. Keep PyMuPDF updated and
   do not process PDFs from untrusted sources in a shared/production environment.

3. **LLM prompt injection** — Patent abstracts fed to Gemini could theoretically
   contain prompt injection attempts. Gemini's system prompt is not considered
   a hard security boundary. Do not grant the MCP server access to privileged
   systems beyond what is described in this project.

---

## Disclosure Policy

We follow a **coordinated disclosure** model:

- Reporter notifies us privately
- We confirm, patch, and prepare a release
- Reporter is credited in the security advisory (unless they prefer anonymity)
- We publish a GitHub Security Advisory after the patch is released
- We request a 90-day embargo for critical vulnerabilities to allow users time to upgrade

We will **never** pursue legal action against researchers who follow this policy in
good faith.

---

## Security Hall of Fame

We recognize and thank security researchers who responsibly disclose vulnerabilities.

*(No disclosures yet — be the first!)*

---

*Last updated: March 2026*
*Maintainer: Prashant Shukla*