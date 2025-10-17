# Use an official lightweight Python image as a parent image
FROM python:3.12-slim

# Set the working directory inside the container
WORKDIR /app

# Install system dependencies needed for the mariadb Python package
# - apt-get update: Refreshes package lists
# - libmariadb-dev & gcc: Required to build the mariadb package from source
# - --no-install-recommends: Reduces image size by skipping optional packages
# - rm -rf /var/lib/apt/lists/*: Cleans up apt cache to keep image small
RUN apt-get update && \
    apt-get install -y --no-install-recommends libmariadb-dev gcc && \
    rm -rf /var/lib/apt/lists/*

# Copy the dependencies file to the working directory
COPY requirements.txt .

# Install any needed packages specified in requirements.txt
# --no-cache-dir reduces image size
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application's code to the working directory
COPY . .

# Specify the command to run on container startup
CMD ["python", "bot.py"]