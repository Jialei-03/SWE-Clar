#pragma once

#include "MainWindowV.h"

namespace workspace {

// The controller is a wx event handler, but all associations are made at
// runtime in the constructor.  There are no static event-table macros.
class MainWindowC final : public wxEvtHandler {
public:
    explicit MainWindowC(MainWindowV& view);

private:
    void on_menu(wxCommandEvent& event);
    void on_tool(wxCommandEvent& event);

    MainWindowV* view_;
};

}  // namespace workspace
