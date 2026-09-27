FROM python:3.11.11-slim-bookworm
ARG DEBIAN_SNAPSHOT=20250224T000000Z
RUN rm -f /etc/apt/sources.list.d/debian.sources && \
    printf 'deb [check-valid-until=no] http://snapshot.debian.org/archive/debian/%s bookworm main\n' "$DEBIAN_SNAPSHOT" > /etc/apt/sources.list && \
    apt-get update && apt-get install -y --no-install-recommends openssh-client rsync tmux iproute2 fonts-dejavu-core ca-certificates procps texlive-latex-extra texlive-fonts-recommended cm-super-minimal dvipng && \
    rm -rf /var/lib/apt/lists/*
COPY testbed/requirements.lock.txt /tmp/requirements.lock.txt
RUN pip install --no-cache-dir -r /tmp/requirements.lock.txt
ARG ARTIFACT_UID=1000
ARG ARTIFACT_GID=1000
RUN groupadd -g "$ARTIFACT_GID" artifact && useradd -m -u "$ARTIFACT_UID" -g "$ARTIFACT_GID" artifact
COPY --chown=artifact:artifact testbed /opt/artifact/testbed
COPY --chown=artifact:artifact plot/lib /opt/artifact/plot/lib
ARG PROJECT_VERSION=unknown
ARG PERFTEST_COMMIT
ENV PROJECT_VERSION=$PROJECT_VERSION PERFTEST_COMMIT=$PERFTEST_COMMIT \
    PYTHONPATH=/opt/artifact/testbed:/opt/artifact/testbed/utils:/opt/artifact/testbed/scripts:/opt/artifact/plot \
    MPLBACKEND=Agg PYTHONUNBUFFERED=1
WORKDIR /opt/artifact/testbed
USER artifact
CMD ["sleep", "infinity"]
