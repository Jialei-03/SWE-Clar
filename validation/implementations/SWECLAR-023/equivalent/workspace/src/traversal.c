#include "graph_internal.h"

#include <stdlib.h>

static bool pointer_seen(graph_node *const *seen, size_t count,
                         const graph_node *candidate)
{
    size_t index;

    for (index = 0; index < count; ++index) {
        if (seen[index] == candidate) {
            return true;
        }
    }
    return false;
}

static graph_node *edge_neighbor(const fcb_graph *graph,
                                 const graph_node *current,
                                 const graph_edge *edge)
{
    if (graph->directed) {
        return edge->from_node == current ? edge->to_node : NULL;
    }

    if (edge->from_node == current) {
        return edge->to_node;
    }
    if (edge->to_node == current) {
        return edge->from_node;
    }
    return NULL;
}

size_t fcb_graph_bfs(const fcb_graph *graph, uint64_t start,
                     uint64_t *out, size_t capacity)
{
    graph_node *start_node;
    graph_node **queue;
    size_t head = 0;
    size_t tail = 0;
    size_t written = 0;

    if (!graph || !out || capacity == 0) {
        return 0;
    }

    start_node = graph_find_node(graph, start);
    if (!start_node) {
        return 0;
    }

    if (graph->nodes > SIZE_MAX / sizeof(*queue)) {
        return 0;
    }
    queue = malloc(graph->nodes * sizeof(*queue));
    if (!queue) {
        return 0;
    }

    queue[tail++] = start_node;
    while (head < tail) {
        graph_node *current = queue[head++];
        graph_edge *edge;

        out[written++] = current->id;
        if (written == capacity) {
            free(queue);
            return written;
        }

        for (edge = graph->links; edge; edge = edge->next) {
            graph_node *neighbor = edge_neighbor(graph, current, edge);
            if (neighbor && !pointer_seen(queue, tail, neighbor)) {
                queue[tail++] = neighbor;
            }
        }
    }

    free(queue);
    return written;
}

typedef struct dfs_frame {
    graph_node *node;
    graph_edge *next_edge;
} dfs_frame;

size_t fcb_graph_dfs(const fcb_graph *graph, uint64_t start,
                     uint64_t *out, size_t capacity)
{
    graph_node *start_node;
    graph_node **seen;
    dfs_frame *stack;
    size_t seen_count = 0;
    size_t top = 0;
    size_t written = 0;

    if (!graph || !out || capacity == 0) {
        return 0;
    }

    start_node = graph_find_node(graph, start);
    if (!start_node) {
        return 0;
    }

    if (graph->nodes > SIZE_MAX / sizeof(*seen) ||
        graph->nodes > SIZE_MAX / sizeof(*stack)) {
        return 0;
    }

    seen = malloc(graph->nodes * sizeof(*seen));
    if (!seen) {
        return 0;
    }
    stack = malloc(graph->nodes * sizeof(*stack));
    if (!stack) {
        free(seen);
        return 0;
    }

    seen[seen_count++] = start_node;
    out[written++] = start_node->id;
    if (written == capacity) {
        free(stack);
        free(seen);
        return written;
    }

    stack[top].node = start_node;
    stack[top].next_edge = graph->links;
    ++top;

    while (top != 0) {
        dfs_frame *frame = &stack[top - 1];
        graph_node *neighbor = NULL;

        while (frame->next_edge) {
            graph_edge *edge = frame->next_edge;
            frame->next_edge = edge->next;
            neighbor = edge_neighbor(graph, frame->node, edge);
            if (neighbor && !pointer_seen(seen, seen_count, neighbor)) {
                break;
            }
            neighbor = NULL;
        }

        if (!neighbor) {
            --top;
            continue;
        }

        seen[seen_count++] = neighbor;
        out[written++] = neighbor->id;
        if (written == capacity) {
            free(stack);
            free(seen);
            return written;
        }

        stack[top].node = neighbor;
        stack[top].next_edge = graph->links;
        ++top;
    }

    free(stack);
    free(seen);
    return written;
}
