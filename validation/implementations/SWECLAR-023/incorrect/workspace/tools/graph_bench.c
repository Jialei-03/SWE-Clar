#define _POSIX_C_SOURCE 200809L

#include "fcb_graph.h"

#include <errno.h>
#include <math.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/resource.h>
#include <time.h>

#define BENCHMARK_MAX_RUNS ((size_t)10000)

typedef struct phase_result {
    double average_us;
    double minimum_us;
    double maximum_us;
    double cpu_seconds;
    long peak_rss_kib;
} phase_result;

static bool parse_runs(const char *text, size_t *runs)
{
    size_t value = 0;
    const unsigned char *cursor;

    if (!text || !*text || !runs) {
        return false;
    }

    for (cursor = (const unsigned char *)text; *cursor; ++cursor) {
        size_t digit;
        if (*cursor < (unsigned char)'0' || *cursor > (unsigned char)'9') {
            return false;
        }
        digit = (size_t)(*cursor - (unsigned char)'0');
        if (value > (BENCHMARK_MAX_RUNS - digit) / 10) {
            return false;
        }
        value = value * 10 + digit;
    }

    if (value == 0 || value > BENCHMARK_MAX_RUNS) {
        return false;
    }
    *runs = value;
    return true;
}

static bool parse_arguments(int argc, char **argv, size_t *runs,
                            const char **output_path)
{
    bool have_runs = false;
    bool have_output = false;
    int index;

    if (argc != 5 || !runs || !output_path) {
        return false;
    }

    for (index = 1; index < argc; index += 2) {
        if (strcmp(argv[index], "--runs") == 0) {
            if (have_runs || !parse_runs(argv[index + 1], runs)) {
                return false;
            }
            have_runs = true;
        } else if (strcmp(argv[index], "--output") == 0) {
            if (have_output || !argv[index + 1] || argv[index + 1][0] == '\0') {
                return false;
            }
            *output_path = argv[index + 1];
            have_output = true;
        } else {
            return false;
        }
    }

    return have_runs && have_output;
}

static bool duration_microseconds(const struct timespec *before,
                                  const struct timespec *after,
                                  double *result)
{
    long double seconds;

    if (!before || !after || !result || after->tv_sec < before->tv_sec ||
        (after->tv_sec == before->tv_sec && after->tv_nsec < before->tv_nsec)) {
        return false;
    }

    seconds = (long double)after->tv_sec - (long double)before->tv_sec;
    seconds += ((long double)after->tv_nsec - (long double)before->tv_nsec) /
               1000000000.0L;
    seconds *= 1000000.0L;
    *result = (double)seconds;
    return isfinite(*result) && *result >= 0.0;
}

static bool elapsed_cpu_seconds(const struct timespec *before,
                                const struct timespec *after,
                                double *result)
{
    long double seconds;

    if (!before || !after || !result || after->tv_sec < before->tv_sec ||
        (after->tv_sec == before->tv_sec && after->tv_nsec < before->tv_nsec)) {
        return false;
    }

    seconds = (long double)after->tv_sec - (long double)before->tv_sec;
    seconds += ((long double)after->tv_nsec - (long double)before->tv_nsec) /
               1000000000.0L;
    *result = (double)seconds;
    return isfinite(*result) && *result >= 0.0;
}

static char **make_values(const char *prefix, size_t runs)
{
    char **values;
    size_t index;

    values = calloc(runs, sizeof(*values));
    if (!values) {
        return NULL;
    }

    for (index = 0; index < runs; ++index) {
        int needed = snprintf(NULL, 0, "%s%zu", prefix, index);
        if (needed < 0) {
            goto failure;
        }
        values[index] = malloc((size_t)needed + 1);
        if (!values[index]) {
            goto failure;
        }
        if (snprintf(values[index], (size_t)needed + 1, "%s%zu", prefix,
                     index) != needed) {
            goto failure;
        }
    }

    return values;

failure:
    for (index = 0; index < runs; ++index) {
        free(values[index]);
    }
    free(values);
    return NULL;
}

static void free_values(char **values, size_t runs)
{
    size_t index;

    if (!values) {
        return;
    }
    for (index = 0; index < runs; ++index) {
        free(values[index]);
    }
    free(values);
}

static bool read_peak_rss(long *peak_rss_kib)
{
    struct rusage usage;

    if (!peak_rss_kib || getrusage(RUSAGE_SELF, &usage) != 0 ||
        usage.ru_maxrss < 0) {
        return false;
    }
    *peak_rss_kib = usage.ru_maxrss;
    return true;
}

