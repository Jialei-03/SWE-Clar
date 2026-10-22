#ifndef GRAPH_INTERNAL_H
#define GRAPH_INTERNAL_H

#include "fcb_graph.h"

#define GRAPH_MAX_STRING_LENGTH ((size_t)4096)

typedef struct graph_node graph_node;
typedef struct graph_edge graph_edge;

struct graph_node {
    uint64_t id;
    char *value;
    graph_node *next;
};

struct graph_edge {
    uint64_t from;
    uint64_t to;
    char *label;
    graph_node *from_node;
    graph_node *to_node;
    graph_edge *next;
};

struct fcb_graph {
    bool directed;
    uint64_t next_id;
    size_t nodes;
    size_t edges;
    graph_node *head;
    graph_edge *links;
};

graph_node *graph_find_node(const fcb_graph *graph, uint64_t id);
graph_edge *graph_find_edge(const fcb_graph *graph, uint64_t from, uint64_t to);
bool graph_string_length(const char *value, size_t *length);
char *graph_copy_string(const char *value);

#endif
