FROM ubuntu:latest

ENV DEBIAN_FRONTEND=noninteractive
ENV LANG=en_US.UTF-8
ENV LANGUAGE=en_US:en
ENV LC_ALL=en_US.UTF-8
ENV TZ=America/Los_Angeles
ENV RUN_API_SOLVER=true
ENV DEBUG=true

# Install system packages in one layer
RUN apt-get update && \
    apt-get -y upgrade && \
    apt-get install -y --no-install-recommends \
    tzdata \
    locales \
    git \
    curl \
    wget \
    screen \
    sudo \
    xrdp \
    xfce4 \
    xorgxrdp \
    dbus-x11 \
    xfce4-terminal \
    python3-pip \
    ca-certificates \
    xvfb \
    firefox && \
    apt remove -y light-locker xscreensaver && \
    apt autoremove -y && \
    rm -rf /var/cache/apt /var/lib/apt/lists/*

# Configure locale
RUN sed -i '/en_US.UTF-8/s/^# //g' /etc/locale.gen && \
    locale-gen && \
    ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && \
    echo $TZ > /etc/timezone && \
    echo "LC_ALL=en_US.UTF-8" >> /etc/environment && \
    echo "en_US.UTF-8 UTF-8" >> /etc/locale.gen && \
    echo "LANG=en_US.UTF-8" > /etc/locale.conf && \
    locale-gen en_US.UTF-8

# Install Google Chrome
RUN wget https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb && \
    apt-get update && \
    apt-get install -y ./google-chrome-stable_current_amd64.deb && \
    rm ./google-chrome-stable_current_amd64.deb && \
    rm -rf /var/cache/apt /var/lib/apt/lists/*

# Set up user and directories
RUN mkdir -p /root/Desktop && \
    echo "root:root" | chpasswd

# Clone repository and install Python dependencies
WORKDIR /root/Desktop
RUN git clone https://github.com/riley-access-labs/Turnstile-Solver.git

WORKDIR /root/Desktop/Turnstile-Solver

# Copy requirements and install Python packages
RUN pip3 install -r requirements.txt --break-system-packages

# Fetch camoufox
RUN python3 -m camoufox fetch

COPY ./run.sh /usr/bin/
RUN chmod +x /usr/bin/run.sh

EXPOSE 3389
ENTRYPOINT ["/usr/bin/run.sh"]