static bool summarize_phase(const double *samples, size_t runs,
                            const struct timespec *cpu_before,
                            const struct timespec *cpu_after,
                            long peak_rss_kib, phase_result *result)
{
    size_t index;
    long double sum = 0.0L;
    double average;
    double minimum;
    double maximum;

    if (!samples || runs == 0 || !cpu_before || !cpu_after ||
        peak_rss_kib < 0 || !result) {
        return false;
    }

    minimum = samples[0];
    maximum = samples[0];
    for (index = 0; index < runs; ++index) {
        if (!isfinite(samples[index]) || samples[index] < 0.0) {
            return false;
        }
        if (samples[index] < minimum) {
            minimum = samples[index];
        }
        if (samples[index] > maximum) {
            maximum = samples[index];
        }
        sum += (long double)samples[index];
    }

    average = (double)(sum / (long double)runs);
    if (!isfinite(average) || average < 0.0 || minimum > average ||
        average > maximum || !elapsed_cpu_seconds(cpu_before, cpu_after,
                                                   &result->cpu_seconds)) {
        return false;
    }

    result->average_us = average;
    result->minimum_us = minimum;
    result->maximum_us = maximum;
    result->peak_rss_kib = peak_rss_kib;
    return true;
}

static bool write_csv(const char *path, size_t runs,
                      const phase_result results[4])
{
    static const char *const names[4] = {"create", "read", "update", "delete"};
    FILE *file;
    size_t index;
    bool ok = true;

    file = fopen(path, "wb");
    if (!file) {
        return false;
    }

    if (fprintf(file, "operation,runs,avg_us,min_us,max_us,cpu_seconds,peak_rss_kib\n") < 0) {
        ok = false;
    }
    for (index = 0; ok && index < 4; ++index) {
        const phase_result *result = &results[index];
        if (fprintf(file, "%s,%zu,%.17g,%.17g,%.17g,%.17g,%ld\n",
                    names[index], runs, result->average_us,
                    result->minimum_us, result->maximum_us,
                    result->cpu_seconds, result->peak_rss_kib) < 0) {
            ok = false;
        }
    }

    if (fclose(file) != 0) {
        ok = false;
    }
    return ok;
}

