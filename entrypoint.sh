#!/bin/sh
set -e

echo "Installing Python dependencies..."
pip install --no-cache-dir flask docker requests > /dev/null 2>&1

echo "Starting Flask application..."
exec python /app/app.py
