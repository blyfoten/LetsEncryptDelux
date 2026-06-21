from flask import Flask, render_template, request, jsonify
import os
import requests
import socket
import docker
import threading
import logging
from enum import Enum

app = Flask(__name__)
app.secret_key = 'your_secret_key'  # Replace with a secure secret key

app.config['DEBUG'] = True
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

# Global store for in-flight and completed jobs keyed by domain
active_jobs = {}
active_jobs_lock = threading.Lock()

try:
    client = docker.from_env()
    logger.info("Docker client initialized successfully")
except Exception as e:
    logger.error(f"Failed to initialize Docker client: {e}")
    raise

class StepStatus(Enum):
    PENDING = 'PENDING'
    SUCCESS = 'SUCCESS'
    FAILURE = 'FAILURE'

def get_public_ip():
    try:
        return requests.get('https://api.ipify.org', timeout=5).text
    except requests.RequestException:
        return None

def reverse_lookup(ip):
    try:
        return socket.gethostbyaddr(ip)[0]
    except socket.herror:
        return None

def get_host_paths():
    """Resolve host filesystem paths from the GUI container's volume mounts."""
    try:
        gui_container = client.containers.get('gui')
        mounts = gui_container.attrs['Mounts']
        host_paths = {}
        for mount in mounts:
            dest = mount['Destination']
            src = mount['Source']
            if dest == '/nginx/conf':
                host_paths['nginx_conf'] = src
            elif dest == '/cert':
                # Derive cert subdirectory host paths from the parent /cert mount
                host_paths['cert_www'] = src + '/www'
                host_paths['cert_conf'] = src + '/conf'
                host_paths['cert_logs'] = src + '/logs'
        logger.info(f"Resolved host paths: {host_paths}")
        return host_paths
    except Exception as e:
        logger.warning(f"Could not resolve host paths from container mounts: {e}")
        return {}

def update_step_status(steps_status, step_key, status):
    status_value = status.value if isinstance(status, StepStatus) else status
    steps_status[step_key]['status'] = status_value

def start_ssl_process(domain, email, job_id):
    with active_jobs_lock:
        steps_status = active_jobs[job_id]
    try:
        logger.info(f"Starting SSL process for domain: {domain}, email: {email}")

        update_step_status(steps_status, 'nginx', StepStatus.PENDING)
        start_nginx_container(domain)
        update_step_status(steps_status, 'nginx', StepStatus.SUCCESS)

        update_step_status(steps_status, 'certbot', StepStatus.PENDING)
        request_certificate(domain, email)
        update_step_status(steps_status, 'certbot', StepStatus.SUCCESS)

        update_step_status(steps_status, 'nginx_config', StepStatus.PENDING)
        update_nginx_config(domain)
        update_step_status(steps_status, 'nginx_config', StepStatus.SUCCESS)

        update_step_status(steps_status, 'nginx_restart', StepStatus.PENDING)
        restart_nginx_container()
        update_step_status(steps_status, 'nginx_restart', StepStatus.SUCCESS)

        steps_status['complete'] = True
        logger.info(f"SSL process completed successfully for {domain}")
    except Exception as e:
        logger.error(f"SSL process failed for {domain}: {e}", exc_info=True)
        steps_status['error'] = str(e)
        for step in list(steps_status.keys()):
            if step in ['complete', 'error']:
                continue
            if steps_status[step]['status'] == StepStatus.PENDING.value:
                steps_status[step]['status'] = StepStatus.FAILURE.value

def start_nginx_container(domain):
    client.images.pull('nginx:alpine')

    os.makedirs('/cert/www', exist_ok=True)
    os.makedirs('/nginx/conf', exist_ok=True)

    nginx_conf = f"""server {{
    listen 80;
    server_name {domain};

    location / {{
        root /usr/share/nginx/html;
        index index.html index.htm;
    }}

    location /.well-known/acme-challenge/ {{
        root /var/www/certbot;
    }}
}}
"""
    with open('/nginx/conf/default.conf', 'w') as f:
        f.write(nginx_conf)

    try:
        existing = client.containers.get('nginx')
        logger.info("Removing existing nginx container...")
        existing.remove(force=True)
    except docker.errors.NotFound:
        pass

    host_paths = get_host_paths()
    volumes = {
        host_paths.get('nginx_conf', '/nginx/conf'): {'bind': '/etc/nginx/conf.d', 'mode': 'ro'},
        host_paths.get('cert_www', '/cert/www'):     {'bind': '/var/www/certbot',   'mode': 'ro'},
        host_paths.get('cert_conf', '/cert/conf'):   {'bind': '/etc/letsencrypt',   'mode': 'ro'},
    }

    logger.info(f"Starting nginx container with volumes: {volumes}")
    client.containers.run(
        'nginx:alpine',
        name='nginx',
        ports={'80/tcp': 80, '443/tcp': 443},
        volumes=volumes,
        detach=True,
        restart_policy={"Name": "unless-stopped"},
    )
    logger.info("Nginx container started")

