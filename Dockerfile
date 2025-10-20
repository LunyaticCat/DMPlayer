# Use an official lightweight Python image as a parent image
FROM python:3.12-slim

# Set the working directory inside the container
WORKDIR /app

# Install system dependencies
# - libmariadb-dev & gcc: Required for the mariadb Python package
# - ffmpeg: Required for the pydub Python package
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    libmariadb-dev \
    gcc \
    ffmpeg && \
    rm -rf /var/lib/apt/lists/*

# Copy the dependencies file to the working directory
COPY requirements.txt .

# Install any needed packages specified in requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application's code to the working directory
COPY . .

# Specify the command to run on container startup
CMD ["python", "bot.py"]