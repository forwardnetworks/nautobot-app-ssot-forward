# Local test/dev image: selected official Nautobot release + this plugin
# (editable) + the test toolchain. CI supplies both supported release lines.
ARG NAUTOBOT_VERSION=3.2.2
ARG PYTHON_VERSION=3.12
FROM ghcr.io/nautobot/nautobot:${NAUTOBOT_VERSION}-py${PYTHON_VERSION}

USER 0
WORKDIR /source

# Install the plugin (editable) + its deps, plus the test toolchain. The source is
# also bind-mounted at runtime (see docker-compose.yml) so code edits are live.
COPY . /source
RUN pip install --no-cache-dir -e . \
    && pip install --no-cache-dir pytest pytest-django ruff

ENV NAUTOBOT_CONFIG=/source/nautobot_config.py \
    DJANGO_SETTINGS_MODULE=nautobot_config \
    PYTHONDONTWRITEBYTECODE=1

USER nautobot
