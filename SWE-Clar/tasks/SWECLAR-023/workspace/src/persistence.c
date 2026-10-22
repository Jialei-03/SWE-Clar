#include "graph_internal.h"
/* Clarify the durable snapshot contract before implementing persistence. */
bool fcb_graph_save(const fcb_graph *g,const char *path) { (void)g;(void)path;return false; }
fcb_graph *fcb_graph_load(const char *path) { (void)path;return NULL; }
