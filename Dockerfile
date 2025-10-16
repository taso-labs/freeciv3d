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
localedef -i en_US -c -f UTF-8 -A /usr/share/locale/locale.alias en_US.UTF
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
    ca-certificates \
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
    build-essential \
    ccache \
    && : \
ln -s ../../bin/ccache /usr/lib/ccache/cc && \
ln -s ../../bin/ccache /usr/lib/ccache/c++
EOF

USER docker

COPY --chown=docker:docker freeciv /freeciv
WORKDIR /freeciv

RUN --mount=type=cache,uid=1001,gid=1001,target=${CCACHE_DIR} \
    /freeciv/prepare_freeciv.sh && ninja -C build install

FROM docker-base

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
COPY .git /docker/.git
COPY freeciv /docker/freeciv
COPY freeciv-proxy /docker/freeciv-proxy
COPY freeciv-web /docker/freeciv-web
COPY publite2 /docker/publite2
COPY llm-gateway /docker/llm-gateway
COPY LICENSE.md /docker/LICENSE.md

COPY scripts /docker/scripts
COPY config /docker/config

RUN chown -R docker:docker /docker

# Make scripts executable
RUN chmod +x /docker/scripts/*.sh

USER docker

WORKDIR /docker/scripts/

COPY --from=freeciv-build --chown=docker:docker /home/docker/freeciv /home/docker/freeciv

# Install dependencies and build
# Using Ubuntu's stable tomcat10 package (10.1.16-1) instead of latest Apache version
RUN --mount=type=cache,uid=1001,gid=1001,target=/home/docker/.m2 \
    --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    <<EOF
set -e
sudo apt-get update --yes --quiet
PIP_SKIP=Y SKIP_FREECIV_BUILD=true \
    install/install.sh --mode=TEST
EOF

# Install Python dependencies for freeciv-proxy and LLM Gateway
WORKDIR /docker/llm-gateway
RUN --mount=type=cache,uid=1001,gid=1001,target=/home/docker/.cache/pip \
    --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    <<EOF
set -e
sudo apt-get update --yes --quiet
sudo apt-get install --yes python3-dotenv
pip install --break-system-packages -r requirements.txt
EOF

## Give server access to savegames / scenarios directory.
## TODO: Figure out more targeted solution.
RUN sudo usermod -a -G tomcat docker

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
