#define _POSIX_C_SOURCE 200809L
#include "fcb_graph.h"
#include <stdio.h>
#include <stdlib.h>
#include <time.h>
#include <errno.h>

/* Public link-time observation helper: no expected outputs or score decisions. */
static unsigned long adds,reads,updates,deletes,monotonic,cpu;
static int registered;
static void report(void) {
    const char *path=getenv("GRAPH_PROBE_LOG");if(!path)return;
    FILE *file=fopen(path,"w");if(!file)return;
    fprintf(file,"{\"add\":%lu,\"read\":%lu,\"update\":%lu,\"delete\":%lu,\"monotonic\":%lu,\"cpu\":%lu}\n",adds,reads,updates,deletes,monotonic,cpu);fclose(file);
}
static void observe(void) {
    if(!registered) {atexit(report);registered=1;}
    const char *value=getenv("GRAPH_PROBE_DELAY_NS");long delay=value?strtol(value,NULL,10):0;
    if(delay>0 && delay<1000000000) {struct timespec wait={0,delay};while(nanosleep(&wait,&wait) && errno==EINTR) {}}
}
uint64_t __real_fcb_graph_add_node(fcb_graph *,const char *);
const char *__real_fcb_graph_get_node(const fcb_graph *,uint64_t);
bool __real_fcb_graph_update_node(fcb_graph *,uint64_t,const char *);
bool __real_fcb_graph_remove_node(fcb_graph *,uint64_t);
int __real_clock_gettime(clockid_t,struct timespec *);
uint64_t __wrap_fcb_graph_add_node(fcb_graph *g,const char *s) {
    ++adds;observe();if(getenv("GRAPH_PROBE_FAIL_ADD"))return 0;return __real_fcb_graph_add_node(g,s);
}
const char *__wrap_fcb_graph_get_node(const fcb_graph *g,uint64_t id) {++reads;observe();return __real_fcb_graph_get_node(g,id);}
bool __wrap_fcb_graph_update_node(fcb_graph *g,uint64_t id,const char *s) {++updates;observe();return __real_fcb_graph_update_node(g,id,s);}
bool __wrap_fcb_graph_remove_node(fcb_graph *g,uint64_t id) {++deletes;observe();return __real_fcb_graph_remove_node(g,id);}
int __wrap_clock_gettime(clockid_t clock,struct timespec *value) {
    if(!registered) {atexit(report);registered=1;}
    if(clock==CLOCK_MONOTONIC)++monotonic;if(clock==CLOCK_PROCESS_CPUTIME_ID)++cpu;
    return __real_clock_gettime(clock,value);
}
