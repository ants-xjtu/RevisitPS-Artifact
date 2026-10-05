FROM ubuntu:24.04
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends python3 python3-venv openssh-client rsync tmux iproute2 fonts-dejavu-core ca-certificates procps build-essential libibverbs-dev librdmacm-dev libudev1 libcap2 zlib1g libnuma1 pkg-config texlive-latex-extra texlive-fonts-recommended cm-super-minimal dvipng && \
    rm -rf /var/lib/apt/lists/*
# Exact vendor MPI exported from the deployment's launcher by export_mpi_toolchain.py.
COPY testbed/build/mpi-toolchain/ /tmp/mpi-toolchain/
RUN cd /tmp/mpi-toolchain && sha256sum -c SHA256SUMS > /dev/null && \
    mkdir -p /usr/mpi/gcc && mv openmpi-4.1.7rc1 /usr/mpi/gcc/ && \
    rm -rf /tmp/mpi-toolchain && \
    /usr/mpi/gcc/openmpi-4.1.7rc1/bin/mpicxx --showme:version
RUN python3 -m venv /opt/venv
ENV PATH=/opt/venv/bin:/usr/mpi/gcc/openmpi-4.1.7rc1/bin:$PATH
COPY testbed/docker/requirements.lock.txt /tmp/requirements.lock.txt
RUN pip install --no-cache-dir -r /tmp/requirements.lock.txt
ARG ARTIFACT_UID=1000
ARG ARTIFACT_GID=1000
RUN groupadd -g "$ARTIFACT_GID" artifact && useradd -m -u "$ARTIFACT_UID" -g "$ARTIFACT_GID" artifact && \
    install -d -m 0700 -o artifact -g artifact /home/artifact/.ssh
COPY --chown=artifact:artifact testbed /opt/artifact/testbed
COPY --chown=artifact:artifact plot/lib /opt/artifact/plot/lib
RUN install -d -o artifact -g artifact /opt/artifact/testbed/results
ARG PROJECT_VERSION=unknown
ARG PERFTEST_COMMIT
ENV PROJECT_VERSION=$PROJECT_VERSION PERFTEST_COMMIT=$PERFTEST_COMMIT \
    PYTHONPATH=/opt/artifact/testbed:/opt/artifact/plot \
    MPLBACKEND=Agg PYTHONUNBUFFERED=1
WORKDIR /opt/artifact/testbed
USER artifact
CMD ["sleep", "infinity"]
