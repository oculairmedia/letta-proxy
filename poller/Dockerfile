FROM python:3.10-slim

WORKDIR /app

# Install basic requirements
RUN pip install --no-cache-dir requests python-dotenv

# Copy the application files
COPY list_letta_agents.py .
COPY config.py .

# Create state directory
RUN mkdir -p /app/state

# Run the poller script
CMD ["python", "list_letta_agents.py"]