#define _POSIX_C_SOURCE 200809L

#include "graph_internal.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>

#define GRAPH_FILE_VERSION UINT32_C(1)
#define GRAPH_FILE_HEADER_SIZE UINT64_C(32)
#define GRAPH_FILE_LIMIT (UINT64_C(64) * UINT64_C(1024) * UINT64_C(1024))

static const unsigned char graph_file_magic[8] = {
    'F', 'C', 'B', 'G', 'R', 'A', 'P', 'H'
};

static bool write_bytes(FILE *file, const void *data, size_t size)
{
    return fwrite(data, 1, size, file) == size;
}

static bool read_bytes(FILE *file, void *data, size_t size)
{
    return fread(data, 1, size, file) == size;
}

static bool write_u32(FILE *file, uint32_t value)
{
    unsigned char bytes[4];

    bytes[0] = (unsigned char)(value & UINT32_C(0xff));
    bytes[1] = (unsigned char)((value >> 8) & UINT32_C(0xff));
    bytes[2] = (unsigned char)((value >> 16) & UINT32_C(0xff));
    bytes[3] = (unsigned char)((value >> 24) & UINT32_C(0xff));
    return write_bytes(file, bytes, sizeof(bytes));
}

static bool read_u32(FILE *file, uint32_t *value)
{
    unsigned char bytes[4];

    if (!value || !read_bytes(file, bytes, sizeof(bytes))) {
        return false;
    }

    *value = ((uint32_t)bytes[0]) |
             ((uint32_t)bytes[1] << 8) |
             ((uint32_t)bytes[2] << 16) |
             ((uint32_t)bytes[3] << 24);
    return true;
}

static bool write_u64(FILE *file, uint64_t value)
{
    unsigned char bytes[8];
    size_t index;

    for (index = 0; index < sizeof(bytes); ++index) {
        bytes[index] = (unsigned char)((value >> (index * 8)) & UINT64_C(0xff));
    }
    return write_bytes(file, bytes, sizeof(bytes));
}

static bool read_u64(FILE *file, uint64_t *value)
{
    unsigned char bytes[8];
    uint64_t result = 0;
    size_t index;

    if (!value || !read_bytes(file, bytes, sizeof(bytes))) {
        return false;
    }

    for (index = 0; index < sizeof(bytes); ++index) {
        result |= (uint64_t)bytes[index] << (index * 8);
    }
    *value = result;
    return true;
}

static bool write_string(FILE *file, const char *value)
{
    size_t length;

    if (!graph_string_length(value, &length) || length > GRAPH_MAX_STRING_LENGTH) {
        return false;
    }
    if (!write_u32(file, (uint32_t)length)) {
        return false;
    }
    return length == 0 || write_bytes(file, value, length);
}

static bool read_string(FILE *file, char **result)
{
    uint32_t length;
    char *value;

    if (!result || !read_u32(file, &length) ||
        length > (uint32_t)GRAPH_MAX_STRING_LENGTH) {
        return false;
    }

    value = malloc((size_t)length + 1);
    if (!value) {
        return false;
    }

    if (length != 0 && !read_bytes(file, value, length)) {
        free(value);
        return false;
    }
    value[length] = '\0';

    /* A graph string is a C string, so an embedded NUL is not a valid record. */
    if (memchr(value, '\0', length) != NULL) {
        free(value);
        return false;
    }

    *result = value;
    return true;
}

bool fcb_graph_save(const fcb_graph *graph, const char *path)
{
    FILE *file;
    unsigned char flags[4] = {0, 0, 0, 0};
    graph_node *node;
    graph_edge *edge;
    bool ok = true;

    if (!graph || !path || path[0] == '\0') {
        return false;
    }

    file = fopen(path, "wb");
    if (!file) {
        return false;
    }

    flags[0] = graph->directed ? 1U : 0U;
    if (!write_bytes(file, graph_file_magic, sizeof(graph_file_magic)) ||
        !write_u32(file, GRAPH_FILE_VERSION) ||
        !write_bytes(file, flags, sizeof(flags)) ||
        !write_u64(file, (uint64_t)graph->nodes) ||
        !write_u64(file, (uint64_t)graph->edges)) {
        ok = false;
    }

    for (node = graph->head; ok && node; node = node->next) {
        if (!write_u64(file, node->id) || !write_string(file, node->value)) {
            ok = false;
        }
    }

    for (edge = graph->links; ok && edge; edge = edge->next) {
        if (!write_u64(file, edge->from) ||
            !write_u64(file, edge->to) ||
            !write_string(file, edge->label)) {
            ok = false;
        }
    }

    if (fclose(file) != 0) {
        ok = false;
    }
    return ok;
}

