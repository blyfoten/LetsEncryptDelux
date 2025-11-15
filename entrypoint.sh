#!/bin/sh

# Start Docker daemon in the background
dockerd &

# Wait until Docker daemon is ready
echo "Waiting for Docker daemon to be ready..."
until docker info >/dev/null 2>&1; do
    sleep 1
done

echo "Docker daemon is ready. Starting the application..."

# Run the Flask application
python /app/app.py
