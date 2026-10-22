#include "graph_internal.h"

#include <stdlib.h>
#include <string.h>

bool graph_string_length(const char *value, size_t *length)
{
    size_t current = 0;

    if (!value || !length) {
        return false;
    }

    while (current <= GRAPH_MAX_STRING_LENGTH) {
        if (value[current] == '\0') {
            *length = current;
            return true;
        }
        ++current;
    }

    return false;
}

char *graph_copy_string(const char *value)
{
    size_t length;
    char *copy;

    if (!graph_string_length(value, &length)) {
        return NULL;
    }

    copy = malloc(length + 1);
    if (!copy) {
        return NULL;
    }

    if (length != 0) {
        memcpy(copy, value, length);
    }
    copy[length] = '\0';
    return copy;
}

graph_node *graph_find_node(const fcb_graph *graph, uint64_t id)
{
    graph_node *node;

    if (!graph || id == 0) {
        return NULL;
    }

    for (node = graph->head; node; node = node->next) {
        if (node->id == id) {
            return node;
        }
    }

    return NULL;
}

graph_edge *graph_find_edge(const fcb_graph *graph, uint64_t from, uint64_t to)
{
    graph_edge *edge;

    if (!graph || from == 0 || to == 0) {
        return NULL;
    }

    for (edge = graph->links; edge; edge = edge->next) {
        if ((edge->from == from && edge->to == to) ||
            (!graph->directed && edge->from == to && edge->to == from)) {
            return edge;
        }
    }

    return NULL;
}

static graph_edge **edge_slot(fcb_graph *graph, uint64_t from, uint64_t to)
{
    graph_edge **slot;

    if (!graph || from == 0 || to == 0) {
        return NULL;
    }

    slot = &graph->links;
    while (*slot) {
        graph_edge *edge = *slot;
        if ((edge->from == from && edge->to == to) ||
            (!graph->directed && edge->from == to && edge->to == from)) {
            break;
        }
        slot = &edge->next;
    }

    return slot;
}

static uint64_t allocate_node_id(fcb_graph *graph)
{
    uint64_t candidate;
    uint64_t first;

    if (!graph) {
        return 0;
    }

    candidate = graph->next_id != 0 ? graph->next_id : UINT64_C(1);
    first = candidate;

    for (;;) {
        if (!graph_find_node(graph, candidate)) {
            graph->next_id = candidate == UINT64_MAX ? 0 : candidate + 1;
            return candidate;
        }

        candidate = candidate == UINT64_MAX ? UINT64_C(1) : candidate + 1;
        if (candidate == first) {
            return 0;
        }
    }
}

fcb_graph *fcb_graph_create(bool directed)
{
    fcb_graph *graph = calloc(1, sizeof(*graph));

    if (graph) {
        graph->directed = directed;
        graph->next_id = UINT64_C(1);
    }

    return graph;
}

void fcb_graph_destroy(fcb_graph *graph)
{
    if (!graph) {
        return;
    }

    while (graph->links) {
        graph_edge *edge = graph->links;
        graph->links = edge->next;
        free(edge->label);
        free(edge);
    }

    while (graph->head) {
        graph_node *node = graph->head;
        graph->head = node->next;
        free(node->value);
        free(node);
    }

    free(graph);
}

size_t fcb_graph_node_count(const fcb_graph *graph)
{
    return graph ? graph->nodes : 0;
}

size_t fcb_graph_edge_count(const fcb_graph *graph)
{
    return graph ? graph->edges : 0;
}

uint64_t fcb_graph_add_node(fcb_graph *graph, const char *value)
{
    graph_node *node;
    char *copy;
    uint64_t id;

    if (!graph) {
        return 0;
    }

    copy = graph_copy_string(value);
    if (!copy) {
        return 0;
    }

    node = malloc(sizeof(*node));
    if (!node) {
        free(copy);
        return 0;
    }

    id = allocate_node_id(graph);
    if (id == 0) {
        free(node);
        free(copy);
        return 0;
    }

    node->id = id;
    node->value = copy;
    node->next = graph->head;
    graph->head = node;
    ++graph->nodes;
    return id;
}

const char *fcb_graph_get_node(const fcb_graph *graph, uint64_t id)
{
    graph_node *node = graph_find_node(graph, id);
    return node ? node->value : NULL;
}

bool fcb_graph_update_node(fcb_graph *graph, uint64_t id, const char *value)
{
    graph_node *node;
    char *copy;

    node = graph_find_node(graph, id);
    if (!node) {
        return false;
    }

    copy = graph_copy_string(value);
    if (!copy) {
        return false;
    }

    free(node->value);
    node->value = copy;
    return true;
}

bool fcb_graph_remove_node(fcb_graph *graph, uint64_t id)
{
    graph_node **node_slot;
    graph_edge **edge_slot_cursor;
    graph_node *node;

    if (!graph || id == 0) {
        return false;
    }

    node_slot = &graph->head;
    while (*node_slot && (*node_slot)->id != id) {
        node_slot = &(*node_slot)->next;
    }
    if (!*node_slot) {
        return false;
    }

    edge_slot_cursor = &graph->links;
    while (*edge_slot_cursor) {
        graph_edge *edge = *edge_slot_cursor;
        if (edge->from == id || edge->to == id) {
            *edge_slot_cursor = edge->next;
            free(edge->label);
            free(edge);
            --graph->edges;
        } else {
            edge_slot_cursor = &edge->next;
        }
    }

    node = *node_slot;
    *node_slot = node->next;
    free(node->value);
    free(node);
    --graph->nodes;
    return true;
}

bool fcb_graph_add_edge(fcb_graph *graph, uint64_t from, uint64_t to,
                        const char *label)
{
    graph_node *from_node;
    graph_node *to_node;
    graph_edge *edge;
    char *copy;

    if (!graph) {
        return false;
    }

    from_node = graph_find_node(graph, from);
    to_node = graph_find_node(graph, to);
    if (!from_node || !to_node || graph_find_edge(graph, from, to)) {
        return false;
    }

    copy = graph_copy_string(label);
    if (!copy) {
        return false;
    }

    edge = malloc(sizeof(*edge));
    if (!edge) {
        free(copy);
        return false;
    }

    edge->from = from;
    edge->to = to;
    edge->label = copy;
    edge->from_node = from_node;
    edge->to_node = to_node;
    edge->next = graph->links;
    graph->links = edge;
    ++graph->edges;
    return true;
}

const char *fcb_graph_get_edge(const fcb_graph *graph, uint64_t from,
                               uint64_t to)
{
    graph_edge *edge = graph_find_edge(graph, from, to);
    return edge ? edge->label : NULL;
}

bool fcb_graph_update_edge(fcb_graph *graph, uint64_t from, uint64_t to,
                           const char *label)
{
    graph_edge *edge;
    char *copy;

    edge = graph_find_edge(graph, from, to);
    if (!edge) {
        return false;
    }

    copy = graph_copy_string(label);
    if (!copy) {
        return false;
    }

    free(edge->label);
    edge->label = copy;
    return true;
}

bool fcb_graph_remove_edge(fcb_graph *graph, uint64_t from, uint64_t to)
{
    graph_edge **slot;
    graph_edge *edge;

    slot = edge_slot(graph, from, to);
    if (!slot || !*slot) {
        return false;
    }

    edge = *slot;
    *slot = edge->next;
    free(edge->label);
    free(edge);
    --graph->edges;
    return true;
}
