CC      ?= gcc
CFLAGS  ?= -O2 -g -Wall -Wextra -pthread
LDLIBS  := -lm
SRC     := src/main.c src/threads.c src/policy.c src/channel.c
BIN     := build/gnb_sim

all: $(BIN)

$(BIN): $(SRC) src/sim.h src/policy.h
	@mkdir -p build
	$(CC) $(CFLAGS) -o $@ $(SRC) $(LDLIBS)

# Debugging/sanitizer build (slower; do not use for measurements).
debug:
	@mkdir -p build
	$(CC) -O0 -g -Wall -Wextra -pthread -fsanitize=thread -o build/gnb_sim_debug $(SRC) $(LDLIBS)

clean:
	rm -rf build

.PHONY: all debug clean
