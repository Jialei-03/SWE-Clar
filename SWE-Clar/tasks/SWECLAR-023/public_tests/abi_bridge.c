#define _POSIX_C_SOURCE 200809L
#include "fcb_graph.h"
#include <inttypes.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

/* Public transport only: no expected graph outcomes or grading policy. */
static int nibble(char c) {
    if(c>='0'&&c<='9')return c-'0';if(c>='a'&&c<='f')return c-'a'+10;return -1;
}
static char *decode(const char *text) {
    if(!text || !strcmp(text,"-"))return NULL;
    if(!strcmp(text,"="))text="";
    size_t n=strlen(text);if(n%2 || n>32768)return NULL;
    char *out=malloc(n/2+1);if(!out)return NULL;
    for(size_t i=0;i<n;i+=2) {int a=nibble(text[i]),b=nibble(text[i+1]);if(a<0||b<0) {free(out);return NULL;}out[i/2]=(char)(16*a+b);}
    out[n/2]=0;return out;
}
static void emit_string(const char *value) {
    if(!value)puts("null");
    else {putchar('"');for(const unsigned char *p=(const unsigned char *)value;*p;p++)printf("%02x",*p);puts("\"");}
}
static uint64_t number(const char *value) {return value?strtoull(value,NULL,10):0;}
int main(void) {
    char *line=NULL;size_t length=0;fcb_graph *g=NULL;const char *held=NULL;
    while(getline(&line,&length,stdin)>=0) {
        char *state=NULL,*op=strtok_r(line," \r\n",&state);if(!op)continue;
        char *first=strtok_r(NULL," \r\n",&state),*second=strtok_r(NULL," \r\n",&state),*third=strtok_r(NULL," \r\n",&state);
        uint64_t a=number(first),b=number(second);
        if(!strcmp(op,"create")) {fcb_graph_destroy(g);g=fcb_graph_create(a!=0);held=NULL;puts(g?"true":"false");}
        else if(!strcmp(op,"destroy")) {fcb_graph_destroy(g);g=NULL;held=NULL;puts("true");}
        else if(!strcmp(op,"counts"))printf("[%zu,%zu]\n",fcb_graph_node_count(g),fcb_graph_edge_count(g));
        else if(!strcmp(op,"add")) {char *s=decode(first);printf("%" PRIu64 "\n",fcb_graph_add_node(g,s));free(s);}
        else if(!strcmp(op,"get"))emit_string(fcb_graph_get_node(g,a));
        else if(!strcmp(op,"update")) {char *s=decode(second);puts(fcb_graph_update_node(g,a,s)?"true":"false");free(s);}
        else if(!strcmp(op,"remove"))puts(fcb_graph_remove_node(g,a)?"true":"false");
        else if(!strcmp(op,"edge_add")) {char *s=decode(third);puts(fcb_graph_add_edge(g,a,b,s)?"true":"false");free(s);}
        else if(!strcmp(op,"edge_get"))emit_string(fcb_graph_get_edge(g,a,b));
        else if(!strcmp(op,"edge_update")) {char *s=decode(third);puts(fcb_graph_update_edge(g,a,b,s)?"true":"false");free(s);}
        else if(!strcmp(op,"edge_remove"))puts(fcb_graph_remove_edge(g,a,b)?"true":"false");
        else if(!strcmp(op,"node_alias"))puts(fcb_graph_update_node(g,a,fcb_graph_get_node(g,a))?"true":"false");
        else if(!strcmp(op,"edge_alias"))puts(fcb_graph_update_edge(g,a,b,fcb_graph_get_edge(g,a,b))?"true":"false");
        else if(!strcmp(op,"hold_node")) {held=fcb_graph_get_node(g,a);emit_string(held);}
        else if(!strcmp(op,"hold_edge")) {held=fcb_graph_get_edge(g,a,b);emit_string(held);}
        else if(!strcmp(op,"held"))emit_string(held);
        else if(!strcmp(op,"save")) {char *s=decode(first);puts(fcb_graph_save(g,s)?"true":"false");free(s);}
        else if(!strcmp(op,"load")) {char *s=decode(first);fcb_graph *loaded=fcb_graph_load(s);free(s);if(loaded) {fcb_graph_destroy(g);g=loaded;held=NULL;}puts(loaded?"true":"false");}
        else if(!strcmp(op,"bfs") || !strcmp(op,"dfs")) {
            if(b>10000) {puts("{\"transport_error\":true}");fflush(stdout);continue;}
            uint64_t *out=malloc(((size_t)b+2)*sizeof(*out));if(!out)return 2;
            for(size_t i=0;i<(size_t)b+2;i++)out[i]=UINT64_MAX;
            bool null_out=third && !strcmp(third,"null");
            size_t count=!strcmp(op,"bfs")?fcb_graph_bfs(g,a,null_out?NULL:out,(size_t)b):fcb_graph_dfs(g,a,null_out?NULL:out,(size_t)b);
            bool bounded=count<=(size_t)b;bool untouched=true;
            if(bounded)for(size_t i=count;i<(size_t)b+2;i++)if(out[i]!=UINT64_MAX)untouched=false;
            printf("{\"count\":%zu,\"bounded\":%s,\"tail_untouched\":%s,\"ids\":[",count,bounded?"true":"false",untouched?"true":"false");
            if(bounded)for(size_t i=0;i<count;i++)printf("%s%" PRIu64,i?",":"",out[i]);
            puts("]}");free(out);
        }
        else if(!strcmp(op,"quit")) {puts("true");fflush(stdout);break;}
        else puts("{\"transport_error\":true}");
        fflush(stdout);
    }
    free(line);fcb_graph_destroy(g);return 0;
}
