# Let's Encrypt Helper GUI

A Dockerized Flask interface that provisions free TLS certificates from Let's Encrypt and configures an accompanying Nginx instance automatically. It embeds Docker-in-Docker so the UI container can control helper containers (Nginx + Certbot) while persisting all certificate artifacts on the host.

## Features
- Web UI to collect domain name and optional admin email.
- Automated flow: launch temporary HTTP Nginx, request certificate via Certbot webroot challenge, rewrite config for HTTPS, reload Nginx.
- Certificates, renewal configs, and logs stored under `cert_data/` for persistence across runs.
- Single `docker compose up` brings up the entire workflow.

## Architecture

| Path | Purpose |
| --- | --- |
| `docker-compose.yml` | Runs the GUI container with the necessary volume mounts and port mappings. |
| `Dockerfile` | Builds the GUI image (Python 3.9 slim + Docker CLI/daemon + Flask app). |
| `entrypoint.sh` | Starts Docker daemon inside the container and then launches the Flask app. |
| `flask/app.py` | Core Flask application; orchestrates Docker containers for Nginx and Certbot. |
| `flask/templates/index.html` | HTML template for submitting domains and monitoring step status. |
| `nginx_conf/` | Target directory where the Flask app writes the live Nginx configuration. |
| `cert_data/` | Mirrors `/etc/letsencrypt` for certs, renewal configs, ACME challenge files, and logs. |

### Workflow
1. User navigates to `http://<server>:8070` and submits a domain (must point to the server's public IP) plus optional admin email.
2. Flask app writes an HTTP-only config to `nginx_conf/default.conf`, then starts an `nginx:alpine` container with `cert_data` volumes.
3. Certbot runs in its own container (`certbot/certbot`) using the webroot challenge, depositing keys/certs into `cert_data/conf`.
4. Flask rewrites the Nginx config for HTTPS and issues `nginx -s reload` inside the running container.
5. Certificates stay on disk so renewals or restarts don't require re-issuance (subject to Let's Encrypt rate limits).

## Prerequisites
- Docker Engine with Docker Compose v2.
- Public DNS A record pointing to the host and inbound access on ports 80, 443, and 8070.
- Internet access for pulling container images and contacting Let’s Encrypt.

## Quick Start
```bash
git clone <your-repo-url>
cd letsencrypt
docker compose up -d --build
```

Then open `http://<your-server>:8070` to kick off certificate issuance.

## Operational Notes
- Replace `app.secret_key` in `flask/app.py` with a strong random value before deploying publicly.
- Restrict access to port 8070 (VPN, firewall, etc.)—it controls certificate issuance and contains no auth.
- `cert_data/` contains private keys, renewal configs, and logs; back it up securely.
- Renewal automation is not scheduled; to renew manually run `docker run --rm -v %cd%/cert_data/conf:/etc/letsencrypt -v %cd%/cert_data/www:/var/www/certbot certbot/certbot renew` or a similar command on a schedule.

## Troubleshooting
- **Port conflicts**: stop other services binding 80/443 while this stack is running.
- **Permission issues**: ensure the Docker daemon user owns `cert_data/` and `nginx_conf/`.
- **Rate limits**: Let’s Encrypt enforces issuance limits. Avoid repeated failed requests and consult https://letsencrypt.org/docs/rate-limits/.

## Licensing
Add your preferred license information here (e.g., MIT, Apache 2.0).

