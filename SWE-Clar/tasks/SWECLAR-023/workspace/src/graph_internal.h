#ifndef GRAPH_INTERNAL_H
#define GRAPH_INTERNAL_H
#include "fcb_graph.h"
typedef struct graph_node { uint64_t id; char *value; struct graph_node *next; } graph_node;
typedef struct graph_edge { uint64_t from,to; char *label; struct graph_edge *next; } graph_edge;
struct fcb_graph { bool directed; uint64_t next_id; size_t nodes,edges; graph_node *head; graph_edge *links; };
graph_node *graph_find_node(const fcb_graph *g,uint64_t id);
char *graph_copy_string(const char *value);
#endif
