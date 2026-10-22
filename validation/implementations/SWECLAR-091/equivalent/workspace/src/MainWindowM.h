#pragma once

#include <string>

namespace workspace {

// The model is intentionally independent of wxWidgets.  It describes the
// stable shell that the view renders, while the controller owns interaction.
class MainWindowM {
public:
    std::string layout_json() const;
};

}  // namespace workspace
