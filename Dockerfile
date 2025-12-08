# syntax=docker/dockerfile:1
# Freeciv-web docker file with LLM gateway support

FROM ubuntu:noble AS docker-base

ENV DEBIAN_FRONTEND=noninteractive \
    LANG=en_US.UTF-8 \
    LANGUAGE=en_US:en \
    LC_ALL=en_US.UTF-8

# https://docs.docker.com/reference/dockerfile/#example-cache-apt-packages
COPY <<keep-cache <<docker-clean /etc/apt/apt.conf.d/
Binary::apt::APT::Keep-Downloaded-Packages "true";
keep-cache
docker-clean

COPY --chmod=0440 <<EOF /etc/sudoers.d/docker
docker ALL = (root) NOPASSWD: ALL
EOF

## Create user and ensure no passwd questions during scripts
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    <<EOF
set -e
apt-get update
apt-get install -y --no-install-recommends locales openssl
useradd -m docker -G sudo -p $(openssl passwd -6 docker)
locale-gen en_US.UTF-8
localedef -i en_US -c -f UTF-8 -A /usr/share/locale/locale.alias en_US.UTF-8
EOF

FROM docker-base AS freeciv-build

ENV GIT_TERMINAL_PROMPT=0 \
    PATH=/usr/lib/ccache:/root/.local/bin:$PATH \
    CFLAGS="-O3 -pipe" \
    CXXFLAGS="-O3 -pipe" \
    LDFLAGS="-O3 -pipe" \
    CCACHE_DIR="/home/docker/ccache"

RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    <<EOF
set -e
apt-get update
apt-get install -y --no-install-recommends \
    binutils \
    build-essential \
    ca-certificates \
    ccache \
    libbz2-dev \
    libcurl4-openssl-dev \
    libicu-dev \
    libjansson-dev \
    liblzma-dev \
    libsqlite3-dev \
    libtool \
    libzstd-dev \
    meson \
    ninja-build \
    pkgconf \
    python3 \
    zlib1g-dev \
    && :
ln -s ../../bin/ccache /usr/lib/ccache/cc
ln -s ../../bin/ccache /usr/lib/ccache/c++
EOF

USER docker

COPY --chown=docker:docker freeciv /freeciv
WORKDIR /freeciv

# Build and install freeciv, then clean up build artifacts
RUN --mount=type=cache,uid=1001,gid=1001,target=${CCACHE_DIR} \
    <<EOF
set -e
/freeciv/prepare_freeciv.sh
ninja -C build install
strip --strip-unneeded /home/docker/freeciv/bin/*
rm -rf /freeciv/build
EOF

FROM docker-base AS tomcat-builder

MAINTAINER FCIV.NET : 3.3

RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    <<EOF
set -e
apt-get update --yes --quiet
apt-get install --yes \
    sudo \
    lsb-release \
    && :
EOF

## Add relevant content
COPY --chown=docker:docker freeciv /docker/freeciv
COPY --chown=docker:docker freeciv-proxy /docker/freeciv-proxy
COPY --chown=docker:docker freeciv-web /docker/freeciv-web
COPY --chown=docker:docker publite2 /docker/publite2
COPY --chown=docker:docker llm-gateway /docker/llm-gateway
COPY --chown=docker:docker LICENSE.md /docker/LICENSE.md
COPY --chown=docker:docker --chmod=755 scripts /docker/scripts
COPY --chown=docker:docker config /docker/config
COPY --from=freeciv-build --chown=docker:docker /home/docker/freeciv/bin /home/docker/freeciv/bin
COPY --from=freeciv-build --chown=docker:docker /home/docker/freeciv/etc /home/docker/freeciv/etc
COPY --from=freeciv-build --chown=docker:docker /home/docker/freeciv/share/freeciv /home/docker/freeciv/share/freeciv
COPY --from=freeciv-build --chown=docker:docker /home/docker/freeciv/share/icons /home/docker/freeciv/share/icons

USER docker
WORKDIR /docker/scripts/

ENV SKIP_FREECIV_BUILD=true

# Cache Maven dependencies separately for better layer reuse
RUN --mount=type=cache,uid=1001,gid=1001,target=/home/docker/.m2 \
    --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    <<EOF
set -e
sudo apt-get update --yes --quiet
sudo apt-get install --yes --no-install-recommends maven
cd /docker/freeciv-web
mvn dependency:resolve || true
EOF

# Install dependencies and build
# Using Ubuntu's stable tomcat10 package (10.1.16-1) instead of latest Apache version
RUN --mount=type=cache,uid=1001,gid=1001,target=/home/docker/.m2 \
    --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    <<EOF
set -e
sudo apt-get update --yes --quiet
install/install.sh --mode=TEST
# Clean up build artifacts after Maven build and other files
sudo rm -rf /var/lib/tomcat10/webapps/{docs,examples,host-manager,manager}
rm -rf /docker/freeciv-web/target /docker/freeciv-web/src install.log /docker/*/tests /docker/*/test
EOF

FROM docker-base AS final

COPY --from=tomcat-builder --chown=docker:docker /docker/config /docker/config
COPY --from=tomcat-builder --chown=docker:docker /docker/freeciv-proxy /docker/freeciv-proxy
COPY --from=tomcat-builder --chown=docker:docker /docker/freeciv-web/*.sh /docker/freeciv-web/
COPY --from=tomcat-builder --chown=docker:docker /docker/LICENSE.md /docker/LICENSE.md
COPY --from=tomcat-builder --chown=docker:docker /docker/publite2 /docker/publite2
COPY --from=tomcat-builder --chown=docker:docker /docker/scripts /docker/scripts

# Copy requirements.txt first for better caching
COPY --from=tomcat-builder --chown=docker:docker /docker/llm-gateway/requirements.txt /docker/llm-gateway/requirements.txt

# Install system dependencies
WORKDIR /docker/llm-gateway
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    <<EOF
set -e
apt-get update --yes --quiet
apt-get install -y --no-install-recommends \
    curl \
    libicu74 \
    libjansson4 \
    python3-dotenv \
    python3-pip \
    python3-tornado \
    sudo \
    tomcat10 \
    && :
## Give server access to savegames / scenarios directory.
## TODO: Figure out more targeted solution.
usermod -a -G tomcat docker
# Remove documentation, saves 1691975 bytes
rm -rf /usr/share/doc/* /usr/share/man/* /usr/share/locale/*
EOF

# Install Python dependencies in separate layer for better caching
RUN --mount=type=cache,uid=1001,gid=1001,target=/root/.cache/pip \
    pip install --break-system-packages -r requirements.txt

# Copy remaining llm-gateway files
COPY --from=tomcat-builder --chown=docker:docker /docker/llm-gateway /docker/llm-gateway

COPY --from=tomcat-builder --chown=docker:docker /home/docker /home/docker
COPY --from=tomcat-builder --chown=tomcat:tomcat /usr/share/tomcat10 /usr/share/tomcat10
COPY --from=tomcat-builder --chown=tomcat:tomcat /var/lib/tomcat10 /var/lib/tomcat10

USER docker

COPY docker-entrypoint.sh /docker/docker-entrypoint.sh

# civsockets ports
EXPOSE 7000-7009

# Freeciv-web port
EXPOSE 8080

# pubstatus port
EXPOSE 4002

# PBEM port
EXPOSE 4003

# State Extraction Service Port
EXPOSE 8002

# LLM Gateway port
EXPOSE 8003

ENTRYPOINT ["/docker/docker-entrypoint.sh"]

CMD ["/bin/bash"]
