# Use the official Python 3.9 slim-buster image as the base
FROM python:3.9-slim-buster

# Install required system packages and dependencies
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        apt-transport-https \
        ca-certificates \
        curl \
        gnupg2 \
        lsb-release \
        software-properties-common \
        tini \
        iproute2 \
        iputils-ping \
        procps \
        net-tools \
        nano

# Install Docker inside the container
RUN curl -fsSL https://download.docker.com/linux/debian/gpg | apt-key add - && \
    add-apt-repository \
        "deb [arch=amd64] https://download.docker.com/linux/debian \
        $(lsb_release -cs) stable" && \
    apt-get update && \
    apt-get install -y --no-install-recommends docker-ce docker-ce-cli containerd.io && \
    sed -i 's/ulimit -Hn/ ulimit -n/g' /etc/init.d/docker

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
