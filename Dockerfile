# Freeciv-web docker file with LLM gateway support
# Simplified single-stage build matching working commit

FROM ubuntu:noble

MAINTAINER FCIV.NET : 3.3

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

# Install dependencies and build
# Using Ubuntu's stable tomcat10 package (10.1.16-1) instead of latest Apache version
RUN DEBIAN_FRONTEND=noninteractive sudo apt-get update --yes --quiet && \
    DEBIAN_FRONTEND=noninteractive PIP_SKIP=Y \
                                   install/install.sh --mode=TEST && \
    DEBIAN_FRONTEND=noninteractive sudo apt-get clean --yes && \
    sudo rm --recursive --force /var/lib/apt/lists/*

# Configure MySQL to allow passwordless root access over TCP
# Use mysqld --skip-grant-tables to bypass authentication
RUN sudo mkdir -p /var/run/mysqld && \
    sudo chown mysql:mysql /var/run/mysqld && \
    sudo mysqld --skip-grant-tables --skip-networking --user=mysql & \
    sleep 8 && \
    sudo mysql -u root -e "FLUSH PRIVILEGES; ALTER USER 'root'@'localhost' IDENTIFIED WITH mysql_native_password BY '';" && \
    sudo mysql -u root -e "FLUSH PRIVILEGES;" && \
    sudo pkill -9 mysqld && \
    sleep 2

# Install Python dependencies for freeciv-proxy and LLM Gateway
RUN pip install --break-system-packages python-dotenv && \
    cd /docker/llm-gateway && pip install --break-system-packages -r requirements.txt

# Copy nginx configuration from working commit
COPY config/nginx/sites-available/freeciv-web /etc/nginx/sites-available/freeciv-web
RUN sudo rm -f /etc/nginx/sites-enabled/default && \
    sudo ln -s /etc/nginx/sites-available/freeciv-web /etc/nginx/sites-enabled/freeciv-web

## Give server access to savegames / scenarios directory.
## TODO: Figure out more targeted solution.
RUN sudo adduser docker tomcat

COPY docker-entrypoint.sh /docker/docker-entrypoint.sh

EXPOSE 80 8080 8002 8003 4002 6000 6001 6002 6003 6004 6005 6006 6007 6008 6009 7000 7001 7002 7003 7004 7005 7006 7007 7008 7009

ENTRYPOINT ["/docker/docker-entrypoint.sh"]

CMD ["/bin/bash"]
