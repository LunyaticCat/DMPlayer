#!/usr/bin/env bash
set -e

# Load environment variables from .env
if [ -f .env ]; then
  export $(grep -v '^#' .env | xargs)
else
  echo ".env file not found. Exiting."
  exit 1
fi

# Configuration
NETWORK_NAME="bot-network"
DB_VOLUME="db_data"
DB_CONTAINER="db"
BOT_CONTAINER="bot"
DB_IMAGE="mariadb:10.6"
BOT_IMAGE="discord-bot:latest"

# Create network and volume if they don't exist
if ! podman network exists $NETWORK_NAME; then
  echo "Creating network $NETWORK_NAME..."
  podman network create $NETWORK_NAME
fi

if ! podman volume exists $DB_VOLUME; then
  echo "Creating volume $DB_VOLUME..."
  podman volume create $DB_VOLUME
fi

# Stop and remove old containers if they exist
if podman container exists $DB_CONTAINER; then
  echo "Removing old database container..."
  podman rm -f $DB_CONTAINER
fi

if podman container exists $BOT_CONTAINER; then
  echo "Removing old bot container..."
  podman rm -f $BOT_CONTAINER
fi

# Start MariaDB
echo "Starting MariaDB..."
podman run -d \
  --name $DB_CONTAINER \
  --restart=always \
  --network $NETWORK_NAME \
  -e MARIADB_ROOT_PASSWORD=$DB_ROOT_PASSWORD \
  -e MARIADB_DATABASE=$DB_DATABASE \
  -e MARIADB_USER=$DB_USER \
  -e MARIADB_PASSWORD=$DB_PASSWORD \
  -v $DB_VOLUME:/var/lib/mysql \
  -p 3307:3306 \
  $DB_IMAGE

# Wait for the database to be ready by actively polling it
echo "Waiting for MariaDB to be ready..."
until podman exec $DB_CONTAINER mysqladmin ping --user=root --password=$DB_ROOT_PASSWORD --silent; do
    echo "MariaDB is unavailable - sleeping for 2 seconds..."
    sleep 2
done
echo "MariaDB is ready! Proceeding..."

# Build bot image
echo "Building bot image..."
podman build -t $BOT_IMAGE .

# Start the bot
echo "Starting Discord bot..."
podman run -d \
  --name $BOT_CONTAINER \
  --restart=always \
  --network $NETWORK_NAME \
  --env-file .env \
  $BOT_IMAGE

echo "✅ All containers are running successfully!"
echo ""
podman ps --format "table {{.Names}}\t{{.Status}}\t{{.Image}}"
