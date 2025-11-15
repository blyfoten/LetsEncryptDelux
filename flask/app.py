from flask import Flask, render_template, request, redirect, url_for, flash
import os
import requests
import socket
import docker
import threading
from enum import Enum

app = Flask(__name__)
app.secret_key = 'your_secret_key'  # Replace with a secure secret key

# Initialize Docker client
client = docker.DockerClient(base_url='unix://var/run/docker.sock')

class StepStatus(Enum):
    PENDING = 'PENDING'
    SUCCESS = 'SUCCESS'
    FAILURE = 'FAILURE'

def get_public_ip():
    try:
        return requests.get('https://api.ipify.org').text
    except requests.RequestException:
        return None

def reverse_lookup(ip):
    try:
        return socket.gethostbyaddr(ip)[0]
    except socket.herror:
        return None

def start_ssl_process(domain, email, steps_status):
    try:
        # Step 1: Start Nginx container with sample HTTP config
        update_step_status(steps_status, 'nginx', StepStatus.PENDING)
        start_nginx_container(domain)
        update_step_status(steps_status, 'nginx', StepStatus.SUCCESS)

        # Step 2: Request Let's Encrypt certificate
        update_step_status(steps_status, 'certbot', StepStatus.PENDING)
        request_certificate(domain, email)
        update_step_status(steps_status, 'certbot', StepStatus.SUCCESS)

        # Step 3: Update Nginx configuration for HTTPS
        update_step_status(steps_status, 'nginx_config', StepStatus.PENDING)
        update_nginx_config(domain)
        update_step_status(steps_status, 'nginx_config', StepStatus.SUCCESS)

        # Step 4: Restart Nginx container
        update_step_status(steps_status, 'nginx_restart', StepStatus.PENDING)
        restart_nginx_container()
        update_step_status(steps_status, 'nginx_restart', StepStatus.SUCCESS)

        steps_status['complete'] = True
    except Exception as e:
        steps_status['error'] = str(e)
        # Mark any pending steps as failed
        for step in steps_status:
            if step in ['complete', 'error']:
                continue  # Skip non-step keys
            if steps_status[step]['status'] == StepStatus.PENDING:
                steps_status[step]['status'] = StepStatus.FAILURE


def update_step_status(steps_status, step_key, status):
    steps_status[step_key]['status'] = status

def start_nginx_container(domain):
    # Pull Nginx image
    client.images.pull('nginx:alpine')

    # Create necessary directories
    os.makedirs('/cert/www', exist_ok=True)
    os.makedirs('/nginx/conf', exist_ok=True)

    # Create Nginx HTTP configuration
    nginx_conf = f"""
server {{
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

    # Write Nginx configuration to file
    with open('/nginx/conf/default.conf', 'w') as f:
        f.write(nginx_conf)

    # Run Nginx container
    client.containers.run(
        'nginx:alpine',
        name='nginx',
        ports={'80/tcp': 80, '443/tcp': 443},
        volumes={
            '/nginx/conf': {'bind': '/etc/nginx/conf.d', 'mode': 'ro'},
            '/cert/www': {'bind': '/var/www/certbot', 'mode': 'ro'},
            '/cert/conf': {'bind': '/etc/letsencrypt', 'mode': 'ro'},
        },
        detach=True,
        restart_policy={"Name": "unless-stopped"},
    )

def request_certificate(domain, email):
    # Pull Certbot image
    client.images.pull('certbot/certbot')

    # Build Certbot command
    email_arg = f'--email {email}' if email else '--register-unsafely-without-email'

    # Run Certbot container
    client.containers.run(
        'certbot/certbot',
        name='certbot',
        command=f'certonly --webroot -w /var/www/certbot {email_arg} --agree-tos -d {domain} --non-interactive',
        volumes={
            '/cert/conf': {'bind': '/etc/letsencrypt', 'mode': 'rw'},
            '/cert/www': {'bind': '/var/www/certbot', 'mode': 'rw'},
            '/cert/logs': {'bind': '/var/log/letsencrypt', 'mode': 'rw'},

        },
        network_mode='host',
        detach=False,
        remove=True,
    )

def update_nginx_config(domain):
    # Update Nginx configuration for HTTPS
    nginx_conf = f"""
server {{
    listen 80;
    server_name {domain};
    return 301 https://$host$request_uri;
}}

server {{
    listen 443 ssl;
    server_name {domain};

    ssl_certificate /etc/letsencrypt/live/{domain}/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/{domain}/privkey.pem;
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers HIGH:!aNULL:!MD5;

    location / {{
        root /usr/share/nginx/html;
        index index.html index.htm;
    }}
}}
"""

    # Write updated Nginx configuration to file
    with open('/nginx/conf/default.conf', 'w') as f:
        f.write(nginx_conf)

def restart_nginx_container():
    nginx_container = client.containers.get('nginx')

    # Create the directory /etc/letsencrypt in the Nginx container
    #nginx_container.exec_run('mkdir -p /etc/letsencrypt/live')

    # Copy certificates to Nginx container
    #copy_certs_to_nginx(nginx_container)

    # Reload Nginx configuration
    nginx_container.exec_run('nginx -s reload')


def copy_certs_to_nginx(nginx_container):
    import tarfile
    import io

    certs_path = '/cert/conf/live'
    for domain in os.listdir(certs_path):
        domain_path = os.path.join(certs_path, domain)
        data = io.BytesIO()
        with tarfile.open(fileobj=data, mode='w') as tar:
            tar.add(domain_path, arcname=f'live/{domain}')
        data.seek(0)
        nginx_container.put_archive('/etc/letsencrypt', data.read())

@app.route('/', methods=['GET', 'POST'])
def index():
    public_ip = get_public_ip()
    reverse_domain = reverse_lookup(public_ip) if public_ip else None
    domain_options = [reverse_domain] if reverse_domain else []

    if request.method == 'POST':
        domain = request.form.get('domain')
        email = request.form.get('email')
        steps_status = {
            'nginx': {'label': 'Starting Nginx container', 'status': StepStatus.PENDING},
            'certbot': {'label': 'Requesting Let\'s Encrypt certificate', 'status': StepStatus.PENDING},
            'nginx_config': {'label': 'Updating Nginx configuration', 'status': StepStatus.PENDING},
            'nginx_restart': {'label': 'Restarting Nginx container', 'status': StepStatus.PENDING},
            'complete': False,
            'error': None
        }

        # Start SSL process in a separate thread
        threading.Thread(target=start_ssl_process, args=(domain, email, steps_status)).start()

        return render_template('index.html', public_ip=public_ip, domain_options=domain_options,
                               domain=domain, email=email, steps_status=steps_status, processing=True)

    return render_template('index.html', public_ip=public_ip, domain_options=domain_options)

@app.route('/status')
def status():
    # Implement a way to retrieve and send the current status of the SSL process
    # For simplicity, this could be stored in a session or a temporary file
    return {}

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8070)
