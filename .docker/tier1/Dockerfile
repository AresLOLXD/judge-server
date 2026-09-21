FROM docker.io/dmoj/runtimes-tier1 AS karel-builder

# make/libexpat1-dev are only needed to build the karel binary, not at
# runtime, so they're confined to this builder stage
RUN apt-get update && \
	apt-get install -y --no-install-recommends make libexpat1-dev && \
	curl -L https://github.com/kishtarn555/rekarel-cpp-interpreter/archive/refs/tags/v2.3.1.tar.gz | tar -xz && \
	cd rekarel-cpp-interpreter-2.3.1 && mkdir bin && \
	sed -i '1i #include <cstdint>' util.h && \
	make karel CFLAGS="-Wall -fno-exceptions" && \
	strip bin/karel

FROM docker.io/dmoj/runtimes-tier1

# Install Node.js (needed by the rekarel CLI compiler) and libexpat1
# (karel links against it dynamically)
RUN apt-get update && \
	apt-get install -y --no-install-recommends libexpat1 nodejs npm && \
	npm install -g @rekarel/cli && \
	npm cache clean --force && \
	apt-get clean && rm -rf /var/lib/apt/lists/*
COPY --from=karel-builder /rekarel-cpp-interpreter-2.3.1/bin/karel /usr/local/bin/karel
RUN chmod 755 /usr/local/bin/karel

ARG TAG=AddKarel
RUN mkdir /judge /problems && cd /judge && \
	curl -L https://github.com/AresLOLXD/judge-server/archive/"${TAG}".tar.gz | tar -xz --strip-components=1 && \
    python3 -m venv --prompt=DMOJ /env && \
	/env/bin/pip3 install --no-cache-dir cython setuptools && \
	/env/bin/pip3 install --no-cache-dir -e . && \
	/env/bin/python3 setup.py develop && \
	HOME=~judge . ~judge/.profile && \
	runuser -u judge -w PATH -- /env/bin/dmoj-autoconf -V > /judge-runtime-paths.yml && \
	echo '  crt_x86_in_lib32: true' >> /judge-runtime-paths.yml

ENTRYPOINT ["/usr/bin/tini", "--", "/judge/.docker/entry"]
