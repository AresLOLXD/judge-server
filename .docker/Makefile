GIT_TAG ?= AddKarel
TAG ?= karel

.PHONY: all runtimes-tier1 runtimes-tier2 runtimes-tier3

all: runtimes-tier1 runtimes-tier2 runtimes-tier3

runtimes-tier1:
	cd tier1 && docker build --build-arg TAG="${GIT_TAG}" -t areslolxd/runtimes-tier1:$(TAG) .

runtimes-tier2:
	cd tier2 && docker build --build-arg TAG="${GIT_TAG}" -t areslolxd/runtimes-tier2:$(TAG) .

runtimes-tier3:
	cd tier3 && docker build --build-arg TAG="${GIT_TAG}" -t areslolxd/runtimes-tier3:$(TAG) .
