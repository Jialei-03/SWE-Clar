CC ?= cc
AR ?= ar
CFLAGS ?= -std=c11 -O2 -Wall -Wextra
CPPFLAGS += -Iinclude
LDFLAGS ?=
OBJECTS = build/fcb_graph.o build/traversal.o build/persistence.o
.PHONY: all clean
all: build/libfcb_graph.a build/graph_demo build/graph_bench
build:
	mkdir -p build
build/%.o: src/%.c include/fcb_graph.h src/graph_internal.h | build
	$(CC) $(CPPFLAGS) $(CFLAGS) -c $< -o $@
build/libfcb_graph.a: $(OBJECTS)
	$(AR) rcs $@ $^
build/graph_demo: tools/graph_demo.c build/libfcb_graph.a
	$(CC) $(CPPFLAGS) $(CFLAGS) $< build/libfcb_graph.a $(LDFLAGS) -o $@
build/graph_bench: tools/graph_bench.c build/libfcb_graph.a
	$(CC) $(CPPFLAGS) $(CFLAGS) $< build/libfcb_graph.a $(LDFLAGS) -o $@
clean:
	rm -rf build
