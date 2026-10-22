#ifndef SWECLAR_GRAPH_H
#define SWECLAR_GRAPH_H
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
typedef struct fcb_graph fcb_graph;
fcb_graph *fcb_graph_create(bool directed);
void fcb_graph_destroy(fcb_graph *graph);
uint64_t fcb_graph_add_node(fcb_graph *graph, const char *value);
const char *fcb_graph_get_node(const fcb_graph *graph, uint64_t id);
bool fcb_graph_update_node(fcb_graph *graph, uint64_t id, const char *value);
bool fcb_graph_remove_node(fcb_graph *graph, uint64_t id);
size_t fcb_graph_node_count(const fcb_graph *graph);
bool fcb_graph_add_edge(fcb_graph *graph, uint64_t from, uint64_t to, const char *label);
const char *fcb_graph_get_edge(const fcb_graph *graph, uint64_t from, uint64_t to);
bool fcb_graph_update_edge(fcb_graph *graph, uint64_t from, uint64_t to, const char *label);
bool fcb_graph_remove_edge(fcb_graph *graph, uint64_t from, uint64_t to);
size_t fcb_graph_edge_count(const fcb_graph *graph);
size_t fcb_graph_bfs(const fcb_graph *graph, uint64_t start, uint64_t *out, size_t capacity);
size_t fcb_graph_dfs(const fcb_graph *graph, uint64_t start, uint64_t *out, size_t capacity);
bool fcb_graph_save(const fcb_graph *graph, const char *path);
fcb_graph *fcb_graph_load(const char *path);
#endif
