#include "fcb_graph.h"
#include <stdio.h>
#include <string.h>
int main(void) {
    fcb_graph *g=fcb_graph_create(true);if (!g) return 1;
    uint64_t a=fcb_graph_add_node(g,"Synthetic A"),b=fcb_graph_add_node(g,"Synthetic B"),c=fcb_graph_add_node(g,"Synthetic C");
    int ok=a && b && c && fcb_graph_add_edge(g,a,b,"first") && fcb_graph_add_edge(g,b,c,"second") &&
        fcb_graph_update_node(g,a,"Updated A") && fcb_graph_update_edge(g,a,b,"updated link") && fcb_graph_remove_node(g,c);
    ok=ok && fcb_graph_node_count(g)==2 && fcb_graph_edge_count(g)==1 &&
        strcmp(fcb_graph_get_node(g,a),"Updated A")==0 && strcmp(fcb_graph_get_edge(g,a,b),"updated link")==0 &&
        fcb_graph_get_node(g,c)==NULL && fcb_graph_get_edge(g,b,c)==NULL;
    fcb_graph_destroy(g);
    if (!ok) return 1;
    puts("{\"ok\":true,\"nodes\":2,\"edges\":1}");return 0;
}
