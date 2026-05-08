VERSION ?= 4.0.0-dev
COMMIT  := $(shell git -C $(CURDIR) rev-parse --short HEAD 2>/dev/null || echo dev)
LDFLAGS := -s -w -X main.Version=$(VERSION)+$(COMMIT)

GO ?= go
BIN := build/bin

.PHONY: all tidy lint test build agent watchdog \
        linux-amd64 linux-arm64 windows-amd64 darwin-arm64 \
        all-platforms clean

all: tidy build

tidy:
	$(GO) mod tidy

lint:
	$(GO) vet ./...

test:
	$(GO) test ./...

build: agent watchdog

agent:
	mkdir -p $(BIN)
	CGO_ENABLED=0 $(GO) build -trimpath -ldflags '$(LDFLAGS)' -o $(BIN)/nocagent ./cmd/agent

watchdog:
	mkdir -p $(BIN)
	CGO_ENABLED=0 $(GO) build -trimpath -ldflags '$(LDFLAGS)' -o $(BIN)/nocwatchdog ./cmd/watchdog

# Cross-compile targets — single static binaries, no CGO.
linux-amd64:
	mkdir -p $(BIN)/linux-amd64
	GOOS=linux GOARCH=amd64 CGO_ENABLED=0 $(GO) build -trimpath -ldflags '$(LDFLAGS)' -o $(BIN)/linux-amd64/nocagent ./cmd/agent
	GOOS=linux GOARCH=amd64 CGO_ENABLED=0 $(GO) build -trimpath -ldflags '$(LDFLAGS)' -o $(BIN)/linux-amd64/nocwatchdog ./cmd/watchdog

linux-arm64:
	mkdir -p $(BIN)/linux-arm64
	GOOS=linux GOARCH=arm64 CGO_ENABLED=0 $(GO) build -trimpath -ldflags '$(LDFLAGS)' -o $(BIN)/linux-arm64/nocagent ./cmd/agent
	GOOS=linux GOARCH=arm64 CGO_ENABLED=0 $(GO) build -trimpath -ldflags '$(LDFLAGS)' -o $(BIN)/linux-arm64/nocwatchdog ./cmd/watchdog

windows-amd64:
	mkdir -p $(BIN)/windows-amd64
	GOOS=windows GOARCH=amd64 CGO_ENABLED=0 $(GO) build -trimpath -ldflags '$(LDFLAGS)' -o $(BIN)/windows-amd64/nocagent.exe ./cmd/agent
	GOOS=windows GOARCH=amd64 CGO_ENABLED=0 $(GO) build -trimpath -ldflags '$(LDFLAGS)' -o $(BIN)/windows-amd64/nocwatchdog.exe ./cmd/watchdog

darwin-arm64:
	mkdir -p $(BIN)/darwin-arm64
	GOOS=darwin GOARCH=arm64 CGO_ENABLED=0 $(GO) build -trimpath -ldflags '$(LDFLAGS)' -o $(BIN)/darwin-arm64/nocagent ./cmd/agent
	GOOS=darwin GOARCH=arm64 CGO_ENABLED=0 $(GO) build -trimpath -ldflags '$(LDFLAGS)' -o $(BIN)/darwin-arm64/nocwatchdog ./cmd/watchdog

all-platforms: linux-amd64 linux-arm64 windows-amd64 darwin-arm64

clean:
	rm -rf $(BIN)
