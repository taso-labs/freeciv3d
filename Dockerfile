# Freeciv-web docker file with LLM gateway support
# Multi-stage build for better caching and ARM64 optimization

FROM ubuntu:noble AS base

MAINTAINER FCIV.NET : 3.3

# Build arguments for development
ARG SKIP_FREECIV_BUILD=false
ARG BUILD_JOBS=2

RUN DEBIAN_FRONTEND=noninteractive apt-get update --yes --quiet && \
    DEBIAN_FRONTEND=noninteractive apt-get install --yes \
        sudo \
        lsb-release \
        locales \
        adduser && \
    DEBIAN_FRONTEND=noninteractive apt-get clean --yes && \
    rm --recursive --force /var/lib/apt/lists/*

RUN DEBIAN_FRONTEND=noninteractive locale-gen en_US.UTF-8 && \
    localedef -i en_US -c -f UTF-8 -A /usr/share/locale/locale.alias en_US.UTF-8

ENV LANG en_US.UTF-8
ENV LANGUAGE en_US:en
ENV LC_ALL en_US.UTF-8

## Create user and ensure no passwd questions during scripts
RUN useradd -m docker && echo "docker:docker" | chpasswd && adduser docker sudo && \
    echo "docker ALL = (root) NOPASSWD: ALL\n" > /etc/sudoers.d/docker && \
    chmod 0440 /etc/sudoers.d/docker

# Stage 1: Dependencies and basic setup
FROM base AS dependencies

# Copy scripts, config, and required directories for build
COPY scripts /docker/scripts
COPY config /docker/config
COPY freeciv-web /docker/freeciv-web
COPY freeciv-proxy /docker/freeciv-proxy
COPY publite2 /docker/publite2

RUN chown -R docker:docker /docker && \
    chmod +x /docker/scripts/*.sh

USER docker
WORKDIR /docker/scripts/

# Install dependencies (this layer will be cached)
RUN DEBIAN_FRONTEND=noninteractive sudo apt-get update --yes --quiet && \
    DEBIAN_FRONTEND=noninteractive DEB_NO_TOMCAT=Y \
                                   PIP_SKIP=Y \
                                   install/install.sh --mode=TEST && \
    DEBIAN_FRONTEND=noninteractive sudo apt-get clean --yes && \
    sudo rm --recursive --force /var/lib/apt/lists/*

# Stage 2: FreeCiv compilation (heaviest layer - cached separately)
FROM dependencies AS freeciv-builder

# Copy FreeCiv source
COPY freeciv /docker/freeciv
RUN sudo chown -R docker:docker /docker/freeciv

# Build FreeCiv with optimization for ARM64
WORKDIR /docker/freeciv
RUN if [ "$SKIP_FREECIV_BUILD" = "false" ] ; then \
        echo "Building FreeCiv (this may take 20-30 minutes on ARM64)..." && \
        MAKEFLAGS="-j${BUILD_JOBS}" ./prepare_freeciv.sh ; \
    else \
        echo "Skipping FreeCiv build (SKIP_FREECIV_BUILD=true)" ; \
    fi

# Stage 3: Final runtime image
FROM dependencies AS runtime

# Copy FreeCiv build artifacts
COPY --from=freeciv-builder /docker/freeciv /docker/freeciv
COPY --from=freeciv-builder /home/docker/freeciv /home/docker/freeciv

# Copy remaining application files (main directories already copied in dependencies stage)
COPY .git /docker/.git
COPY LICENSE.md /docker/LICENSE.md

RUN sudo chown -R docker:docker /docker

## Give server access to savegames / scenarios directory.
## TODO: Figure out more targeted solution.
RUN sudo adduser docker tomcat

COPY docker-entrypoint.sh /docker/docker-entrypoint.sh

EXPOSE 80 8080 4002 6000 6001 6002 7000 7001 7002 8002


ENTRYPOINT ["/docker/docker-entrypoint.sh"]

CMD ["/bin/bash"]