int main(int argc, char **argv)
{
    size_t runs = 0;
    const char *output_path = NULL;
    char **initial_values = NULL;
    char **updated_values = NULL;
    uint64_t *ids = NULL;
    double *samples[4] = {NULL, NULL, NULL, NULL};
    phase_result results[4];
    fcb_graph *graph = NULL;
    size_t index;
    bool success = false;

    if (!parse_arguments(argc, argv, &runs, &output_path)) {
        return 1;
    }

    initial_values = make_values("record-", runs);
    updated_values = make_values("updated-", runs);
    ids = malloc(runs * sizeof(*ids));
    for (index = 0; index < 4; ++index) {
        samples[index] = malloc(runs * sizeof(*samples[index]));
    }
    if (!initial_values || !updated_values || !ids || !samples[0] ||
        !samples[1] || !samples[2] || !samples[3]) {
        goto cleanup;
    }

    graph = fcb_graph_create(true);
    if (!graph) {
        goto cleanup;
    }

    {
        struct timespec cpu_before;
        struct timespec cpu_after;
        long peak_rss;

        if (clock_gettime(CLOCK_PROCESS_CPUTIME_ID, &cpu_before) != 0) {
            goto cleanup;
        }
        for (index = 0; index < runs; ++index) {
            struct timespec before;
            struct timespec after;
            uint64_t id;

            if (clock_gettime(CLOCK_MONOTONIC, &before) != 0) {
                goto cleanup;
            }
            id = fcb_graph_add_node(graph, initial_values[index]);
            if (clock_gettime(CLOCK_MONOTONIC, &after) != 0 ||
                !duration_microseconds(&before, &after, &samples[0][index])) {
                goto cleanup;
            }
            if (id == 0) {
                goto cleanup;
            }
            ids[index] = id;
        }
        if (fcb_graph_node_count(graph) != runs ||
            fcb_graph_edge_count(graph) != 0 ||
            clock_gettime(CLOCK_PROCESS_CPUTIME_ID, &cpu_after) != 0 ||
            !read_peak_rss(&peak_rss) ||
            !summarize_phase(samples[0], runs, &cpu_before, &cpu_after,
                             peak_rss, &results[0])) {
            goto cleanup;
        }
    }

    {
        struct timespec cpu_before;
        struct timespec cpu_after;
        long peak_rss;

        if (clock_gettime(CLOCK_PROCESS_CPUTIME_ID, &cpu_before) != 0) {
            goto cleanup;
        }
        for (index = 0; index < runs; ++index) {
            struct timespec before;
            struct timespec after;
            const char *value;

            if (clock_gettime(CLOCK_MONOTONIC, &before) != 0) {
                goto cleanup;
            }
            value = fcb_graph_get_node(graph, ids[index]);
            if (clock_gettime(CLOCK_MONOTONIC, &after) != 0 ||
                !duration_microseconds(&before, &after, &samples[1][index])) {
                goto cleanup;
            }
            if (!value || strcmp(value, initial_values[index]) != 0) {
                goto cleanup;
            }
        }
        if (clock_gettime(CLOCK_PROCESS_CPUTIME_ID, &cpu_after) != 0 ||
            !read_peak_rss(&peak_rss) ||
            !summarize_phase(samples[1], runs, &cpu_before, &cpu_after,
                             peak_rss, &results[1])) {
            goto cleanup;
        }
    }

    {
        struct timespec cpu_before;
        struct timespec cpu_after;
        long peak_rss;

        if (clock_gettime(CLOCK_PROCESS_CPUTIME_ID, &cpu_before) != 0) {
            goto cleanup;
        }
        for (index = 0; index < runs; ++index) {
            struct timespec before;
            struct timespec after;
            const char *value;
            bool updated;

            if (clock_gettime(CLOCK_MONOTONIC, &before) != 0) {
                goto cleanup;
            }
            updated = fcb_graph_update_node(graph, ids[index], updated_values[index]);
            if (clock_gettime(CLOCK_MONOTONIC, &after) != 0 ||
                !duration_microseconds(&before, &after, &samples[2][index])) {
                goto cleanup;
            }
            if (!updated) {
                goto cleanup;
            }

            /* Validation is deliberately outside the timed update interval. */
            value = fcb_graph_get_node(graph, ids[index]);
            if (!value || strcmp(value, updated_values[index]) != 0) {
                goto cleanup;
            }
        }
        if (fcb_graph_node_count(graph) != runs ||
            clock_gettime(CLOCK_PROCESS_CPUTIME_ID, &cpu_after) != 0 ||
            !read_peak_rss(&peak_rss) ||
            !summarize_phase(samples[2], runs, &cpu_before, &cpu_after,
                             peak_rss, &results[2])) {
            goto cleanup;
        }
    }

    {
        struct timespec cpu_before;
        struct timespec cpu_after;
        long peak_rss;

        if (clock_gettime(CLOCK_PROCESS_CPUTIME_ID, &cpu_before) != 0) {
            goto cleanup;
        }
        for (index = 0; index < runs; ++index) {
            struct timespec before;
            struct timespec after;
            bool removed;

            if (clock_gettime(CLOCK_MONOTONIC, &before) != 0) {
                goto cleanup;
            }
            removed = fcb_graph_remove_node(graph, ids[index]);
            if (clock_gettime(CLOCK_MONOTONIC, &after) != 0 ||
                !duration_microseconds(&before, &after, &samples[3][index])) {
                goto cleanup;
            }
            if (!removed) {
                goto cleanup;
            }
        }
        if (fcb_graph_node_count(graph) != 0 ||
            fcb_graph_edge_count(graph) != 0 ||
            clock_gettime(CLOCK_PROCESS_CPUTIME_ID, &cpu_after) != 0 ||
            !read_peak_rss(&peak_rss) ||
            !summarize_phase(samples[3], runs, &cpu_before, &cpu_after,
                             peak_rss, &results[3])) {
            goto cleanup;
        }
    }

    if (!write_csv(output_path, runs, results)) {
        goto cleanup;
    }
    success = true;

cleanup:
    fcb_graph_destroy(graph);
    free_values(initial_values, runs);
    free_values(updated_values, runs);
    free(ids);
    for (index = 0; index < 4; ++index) {
        free(samples[index]);
    }

    if (!success) {
        return 1;
    }
    if (printf("{\"ok\":true,\"runs\":%zu,\"rows\":4}\n", runs) < 0) {
        return 1;
    }
    return 0;
}
