#define _POSIX_C_SOURCE 200809L

#include "graph_internal.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>

/*
 * The on-disk representation is deliberately separate from the in-memory
 * linked lists.  A snapshot has a header followed by two length-delimited
 * sections.  Each record is framed as a payload length, which lets the
 * reader reject both truncated records and records with inconsistent string
 * lengths before adding anything to the returned graph.
 */
#define GRAPH_FILE_VERSION UINT32_C(2)
#define GRAPH_FILE_HEADER_SIZE UINT64_C(48)
#define GRAPH_FILE_LIMIT (UINT64_C(64) * UINT64_C(1024) * UINT64_C(1024))
#define NODE_RECORD_PAYLOAD_SIZE UINT64_C(12)
#define EDGE_RECORD_PAYLOAD_SIZE UINT64_C(20)
#define RECORD_FRAME_SIZE UINT64_C(4)
#define NODE_RECORD_MIN_SIZE (RECORD_FRAME_SIZE + NODE_RECORD_PAYLOAD_SIZE)
#define EDGE_RECORD_MIN_SIZE (RECORD_FRAME_SIZE + EDGE_RECORD_PAYLOAD_SIZE)

static const unsigned char graph_file_magic[8] = {
    'F', 'C', 'B', 'S', 'N', 'A', 'P', '2'
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

static bool checked_add_u64(uint64_t left, uint64_t right, uint64_t *sum)
{
    if (!sum || left > UINT64_MAX - right) {
        return false;
    }
    *sum = left + right;
    return true;
}

static bool count_as_u64(size_t count, uint64_t *result)
{
    if (!result || (uintmax_t)count > (uintmax_t)UINT64_MAX) {
        return false;
    }
    *result = (uint64_t)count;
    return true;
}

static bool string_size(const char *value, uint64_t fixed_payload,
                        uint64_t *record_size, uint32_t *length_out)
{
    size_t length;
    uint64_t payload_size;
    uint64_t total_size;

    if (!record_size || !graph_string_length(value, &length) ||
        length > GRAPH_MAX_STRING_LENGTH ||
        !checked_add_u64(fixed_payload, (uint64_t)length, &payload_size) ||
        payload_size > (uint64_t)UINT32_MAX ||
        !checked_add_u64(RECORD_FRAME_SIZE, payload_size, &total_size)) {
        return false;
    }

    *record_size = total_size;
    if (length_out) {
        *length_out = (uint32_t)length;
    }
    return true;
}

static bool section_sizes(const fcb_graph *graph, uint64_t *node_count,
                          uint64_t *edge_count, uint64_t *node_bytes,
                          uint64_t *edge_bytes)
{
    graph_node *node;
    graph_edge *edge;
    uint64_t node_total = 0;
    uint64_t edge_total = 0;

    if (!graph || !node_count || !edge_count || !node_bytes || !edge_bytes ||
        !count_as_u64(graph->nodes, node_count) ||
        !count_as_u64(graph->edges, edge_count)) {
        return false;
    }

    for (node = graph->head; node; node = node->next) {
        uint64_t record_size;
        if (!string_size(node->value, NODE_RECORD_PAYLOAD_SIZE,
                         &record_size, NULL) ||
            !checked_add_u64(node_total, record_size, &node_total)) {
            return false;
        }
    }
    for (edge = graph->links; edge; edge = edge->next) {
        uint64_t record_size;
        if (!string_size(edge->label, EDGE_RECORD_PAYLOAD_SIZE,
                         &record_size, NULL) ||
            !checked_add_u64(edge_total, record_size, &edge_total)) {
            return false;
        }
    }

    *node_bytes = node_total;
    *edge_bytes = edge_total;
    return true;
}

static bool snapshot_fits(uint64_t node_bytes, uint64_t edge_bytes,
                          uint64_t *file_size)
{
    uint64_t total = GRAPH_FILE_HEADER_SIZE;

    if (!file_size || !checked_add_u64(total, node_bytes, &total) ||
        !checked_add_u64(total, edge_bytes, &total) ||
        total > GRAPH_FILE_LIMIT) {
        return false;
    }
    *file_size = total;
    return true;
}

static bool write_node_record(FILE *file, const graph_node *node)
{
    uint64_t record_size;
    uint32_t length;
    uint32_t payload_size;

    if (!node || !string_size(node->value, NODE_RECORD_PAYLOAD_SIZE,
                              &record_size, &length)) {
        return false;
    }
    (void)record_size;
    payload_size = (uint32_t)(NODE_RECORD_PAYLOAD_SIZE + (uint64_t)length);
    if (!write_u32(file, payload_size) || !write_u64(file, node->id) ||
        !write_u32(file, length)) {
        return false;
    }
    return length == 0 || write_bytes(file, node->value, (size_t)length);
}

static bool write_edge_record(FILE *file, const graph_edge *edge)
{
    uint64_t record_size;
    uint32_t length;
    uint32_t payload_size;

    if (!edge || !string_size(edge->label, EDGE_RECORD_PAYLOAD_SIZE,
                              &record_size, &length)) {
        return false;
    }
    (void)record_size;
    payload_size = (uint32_t)(EDGE_RECORD_PAYLOAD_SIZE + (uint64_t)length);
    if (!write_u32(file, payload_size) || !write_u64(file, edge->from) ||
        !write_u64(file, edge->to) || !write_u32(file, length)) {
        return false;
    }
    return length == 0 || write_bytes(file, edge->label, (size_t)length);
}

static bool read_owned_string(FILE *file, uint32_t length, char **result)
{
    char *value;

    if (!result || length > (uint32_t)GRAPH_MAX_STRING_LENGTH) {
        return false;
    }

    value = malloc((size_t)length + 1);
    if (!value) {
        return false;
    }
    if (length != 0 && !read_bytes(file, value, (size_t)length)) {
        free(value);
        return false;
    }
    value[length] = '\0';

    /* Embedded NUL bytes cannot be represented by the public C ABI. */
    if (memchr(value, '\0', (size_t)length) != NULL) {
        free(value);
        return false;
    }

    *result = value;
    return true;
}

static bool consume_section_bytes(uint64_t *remaining, uint64_t amount)
{
    if (!remaining || *remaining < amount) {
        return false;
    }
    *remaining -= amount;
    return true;
}

static bool read_node_record(FILE *file, uint64_t *section_remaining,
                             fcb_graph *graph, uint64_t *maximum_id)
{
    uint32_t payload_size;
    uint64_t payload_remaining;
    uint64_t id;
    uint32_t length;
    char *value = NULL;
    graph_node *node;

    if (!section_remaining || !graph || !maximum_id ||
        !consume_section_bytes(section_remaining, RECORD_FRAME_SIZE) ||
        !read_u32(file, &payload_size) ||
        (uint64_t)payload_size < NODE_RECORD_PAYLOAD_SIZE ||
        !consume_section_bytes(section_remaining, (uint64_t)payload_size)) {
        return false;
    }

    payload_remaining = (uint64_t)payload_size;
    if (!read_u64(file, &id) || id == 0 ||
        !consume_section_bytes(&payload_remaining, UINT64_C(8)) ||
        !read_u32(file, &length) ||
        !consume_section_bytes(&payload_remaining, UINT64_C(4)) ||
        length > (uint32_t)GRAPH_MAX_STRING_LENGTH ||
        payload_remaining != (uint64_t)length ||
        !read_owned_string(file, length, &value)) {
        free(value);
        return false;
    }

    if (graph_find_node(graph, id)) {
        free(value);
        return false;
    }

    node = malloc(sizeof(*node));
    if (!node) {
        free(value);
        return false;
    }
    node->id = id;
    node->value = value;
    node->next = graph->head;
    graph->head = node;
    ++graph->nodes;
    if (id > *maximum_id) {
        *maximum_id = id;
    }
    return true;
}

static bool read_edge_record(FILE *file, uint64_t *section_remaining,
                             fcb_graph *graph)
{
    uint32_t payload_size;
    uint64_t payload_remaining;
    uint64_t from;
    uint64_t to;
    uint32_t length;
    char *label = NULL;
    graph_node *from_node;
    graph_node *to_node;
    graph_edge *edge;

    if (!section_remaining || !graph ||
        !consume_section_bytes(section_remaining, RECORD_FRAME_SIZE) ||
        !read_u32(file, &payload_size) ||
        (uint64_t)payload_size < EDGE_RECORD_PAYLOAD_SIZE ||
        !consume_section_bytes(section_remaining, (uint64_t)payload_size)) {
        return false;
    }

    payload_remaining = (uint64_t)payload_size;
    if (!read_u64(file, &from) || !consume_section_bytes(&payload_remaining,
                                                          UINT64_C(8)) ||
        !read_u64(file, &to) || !consume_section_bytes(&payload_remaining,
                                                        UINT64_C(8)) ||
        !read_u32(file, &length) ||
        !consume_section_bytes(&payload_remaining, UINT64_C(4)) ||
        from == 0 || to == 0 || length > (uint32_t)GRAPH_MAX_STRING_LENGTH ||
        payload_remaining != (uint64_t)length ||
        !read_owned_string(file, length, &label)) {
        free(label);
        return false;
    }

    from_node = graph_find_node(graph, from);
    to_node = graph_find_node(graph, to);
    if (!from_node || !to_node || graph_find_edge(graph, from, to)) {
        free(label);
        return false;
    }

    edge = malloc(sizeof(*edge));
    if (!edge) {
        free(label);
        return false;
    }
    edge->from = from;
    edge->to = to;
    edge->label = label;
    edge->from_node = from_node;
    edge->to_node = to_node;
    edge->next = graph->links;
    graph->links = edge;
    ++graph->edges;
    return true;
}

bool fcb_graph_save(const fcb_graph *graph, const char *path)
{
    FILE *file;
    graph_node *node;
    graph_edge *edge;
    uint64_t node_count;
    uint64_t edge_count;
    uint64_t node_bytes;
    uint64_t edge_bytes;
    uint64_t file_size;
    bool ok = true;

    if (!graph || !path || path[0] == '\0' ||
        !section_sizes(graph, &node_count, &edge_count, &node_bytes,
                       &edge_bytes) ||
        !snapshot_fits(node_bytes, edge_bytes, &file_size)) {
        return false;
    }
    (void)file_size;

    file = fopen(path, "wb");
    if (!file) {
        return false;
    }

    if (!write_bytes(file, graph_file_magic, sizeof(graph_file_magic)) ||
        !write_u32(file, GRAPH_FILE_VERSION) ||
        !write_u32(file, graph->directed ? UINT32_C(1) : UINT32_C(0)) ||
        !write_u64(file, node_count) || !write_u64(file, edge_count) ||
        !write_u64(file, node_bytes) || !write_u64(file, edge_bytes)) {
        ok = false;
    }

    for (node = graph->head; ok && node; node = node->next) {
        if (!write_node_record(file, node)) {
            ok = false;
        }
    }
    for (edge = graph->links; ok && edge; edge = edge->next) {
        if (!write_edge_record(file, edge)) {
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
    uint64_t node_count;
    uint64_t edge_count;
    uint64_t node_bytes;
    uint64_t edge_bytes;
    uint64_t remaining_file;
    uint64_t node_remaining;
    uint64_t edge_remaining;
    uint64_t maximum_id = 0;
    unsigned char magic[sizeof(graph_file_magic)];
    uint32_t version;
    uint32_t flags;
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
        !read_u32(file, &flags) || flags > UINT32_C(1) ||
        !read_u64(file, &node_count) || !read_u64(file, &edge_count) ||
        !read_u64(file, &node_bytes) || !read_u64(file, &edge_bytes)) {
        goto failure;
    }

    remaining_file = file_size - GRAPH_FILE_HEADER_SIZE;
    if (node_bytes > remaining_file) {
        goto failure;
    }
    remaining_file -= node_bytes;
    if (edge_bytes != remaining_file ||
        node_count > node_bytes / NODE_RECORD_MIN_SIZE ||
        edge_count > edge_bytes / EDGE_RECORD_MIN_SIZE ||
        node_count > (uint64_t)SIZE_MAX || edge_count > (uint64_t)SIZE_MAX) {
        goto failure;
    }

    graph = fcb_graph_create(flags != 0);
    if (!graph) {
        goto failure;
    }

    node_remaining = node_bytes;
    for (index = 0; index < node_count; ++index) {
        if (!read_node_record(file, &node_remaining, graph, &maximum_id)) {
            goto failure;
        }
    }
    if (node_remaining != 0) {
        goto failure;
    }

    edge_remaining = edge_bytes;
    for (index = 0; index < edge_count; ++index) {
        if (!read_edge_record(file, &edge_remaining, graph)) {
            goto failure;
        }
    }
    if (edge_remaining != 0 || fgetc(file) != EOF || ferror(file)) {
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
