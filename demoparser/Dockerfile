# Use multi-stage build with uv's official image
FROM ghcr.io/astral-sh/uv:latest as uv

FROM python:3.12-slim-bookworm

# Set the source repository
LABEL org.opencontainers.image.source=https://github.com/Asgerspange/refactored-octo-succotash

# Set the working directory to /demoparser
WORKDIR /demoparser

# Install system dependencies
RUN apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/*

# Copy uv from the uv image
COPY --from=uv /uv /usr/local/bin/uv

# Set uv environment variables
ENV UV_LINK_MODE=copy
ENV UV_COMPILE_BYTECODE=1

# Copy the project files into the container
COPY ./pyproject.toml /demoparser/
COPY ./.python-version /demoparser/
COPY ./main.py /demoparser/
COPY ./helpers.py /demoparser/
COPY ./config.py /demoparser/
COPY ./demo_processor.py /demoparser/
COPY ./demo_service.py /demoparser/
COPY ./SafeJSONEncoder.py /demoparser/
COPY ./antistrat_analyzer.py /demoparser/
COPY ./spatial_processor.py /demoparser/
COPY ./post_processor.py /demoparser/

# Create virtual environment and install dependencies
RUN uv venv .venv && \
    uv pip install --no-cache .

# Set the virtual environment in PATH
ENV PATH="/demoparser/.venv/bin:$PATH"
ENV VIRTUAL_ENV="/demoparser/.venv"

# Create the .env file
RUN touch .env

# Command to run the application
CMD ["python", "main.py"]