fcb_graph *fcb_graph_load(const char *path)
{
    FILE *file = NULL;
    struct stat information;
    uint64_t file_size;
    unsigned char magic[sizeof(graph_file_magic)];
    unsigned char flags[4];
    uint32_t version;
    uint64_t node_count;
    uint64_t edge_count;
    uint64_t remaining;
    uint64_t maximum_id = 0;
    fcb_graph *graph = NULL;
    uint64_t index;

    if (!path || path[0] == '\0') {
        return NULL;
    }

    file = fopen(path, "rb");
    if (!file) {
        return NULL;
    }

    if (fstat(fileno(file), &information) != 0 || information.st_size < 0 ||
        !S_ISREG(information.st_mode)) {
        goto failure;
    }
    file_size = (uint64_t)information.st_size;
    if (file_size > GRAPH_FILE_LIMIT || file_size < GRAPH_FILE_HEADER_SIZE) {
        goto failure;
    }

    if (!read_bytes(file, magic, sizeof(magic)) ||
        memcmp(magic, graph_file_magic, sizeof(magic)) != 0 ||
        !read_u32(file, &version) || version != GRAPH_FILE_VERSION ||
        !read_bytes(file, flags, sizeof(flags)) ||
        (flags[0] != 0 && flags[0] != 1) || flags[1] != 0 ||
        flags[2] != 0 || flags[3] != 0 ||
        !read_u64(file, &node_count) || !read_u64(file, &edge_count)) {
        goto failure;
    }

    remaining = file_size - GRAPH_FILE_HEADER_SIZE;
    /* Every node and edge has at least its fixed-size record fields. */
    if (node_count > remaining / UINT64_C(12)) {
        goto failure;
    }
    remaining -= node_count * UINT64_C(12);
    if (edge_count > remaining / UINT64_C(20)) {
        goto failure;
    }
    if (node_count > (uint64_t)SIZE_MAX || edge_count > (uint64_t)SIZE_MAX) {
        goto failure;
    }

    graph = fcb_graph_create(flags[0] != 0);
    if (!graph) {
        goto failure;
    }

    for (index = 0; index < node_count; ++index) {
        uint64_t id;
        char *value = NULL;
        graph_node *node;

        if (!read_u64(file, &id) || id == 0 ||
            graph_find_node(graph, id) || !read_string(file, &value)) {
            free(value);
            goto failure;
        }

        node = malloc(sizeof(*node));
        if (!node) {
            free(value);
            goto failure;
        }
        node->id = id;
        node->value = value;
        node->next = graph->head;
        graph->head = node;
        ++graph->nodes;
        if (id > maximum_id) {
            maximum_id = id;
        }
    }

    for (index = 0; index < edge_count; ++index) {
        uint64_t from;
        uint64_t to;
        char *label = NULL;
        graph_node *from_node;
        graph_node *to_node;
        graph_edge *edge;

        if (!read_u64(file, &from) || !read_u64(file, &to) ||
            from == 0 || to == 0 || graph_find_edge(graph, from, to) ||
            !read_string(file, &label)) {
            free(label);
            goto failure;
        }

        from_node = graph_find_node(graph, from);
        to_node = graph_find_node(graph, to);
        if (!from_node || !to_node) {
            free(label);
            goto failure;
        }

        edge = malloc(sizeof(*edge));
        if (!edge) {
            free(label);
            goto failure;
        }
        edge->from = from;
        edge->to = to;
        edge->label = label;
        edge->from_node = from_node;
        edge->to_node = to_node;
        edge->next = graph->links;
        graph->links = edge;
        ++graph->edges;
    }

    if (fgetc(file) != EOF || ferror(file)) {
        goto failure;
    }

    if (maximum_id == 0) {
        graph->next_id = UINT64_C(1);
    } else if (maximum_id == UINT64_MAX) {
        graph->next_id = 0;
    } else {
        graph->next_id = maximum_id + 1;
    }

    if (fclose(file) != 0) {
        file = NULL;
        goto failure;
    }
    file = NULL;
    return graph;

failure:
    if (file) {
        fclose(file);
    }
    fcb_graph_destroy(graph);
    return NULL;
}
