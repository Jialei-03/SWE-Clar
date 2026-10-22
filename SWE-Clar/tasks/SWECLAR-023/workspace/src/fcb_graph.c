#include "graph_internal.h"
#include <stdlib.h>
#include <string.h>

char *graph_copy_string(const char *value) {
    if (!value) return NULL;
    size_t length=0;
    while (length<=4096 && value[length]) ++length;
    if (length>4096) return NULL;
    char *copy=malloc(length+1);
    if (copy) memcpy(copy,value,length+1);
    return copy;
}
graph_node *graph_find_node(const fcb_graph *g,uint64_t id) {
    if (!g || !id) return NULL;
    for (graph_node *node=g->head;node;node=node->next)
        if (node->id==id) return node;
    return NULL;
}
static graph_edge **edge_slot(fcb_graph *g,uint64_t from,uint64_t to) {
    graph_edge **slot=&g->links;
    while (*slot) {
        graph_edge *edge=*slot;
        if ((edge->from==from && edge->to==to) ||
            (!g->directed && edge->from==to && edge->to==from)) break;
        slot=&edge->next;
    }
    return slot;
}
fcb_graph *fcb_graph_create(bool directed) {
    fcb_graph *g=calloc(1,sizeof(*g));
    if (g) { g->directed=directed;g->next_id=1; }
    return g;
}
void fcb_graph_destroy(fcb_graph *g) {
    if (!g) return;
    while (g->links) { graph_edge *edge=g->links;g->links=edge->next;free(edge->label);free(edge); }
    while (g->head) { graph_node *node=g->head;g->head=node->next;free(node->value);free(node); }
    free(g);
}
size_t fcb_graph_node_count(const fcb_graph *g) { return g?g->nodes:0; }
size_t fcb_graph_edge_count(const fcb_graph *g) { return g?g->edges:0; }
uint64_t fcb_graph_add_node(fcb_graph *g,const char *value) {
    if (!g || !g->next_id) return 0;
    char *copy=graph_copy_string(value);if (!copy) return 0;
    graph_node *node=malloc(sizeof(*node));
    if (!node) { free(copy);return 0; }
    node->id=g->next_id++;node->value=copy;node->next=g->head;g->head=node;++g->nodes;
    return node->id;
}
const char *fcb_graph_get_node(const fcb_graph *g,uint64_t id) {
    graph_node *node=graph_find_node(g,id);return node?node->value:NULL;
}
bool fcb_graph_update_node(fcb_graph *g,uint64_t id,const char *value) {
    graph_node *node=graph_find_node(g,id);if (!node) return false;
    char *copy=graph_copy_string(value);if (!copy) return false;
    free(node->value);node->value=copy;return true;
}
bool fcb_graph_remove_node(fcb_graph *g,uint64_t id) {
    if (!g || !id) return false;
    graph_node **slot=&g->head;
    while (*slot && (*slot)->id!=id) slot=&(*slot)->next;
    if (!*slot) return false;
    graph_edge **link=&g->links;
    while (*link) {
        graph_edge *edge=*link;
        if (edge->from==id || edge->to==id) { *link=edge->next;free(edge->label);free(edge);--g->edges; }
        else link=&edge->next;
    }
    graph_node *node=*slot;*slot=node->next;free(node->value);free(node);--g->nodes;return true;
}
bool fcb_graph_add_edge(fcb_graph *g,uint64_t from,uint64_t to,const char *label) {
    if (!graph_find_node(g,from) || !graph_find_node(g,to) || *edge_slot(g,from,to)) return false;
    char *copy=graph_copy_string(label);if (!copy) return false;
    graph_edge *edge=malloc(sizeof(*edge));if (!edge) { free(copy);return false; }
    edge->from=from;edge->to=to;edge->label=copy;edge->next=g->links;g->links=edge;++g->edges;return true;
}
const char *fcb_graph_get_edge(const fcb_graph *g,uint64_t from,uint64_t to) {
    if (!g || !from || !to) return NULL;
    for (graph_edge *edge=g->links;edge;edge=edge->next)
        if ((edge->from==from && edge->to==to) || (!g->directed && edge->from==to && edge->to==from)) return edge->label;
    return NULL;
}
bool fcb_graph_update_edge(fcb_graph *g,uint64_t from,uint64_t to,const char *label) {
    if (!g) return false;
    graph_edge *edge=*edge_slot(g,from,to);if (!edge) return false;
    char *copy=graph_copy_string(label);if (!copy) return false;
    free(edge->label);edge->label=copy;return true;
}
bool fcb_graph_remove_edge(fcb_graph *g,uint64_t from,uint64_t to) {
    if (!g) return false;
    graph_edge **slot=edge_slot(g,from,to);if (!*slot) return false;
    graph_edge *edge=*slot;*slot=edge->next;free(edge->label);free(edge);--g->edges;return true;
}
