
FROM ubuntu:22.04

ARG UID=1000
ARG GID=1000

# install dependencies
RUN apt-get update && apt-get install -y \
  build-essential \
  && apt-get clean && rm -rf "/var/lib/apt/lists/*"

# create a non-root user
RUN groupadd -g ${GID} ubuntu && useradd -u ${UID} -g ${GID} ubuntu

USER ubuntu

WORKDIR /app
