#include "MainWindowC.h"

namespace workspace {

MainWindowC::MainWindowC(MainWindowV& view) {
    view.Bind(wxEVT_MENU, [&view](wxCommandEvent&) { view.Close(true); }, wxID_EXIT);
}

}  // namespace workspace

