# Local test/dev image: official Nautobot 3.1.6 + this plugin (editable) + the
# pytest toolchain, so the full suite (contrib / API / crypto tests that skip
# without a real Nautobot) runs in a container instead of on a remote box.
FROM ghcr.io/nautobot/nautobot:3.1.6-py3.12

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
