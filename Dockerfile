# Use a maintained Python slim image as the base
FROM python:3.11-slim-bookworm

# Install required system packages and dependencies
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        gnupg2 \
        lsb-release \
        tini \
        iproute2 \
        iputils-ping \
        procps \
        net-tools \
        nano \
        docker.io && \
    rm -rf /var/lib/apt/lists/*

# Adjust Docker init script to avoid hard ulimit requirement
RUN sed -i 's/ulimit -Hn/ ulimit -n/g' /etc/init.d/docker

# Install Python packages
RUN pip install flask docker requests

# Copy application files into the container
COPY entrypoint.sh /entrypoint.sh

# Make entrypoint.sh executable
RUN chmod +x /entrypoint.sh

# Expose ports
EXPOSE 8070 80 443

# Set working directory
WORKDIR /app

# Set the entrypoint
ENTRYPOINT ["/usr/bin/tini", "--", "/entrypoint.sh"]