def request_certificate(domain, email):
    client.images.pull('certbot/certbot')

    try:
        existing = client.containers.get('certbot')
        logger.info("Removing existing certbot container...")
        existing.remove(force=True)
    except docker.errors.NotFound:
        pass

    os.makedirs('/cert/conf', exist_ok=True)
    os.makedirs('/cert/www', exist_ok=True)
    os.makedirs('/cert/logs', exist_ok=True)

    email_arg = f'--email {email}' if email else '--register-unsafely-without-email'
    certbot_cmd = (
        f'certonly --webroot -w /var/www/certbot {email_arg} '
        f'--agree-tos -d {domain} --non-interactive'
    )
    logger.info(f"Running certbot: {certbot_cmd}")

    host_paths = get_host_paths()
    volumes = {
        host_paths.get('cert_conf', '/cert/conf'): {'bind': '/etc/letsencrypt',        'mode': 'rw'},
        host_paths.get('cert_www',  '/cert/www'):  {'bind': '/var/www/certbot',         'mode': 'rw'},
        host_paths.get('cert_logs', '/cert/logs'): {'bind': '/var/log/letsencrypt',     'mode': 'rw'},
    }

    logger.info(f"Starting certbot container with volumes: {volumes}")
    result = client.containers.run(
        'certbot/certbot',
        command=certbot_cmd,
        volumes=volumes,
        network_mode='host',
        detach=False,
        remove=True,
    )
    logger.info(f"Certbot output: {result.decode() if result else 'No output'}")

def update_nginx_config(domain):
    nginx_conf = f"""server {{
    listen 80;
    server_name {domain};
    return 301 https://$host$request_uri;
}}

server {{
    listen 443 ssl;
    server_name {domain};

    ssl_certificate     /etc/letsencrypt/live/{domain}/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/{domain}/privkey.pem;
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers HIGH:!aNULL:!MD5;

    location / {{
        root /usr/share/nginx/html;
        index index.html index.htm;
    }}
}}
"""
    with open('/nginx/conf/default.conf', 'w') as f:
        f.write(nginx_conf)

def restart_nginx_container():
    nginx_container = client.containers.get('nginx')
    nginx_container.exec_run('nginx -s reload')

@app.route('/', methods=['GET', 'POST'])
def index():
    public_ip = get_public_ip()
    reverse_domain = reverse_lookup(public_ip) if public_ip else None
    domain_options = [reverse_domain] if reverse_domain else []

    if request.method == 'POST':
        domain = request.form.get('domain', '').strip()
        email = request.form.get('email', '').strip()

        job_id = domain
        steps_status = {
            'nginx':        {'label': 'Starting Nginx container',            'status': StepStatus.PENDING.value},
            'certbot':      {'label': "Requesting Let's Encrypt certificate", 'status': StepStatus.PENDING.value},
            'nginx_config': {'label': 'Updating Nginx configuration',         'status': StepStatus.PENDING.value},
            'nginx_restart':{'label': 'Reloading Nginx',                      'status': StepStatus.PENDING.value},
            'complete': False,
            'error': None,
        }
        with active_jobs_lock:
            active_jobs[job_id] = steps_status

        threading.Thread(
            target=start_ssl_process,
            args=(domain, email, job_id),
            daemon=True,
        ).start()

        return render_template(
            'index.html',
            public_ip=public_ip,
            domain_options=domain_options,
            domain=domain,
            email=email,
            steps_status=steps_status,
            processing=True,
            job_id=job_id,
        )

    return render_template('index.html', public_ip=public_ip, domain_options=domain_options)

@app.route('/status')
def status():
    job_id = request.args.get('job_id', '')
    with active_jobs_lock:
        job = active_jobs.get(job_id)
    if job is None:
        return jsonify({'error': 'Job not found'}), 404
    return jsonify(job)

if __name__ == '__main__':
    logger.info("Starting Flask application on 0.0.0.0:8070")
    # use_reloader=False prevents the reloader from killing background threads
    app.run(host='0.0.0.0', port=8070, debug=True, use_reloader=False)
