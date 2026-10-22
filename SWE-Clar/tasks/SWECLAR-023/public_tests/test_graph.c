#include "fcb_graph.h"
#include <assert.h>
#include <string.h>
#include <stdio.h>
int main(void) {
    fcb_graph_destroy(NULL);assert(!fcb_graph_node_count(NULL));
    for(int directed=0;directed<=1;directed++) {
        fcb_graph *g=fcb_graph_create(directed);assert(g);
        char value[]="original";uint64_t a=fcb_graph_add_node(g,value);value[0]='X';
        uint64_t b=fcb_graph_add_node(g,""),c=fcb_graph_add_node(g,"third");assert(a&&b&&c&&a!=b&&a!=c&&b!=c);
        const char *borrowed=fcb_graph_get_node(g,a);assert(!strcmp(borrowed,"original"));
        assert(fcb_graph_update_node(g,b,"another"));assert(!strcmp(borrowed,"original"));
        assert(fcb_graph_update_node(g,a,borrowed));assert(!strcmp(fcb_graph_get_node(g,a),"original"));
        char label[]="edge";assert(fcb_graph_add_edge(g,a,b,label));label[0]='X';assert(!strcmp(fcb_graph_get_edge(g,a,b),"edge"));
        assert(!fcb_graph_add_edge(g,a,b,"duplicate"));
        if(!directed) { assert(!fcb_graph_add_edge(g,b,a,"reverse"));assert(!strcmp(fcb_graph_get_edge(g,b,a),"edge")); }
        else assert(fcb_graph_add_edge(g,b,a,"reverse"));
        assert(fcb_graph_add_edge(g,a,a,"self"));assert(fcb_graph_add_edge(g,b,c,"survive"));
        assert(fcb_graph_remove_node(g,a));assert(fcb_graph_edge_count(g)==1);assert(fcb_graph_node_count(g)==2);
        assert(!fcb_graph_get_edge(g,a,b));assert(!fcb_graph_get_edge(g,b,a));assert(!fcb_graph_get_edge(g,a,a));
        assert(!strcmp(fcb_graph_get_edge(g,b,c),"survive"));
        char long_value[4098];memset(long_value,'x',4097);long_value[4097]=0;
        assert(!fcb_graph_update_node(g,b,long_value));assert(!strcmp(fcb_graph_get_node(g,b),"another"));
        assert(!fcb_graph_add_node(g,NULL));assert(!fcb_graph_add_edge(g,0,b,"x"));
        fcb_graph_destroy(g);
    }
    puts("{\"passed\":true,\"scope\":\"Visible C storage ownership and directedness regression\"}");
}
