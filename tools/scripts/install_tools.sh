#!/bin/bash
# Install Docker and Docker Compose
echo "Installing Docker and tools..."
sudo apt update
sudo apt install -y docker.io docker-compose python3-venv npm

# Add user to docker group
echo "Adding user to docker group..."
sudo usermod -aG docker $USER

echo "Installation complete. You may need to log out and log back in for docker group changes to take effect."
