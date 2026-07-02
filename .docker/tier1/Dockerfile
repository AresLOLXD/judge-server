FROM dmoj/runtimes-tier1

# Install Node.js (needed by the rekarel CLI compiler) and build the ReKarel C++ VM
RUN apt-get update && \
	apt-get install -y --no-install-recommends make libexpat1-dev gnupg && \
	mkdir -p /etc/apt/keyrings && \
	curl -fsSL https://deb.nodesource.com/gpgkey/nodesource-repo.gpg.key | gpg --dearmor -o /etc/apt/keyrings/nodesource.gpg && \
	echo 'deb [signed-by=/etc/apt/keyrings/nodesource.gpg] https://deb.nodesource.com/node_20.x nodistro main' > /etc/apt/sources.list.d/nodesource.list && \
	apt-get update && \
	apt-get install -y --no-install-recommends nodejs && \
	npm install -g @rekarel/cli && \
	curl -L https://github.com/kishtarn555/rekarel-cpp-interpreter/archive/refs/tags/v2.3.1.tar.gz | tar -xz && \
	cd rekarel-cpp-interpreter-2.3.1 && mkdir bin && make karel && install -m 755 bin/karel /usr/local/bin/karel && cd .. && \
	rm -rf rekarel-cpp-interpreter-2.3.1 && \
	apt-get clean && rm -rf /var/lib/apt/lists/*

ARG TAG=AddKarel
RUN mkdir /judge /problems && cd /judge && \
	curl -L https://github.com/AresLOLXD/judge-server/archive/"${TAG}".tar.gz | tar -xz --strip-components=1 && \
    python3 -m venv --prompt=DMOJ /env && \
	/env/bin/pip3 install cython setuptools && \
	/env/bin/pip3 install -e . && \
	/env/bin/python3 setup.py develop && \
	HOME=~judge . ~judge/.profile && \
	runuser -u judge -w PATH -- /env/bin/dmoj-autoconf -V > /judge-runtime-paths.yml && \
	echo '  crt_x86_in_lib32: true' >> /judge-runtime-paths.yml

ENTRYPOINT ["/usr/bin/tini", "--", "/judge/.docker/entry"]
