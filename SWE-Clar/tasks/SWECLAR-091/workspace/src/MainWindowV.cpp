#include "MainWindowV.h"

#include "MainWindowG.h"

namespace workspace {

MainWindowV::MainWindowV()
    : wxFrame(nullptr, wxID_ANY, constants::kApplicationTitle, wxDefaultPosition, wxSize(900, 600)) {
    CreateStatusBar(1);
    SetStatusText(constants::kStatusReady);
}

}  // namespace workspace

